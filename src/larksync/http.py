"""飞书开放平台 HTTP：网络错误和限流自动退避重试，错误码统一转成 LarkError。"""
import os
import time

import httpx

BASE = "https://open.feishu.cn/open-apis"
_TRIES = 5
_RATE_LIMITED = {99991400, 1254290, 1254291}   # 频控、多维表格写冲突


class LarkError(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


_client = None
_client_pid = None


def _http():
    # fork 出来的子进程不能复用父进程的连接池
    global _client, _client_pid
    if _client is None or _client_pid != os.getpid():
        _client = httpx.Client(base_url=BASE, timeout=30)
        _client_pid = os.getpid()
    return _client


def call(method, path, *, token=None, params=None, json=None):
    """返回飞书响应的完整 body（code == 0）。"""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    for attempt in range(_TRIES):
        last = attempt == _TRIES - 1
        try:
            resp = _http().request(method, path, headers=headers, params=params, json=json)
        except httpx.TransportError as e:
            if last:
                raise LarkError(f"网络错误：{e}") from e
            time.sleep(2 ** attempt)
            continue
        try:
            body = resp.json()
        except ValueError:
            body = {}
        code = body.get("code")
        retryable = resp.status_code == 429 or resp.status_code >= 500 or code in _RATE_LIMITED
        if retryable and not last:
            time.sleep(2 ** attempt)
            continue
        if code not in (0, None) or resp.is_error:
            shown = code if code is not None else f"HTTP {resp.status_code}"
            raise LarkError(f"飞书接口返回错误 {shown}：{body.get('msg') or resp.text[:300]}", code)
        return body
