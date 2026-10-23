"""本机飞书应用配置与登录。

每人用自己的飞书应用（表格权限因人而异），configure() 一次即可。
user 身份（默认）首次登录打开浏览器，之后缓存 token、自动续期；tenant 身份无需登录。
"""
import json
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import platformdirs

from .http import BASE, LarkError, call

CONFIG_DIR = Path(platformdirs.user_config_dir("larksync", appauthor=False))
CONFIG_FILE = CONFIG_DIR / "config.json"
TOKEN_FILE = CONFIG_DIR / "token.json"

SCOPES = "wiki:wiki:readonly sheets:spreadsheet bitable:app"
_EXPIRY_MARGIN_S = 300   # 提前 5 分钟判过期，免得请求发出的瞬间失效
_LOGIN_TIMEOUT_S = 180


def configure(app_id, app_secret, port=8888):
    """保存本机的飞书应用。port 要和应用后台配置的重定向地址 http://localhost:<port>/callback 一致。"""
    write_json(CONFIG_FILE, {"app_id": app_id.strip(), "app_secret": app_secret.strip(),
                              "port": int(port)})


def load_config():
    cfg = read_json(CONFIG_FILE)
    app_id = os.environ.get("LARKSYNC_APP_ID") or cfg.get("app_id")
    app_secret = os.environ.get("LARKSYNC_APP_SECRET") or cfg.get("app_secret")
    if not app_id or not app_secret:
        raise LarkError("还没配置飞书应用：先运行 larksync.configure(app_id, app_secret)，"
                        "或设置环境变量 LARKSYNC_APP_ID / LARKSYNC_APP_SECRET")
    return app_id, app_secret, int(cfg.get("port") or 8888)


class Auth:
    def __init__(self, method="user"):
        if method not in ("user", "tenant"):
            raise LarkError(f'auth 只能是 "user" 或 "tenant"，收到 {method!r}')
        self.method = method
        self.app_id, self.app_secret, self.port = load_config()

    def token(self):
        c = self._cached()
        if c and c["expires_at"] > time.time():
            return c["access_token"]
        if self.method == "tenant":
            body = call("POST", "/auth/v3/tenant_access_token/internal",
                        json={"app_id": self.app_id, "app_secret": self.app_secret})
            return self._save({"access_token": body["tenant_access_token"],
                               "expires_in": body.get("expire")})
        if c and (t := self._refresh(c.get("refresh_token"))):
            return t
        return self._login()

    def account(self):
        """已登录的用户名（只看本地缓存，不联网）；没登录返回 None。"""
        c = self._cached()
        if not c or (c["expires_at"] <= time.time() and not c.get("refresh_token")):
            return None
        return c.get("name") or "飞书用户"

    def logout(self):
        d = read_json(TOKEN_FILE)
        if d.pop(self.method, None) is not None:
            write_json(TOKEN_FILE, d)

    # -- 缓存：按 app_id 隔离，换应用自动作废 --

    def _cached(self):
        d = read_json(TOKEN_FILE)
        block = d.get(self.method) if d.get("app_id") == self.app_id else None
        if isinstance(block, dict) and block.get("access_token"):
            return block
        return None

    def _save(self, data):
        token = data.get("access_token")
        if not token:
            raise LarkError(f"飞书没有返回 access_token：{data}")
        d = read_json(TOKEN_FILE)
        if d.get("app_id") != self.app_id:
            d = {"app_id": self.app_id}
        d[self.method] = {
            "access_token": token,
            "refresh_token": data.get("refresh_token", ""),
            "expires_at": time.time() + float(data.get("expires_in") or 0) - _EXPIRY_MARGIN_S,
            "name": data.get("name") or (d.get(self.method) or {}).get("name", ""),
        }
        try:
            write_json(TOKEN_FILE, d)
        except OSError:
            pass   # 缓存写不下去不该让整个流程失败
        return token

    # -- user 身份：续期 -> 浏览器登录 --

    def _app_token(self):
        body = call("POST", "/auth/v3/app_access_token/internal",
                    json={"app_id": self.app_id, "app_secret": self.app_secret})
        return body["app_access_token"]

    def _refresh(self, refresh_token):
        if not refresh_token:
            return None
        try:
            body = call("POST", "/authen/v1/refresh_access_token", token=self._app_token(),
                        json={"grant_type": "refresh_token", "refresh_token": refresh_token})
        except LarkError:
            # refresh_token 每次续期都会轮换：可能是别的进程刚续过，再看一眼缓存
            c = self._cached()
            if c and c["expires_at"] > time.time():
                return c["access_token"]
            return None
        return self._save(body.get("data") or {})

    def _login(self):
        got = {}
        done = threading.Event()

        class Callback(BaseHTTPRequestHandler):
            def do_GET(self):
                got["code"] = (parse_qs(urlparse(self.path).query).get("code") or [None])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("<h3>飞书授权完成，可以关闭这个页面了。</h3>".encode())
                done.set()

            def log_message(self, *a):
                pass

        try:
            server = HTTPServer(("localhost", self.port), Callback)
        except OSError as e:
            raise LarkError(f"本机端口 {self.port} 被占用：换个端口重新 configure，"
                            f"并同步修改应用后台的重定向地址") from e
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"{BASE}/authen/v1/index?" + urlencode({
            "app_id": self.app_id, "scope": SCOPES,
            "redirect_uri": f"http://localhost:{self.port}/callback"})
        print(f"请在浏览器中登录飞书并授权（没有自动打开就手动访问）：\n  {url}",
              file=sys.stderr, flush=True)
        webbrowser.open(url)
        try:
            if not done.wait(_LOGIN_TIMEOUT_S) or not got.get("code"):
                raise LarkError(f"{_LOGIN_TIMEOUT_S} 秒内没有完成飞书授权。服务器上请改用 "
                                f'auth="tenant"，或拷贝本机的 {TOKEN_FILE.name}')
        finally:
            server.shutdown()
            server.server_close()
        body = call("POST", "/authen/v1/access_token", token=self._app_token(),
                    json={"grant_type": "authorization_code", "code": got["code"]})
        return self._save(body.get("data") or {})


def read_json(path):
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)   # 原子替换，并发写入不会留下半个文件
