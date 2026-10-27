"""larksync 桌面工具：pywebview 窗口 + 前端（gui/frontend/dist）。

前端通过 window.pywebview.api 调用 Api 的方法，每个方法收一个 dict、返回 JSON；
出错时返回 {"error": "..."}，由前端弹提示。逻辑都在核心库，这里只做转换和保存表格配置。
"""
import base64
import functools
import json
import secrets
import sys
import time
import traceback
from pathlib import Path

from urllib.parse import unquote, urlparse

import webview
from webview.dom import DOMEventHandler

import larksync
from larksync import LarkError, Table, history
from larksync.auth import CONFIG_DIR, Auth, read_json, write_json
from larksync.diff import load, show_key
from larksync.http import call

TABLES = CONFIG_DIR / "tables"   # 每张表一份配置，互相隔离
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))   # PyInstaller 解包目录
INDEX = ROOT / "frontend" / "dist" / "index.html"


def guard(fn):
    @functools.wraps(fn)
    def wrapper(self, arg=None):
        try:
            return fn(self, **(arg or {}))
        except LarkError as e:
            return {"error": str(e)}
        except Exception as e:   # 未预料的错误也别让界面卡死
            traceback.print_exc()
            return {"error": f"内部错误：{e!r}"}
    return wrapper


FILE_TYPES = ("表格文件 (*.csv;*.xlsx)",)


class Api:
    def __init__(self):
        self._window = None   # 下划线开头：pywebview 不会把它暴露给前端
        self._tables = {}   # 表格配置 id → Table
        self._csv = {}      # 表格配置 id → (列名, 行)
        self._plan = None   # (表格配置 id, Plan)

    # -- 应用与登录 --

    @guard
    def state(self):
        cfg = read_json(CONFIG_DIR / "config.json")
        try:
            user = Auth("user").account()
        except LarkError:
            user = None
        return {"configured": bool(cfg.get("app_id") and cfg.get("app_secret")),
                "app_id": cfg.get("app_id", ""), "port": cfg.get("port", 8888), "user": user}

    @guard
    def save_settings(self, app_id, app_secret, port=8888):
        old = read_json(CONFIG_DIR / "config.json")
        larksync.configure(app_id, app_secret or old.get("app_secret", ""), port)
        self._tables.clear()
        return self.state()

    @guard
    def login(self):
        auth = Auth("user")
        token = auth.token()   # 没登录会打开浏览器授权
        if auth.account() == "飞书用户":   # 旧缓存里没存名字，问一次飞书
            info = call("GET", "/authen/v1/user_info", token=token)["data"]
            cache = read_json(CONFIG_DIR / "token.json")
            cache["user"]["name"] = info.get("name", "")
            write_json(CONFIG_DIR / "token.json", cache)
        return self.state()

    @guard
    def logout(self):
        Auth("user").logout()
        self._tables.clear()
        return self.state()

    # -- 表格配置 --

    @guard
    def tables(self):
        return sorted((read_json(p) for p in TABLES.glob("*.json")), key=lambda t: t.get("created", ""))

    @guard
    def probe(self, url):
        t = Table(url)
        return {"title": t.title, "selected": t.tab,
                "tabs": [{"id": i, "title": n} for i, n in t.tabs()]}

    @guard
    def columns(self, url, tab):
        return Table(url, tab=tab).columns()

    @guard
    def add_table(self, url, tab, name):
        t = Table(url, tab=tab)
        profile = {"id": secrets.token_hex(4), "name": name, "url": url, "tab": t.tab,
                   "tab_title": dict(t.tabs()).get(t.tab, ""), "target": t._backend.target,
                   "columns": t.columns(), "key": [], "mapping": {},
                   "created": time.strftime("%Y-%m-%d %H:%M:%S")}
        _save(profile)
        return profile

    @guard
    def remove_table(self, id):
        (TABLES / f"{id}.json").unlink(missing_ok=True)
        self._tables.pop(id, None)
        return {}

    @guard
    def refresh_columns(self, id):
        profile = _profile(id)
        profile["columns"] = self._table(profile).columns()
        _save(profile)
        return profile

    # -- 更新 --

    @guard
    def read_csv(self, table_id, name, data):
        """浏览器开发模式用：前端把文件转成 base64 传过来。"""
        return self._read(table_id, name, base64.b64decode(data))

    @guard
    def pick_file(self, table_id):
        """弹出系统的选择文件窗口；取消返回 {}。"""
        paths = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=FILE_TYPES)
        if not paths:
            return {}
        return self._read(table_id, Path(paths[0]).name, Path(paths[0]).read_bytes())

    @guard
    def read_path(self, table_id, path):
        """拖入文件后，前端拿到完整路径再调这里。"""
        return self._read(table_id, Path(path).name, Path(path).read_bytes())

    def log(self, msg):
        _log(f"前端: {msg}")

    def _read(self, table_id, name, data):
        if Path(name).suffix.lower() not in (".csv", ".xlsx"):
            raise LarkError(f"只支持 CSV 和 xlsx 文件：{name}")
        header, rows = load(data)
        if not header:
            raise LarkError(f"{name} 是空的")
        self._csv[table_id] = (header, rows)
        return {"name": name, "header": header, "count": len(rows)}

    @guard
    def diff(self, table_id, mapping, key):
        """mapping：要用到的 CSV 列 → 表格字段；key：主键字段列表（可多选，组成联合主键）。"""
        profile = _profile(table_id)
        header, rows = self._csv[table_id]
        mapping = {c: f for c, f in mapping.items() if f}
        fields = list(mapping.values())
        dupes = sorted({f for f in fields if fields.count(f) > 1})
        if dupes:
            raise LarkError(f"多个 CSV 列对应到了同一个字段：{'、'.join(dupes)}")
        if not key or any(k not in fields for k in key):
            raise LarkError("请勾选主键，主键必须是已对应的字段")
        local = [{f: r.get(c, "") for c, f in mapping.items()} for r in rows]
        plan = self._table(profile).diff(local, key=key, columns=[f for f in fields if f not in key])
        self._plan = (table_id, plan)

        profile.update(mapping=mapping, key=key)   # 记住，下次拖入同样的 CSV 直接对上
        _save(profile)
        cells = lambda cs: [{"i": i, "key": show_key(c.key), "column": c.column, "old": c.old, "new": c.new}
                            for i, c in enumerate(cs)]
        return {"changed": cells(plan.changed), "conflicts": cells(plan.conflicts),
                "added": [{"i": i, "key": show_key([r[k] for k in plan.key]), "values": r}
                          for i, r in enumerate(plan.added)],
                "unmatched": plan.unmatched}

    @guard
    def apply(self, changed, conflicts, added):
        if not self._plan:
            raise LarkError("预览已失效，请重新生成预览")
        _, plan = self._plan
        plan.changed = [plan.changed[i] for i in changed] + [plan.conflicts[i] for i in conflicts]
        plan.added = [plan.added[i] for i in added]
        record = plan.apply(progress=self._progress)
        self._plan = None
        return {"record_id": record}

    @guard
    def history(self, table_id):
        target = _profile(table_id)["target"]
        out = []
        for r in history.records():
            if r.get("target") != target:
                continue
            out.append({"id": r["id"], "time": r["time"], "status": r["status"],
                        "fills": sum(1 for c in r["changed"] if not c["old"]),
                        "overwrites": sum(1 for c in r["changed"] if c["old"]),
                        "added": len(r["added"])})
        return out

    @guard
    def undo(self, table_id, record_id):
        self._table(_profile(table_id)).undo(record_id, progress=self._progress)
        return {}

    def _progress(self, stage, done, total):
        """把写入 / 撤销进度推给前端（window.larksyncProgress）。"""
        if self._window:
            msg = json.dumps({"stage": stage, "done": done, "total": total}, ensure_ascii=False)
            self._window.evaluate_js(f"window.larksyncProgress && window.larksyncProgress({msg})")

    def _table(self, profile):
        if profile["id"] not in self._tables:
            self._tables[profile["id"]] = Table(profile["url"], tab=profile["tab"])
        return self._tables[profile["id"]]


def _profile(id):
    p = read_json(TABLES / f"{id}.json")
    if not p:
        raise LarkError("这张表的配置不见了，请重新添加")
    return p


def _save(profile):
    write_json(TABLES / f"{profile['id']}.json", profile)


_gtk_dropped = []   # Linux：自己从 GTK 拖放数据里取到的路径


def _on_drop(window, event):
    """拖入文件：只有在 Python 里订阅 drop，pywebview 才会给出文件的完整路径（Windows / Mac）。

    Linux 上 pywebview 取不到路径，改用 _hook_gtk_drop 存下的；两条通道先后不定，稍等一下。
    """
    files = event.get("dataTransfer", {}).get("files") or []
    path = files[0].get("pywebviewFullPath") if files else None
    for _ in range(20):
        if path or not sys.platform.startswith("linux"):
            break
        if _gtk_dropped:
            path = _gtk_dropped.pop()
            _gtk_dropped.clear()
        else:
            time.sleep(0.05)
    _log(f"drop: path={path!r}")
    if path:
        window.evaluate_js(f"window.larksyncDrop && window.larksyncDrop({json.dumps(path)})")


def _hook_gtk_drop(window):
    """pywebview 在 GTK 上用 get_text() 读拖放数据，文件管理器给的是 URI 列表，读出来是空的。"""
    from gi.repository import GLib
    from webview.platforms.gtk import BrowserView

    def on_data(_widget, _ctx, _x, _y, data, _info, _time):
        uris = [u for u in (data.get_uris() or []) if u.startswith("file://")]
        _gtk_dropped[:] = [unquote(urlparse(u).path) for u in uris]
        return False

    def connect():
        BrowserView.instances[window.uid].webview.connect("drag-data-received", on_data)
        return False

    GLib.idle_add(connect)


def _log(msg):
    print(f"[larksync] {msg}", file=sys.stderr, flush=True)


def main():
    api = Api()
    window = webview.create_window("larksync", url=str(INDEX), js_api=api,
                                   width=1120, height=760, min_size=(880, 600))
    api._window = window

    def bind():
        events = window.dom.document.events
        events.dragover += DOMEventHandler(lambda e: None, prevent_default=True)
        events.drop += DOMEventHandler(lambda e: _on_drop(window, e), prevent_default=True)
        if sys.platform.startswith("linux"):
            _hook_gtk_drop(window)
        _log("已订阅拖入事件")

    window.events.loaded += bind
    webview.start()


if __name__ == "__main__":
    main()
