"""写入记录：每次写飞书之前先落盘，撤销时据此还原。"""
import secrets
import time
from dataclasses import asdict

from .auth import CONFIG_DIR, read_json, write_json
from .http import LarkError

DIR = CONFIG_DIR / "history"


def new(url, target, key, changed, added):
    rec = {
        "id": time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "url": url,
        "target": target,
        "key": list(key),
        "status": "pending",        # pending → done → undone；中途失败会停在 pending
        "changed": [asdict(c) for c in changed],
        "added": added,
        "created": [],              # 新增行的 ref，和 added 一一对应，每批写完就更新
    }
    save(rec)
    return rec


def save(rec):
    write_json(DIR / f"{rec['id']}.json", rec)


def load(record_id):
    rec = read_json(DIR / f"{record_id}.json")
    if not rec:
        raise LarkError(f"找不到写入记录 {record_id}")
    return rec


def records():
    """所有写入记录，新的在前。"""
    return [read_json(p) for p in sorted(DIR.glob("*.json"), reverse=True)]
