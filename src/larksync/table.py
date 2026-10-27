"""Table：用链接打开一张飞书表，拉取 / 按主键更新 / 撤销。"""
import csv
from contextlib import contextmanager
from urllib.parse import parse_qs, urlparse

from . import history
from .auth import SCOPES, Auth
from .bitable import Bitable
from .diff import Plan, brief, compute, keyed, load, show_key
from .http import LarkError, call
from .sheets import Sheets

_DENIED = {91403, 131006, 1254302}
_PROGRESS_STEP = 1000   # 每写这么多格回调一次进度
_MISSING_SCOPE = {99991672, 99991679}


class Table:
    def __init__(self, url, auth="user", tab=None):
        """tab：工作表 / 数据表 id，不传就用链接里的 ?sheet= / ?table=，再没有就用第一个。"""
        self.url = url
        self._auth = Auth(auth)
        kind, token, sub = parse_url(url)
        sub = tab or sub
        title = None
        with self._explained():
            if kind == "wiki":
                node = call("GET", "/wiki/v2/spaces/get_node", token=self._auth.token(),
                            params={"token": token, "obj_type": "wiki"})["data"]["node"]
                kind, token, title = node["obj_type"], node["obj_token"], node.get("title")
            if kind == "sheet":
                self._backend = Sheets(self._auth, token, sub)
            elif kind == "bitable":
                self._backend = Bitable(self._auth, token, sub)
            else:
                raise LarkError(f"不支持的文档类型 {kind!r}，只支持电子表格和多维表格")
        self.title = title or self._backend.doc_title   # 文档标题（知识库链接用节点标题）
        self.tab = self._backend.target.split(":")[2]  # 当前工作表 / 数据表 id

    def tabs(self):
        """同一文档里的所有工作表 / 数据表：[(id, 标题)]。"""
        return self._backend.tabs()

    def columns(self):
        """表头（只读表头，不读数据）。"""
        with self._explained():
            return self._backend.columns()

    def pull(self, path=None):
        """拉取整张表，返回 list[dict]；传 path 时同时写成 CSV（utf-8-sig，Excel 可直接打开）。"""
        with self._explained():
            header, rows, _ = self._backend.read()
        if path is not None:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=header)
                w.writeheader()
                w.writerows(rows)
        return rows

    def diff(self, source, key, columns=None):
        """按主键比较本地数据（CSV 路径或 list[dict]）和在线表，见 Plan。

        columns 为空时比较本地所有非主键列；新增行写入本地和在线共有的所有可写列。
        """
        local_header, local_rows = load(source)
        with self._explained():
            header = self._backend.columns()
        key = [key] if isinstance(key, str) else list(key)
        cols = list(columns) if columns is not None else [c for c in local_header if c not in key]
        for c in key + cols:
            if c not in local_header:
                raise LarkError(f"本地数据里没有列「{c}」")
            if c not in header:
                tip = "；只更新部分列请传 columns=[...]" if columns is None else ""
                raise LarkError(f"在线表里没有列「{c}」{tip}")
        readonly = [c for c in cols if not self._backend.writable(c)]
        if readonly:
            raise LarkError(f"这些列在线表里是只读的，不能更新：{'、'.join(readonly)}")

        common = [c for c in local_header if c in header]
        local_rows = self._canon(local_rows, common)
        wanted = {k[0] for k in keyed(local_rows, key, local=True)}
        with self._explained():   # 只读主键和本地相同的行，表再大也快
            rows, refs, total = self._backend.lookup(key, wanted)
        changed, conflicts, added, matched = compute(rows, refs, local_rows, key, cols)
        if added and not all(self._backend.writable(c) for c in key):
            raise LarkError("主键列在线表里是只读的，不能新增行")
        writable = [c for c in common if self._backend.writable(c)]
        added = [{c: r[c] for c in writable} for r in added]
        return Plan(self, key, changed, conflicts, added, total - matched)

    def init(self, source):
        """用首个 CSV 初始化空表：补齐在线表缺少的列，再写入全部行。返回写入记录 id。"""
        local_header, local_rows = load(source)
        with self._explained():
            header, rows, _ = self._backend.read()
            if rows:
                raise LarkError("表里已经有数据，init 只能用于空表；更新请用 diff")
            self._backend.add_fields([c for c in local_header if c not in header])
            readonly = [c for c in local_header if not self._backend.writable(c)]
            if readonly:
                raise LarkError(f"这些列在线表里是只读的，不能写入：{'、'.join(readonly)}")
            added = self._canon(local_rows, local_header)
            rec = history.new(self.url, self._backend.target, [], [], added)
            self._write(rec, [], added)
        return rec["id"]

    def undo(self, record_id, progress=None):
        """撤销一次写入：还原改过的格子、删掉新增的行。之后又被别人改过的话整体中止。

        progress(阶段, 已完成, 总数)：可选的进度回调，阶段是「检查」或「撤销」。
        """
        rec = history.load(record_id)
        if rec["target"] != self._backend.target:
            raise LarkError(f"写入记录 {record_id} 不属于这张表（它属于 {rec['url']}）")
        if rec["status"] == "undone":
            raise LarkError(f"写入记录 {record_id} 已经撤销过了")
        with self._explained():
            _report(progress, "检查", 0, len(rec["changed"]) + len(rec["created"]))
            current = self._backend.fetch([ch["ref"] for ch in rec["changed"]] + rec["created"])
            conflicts, cells, drop = [], [], []
            for ch in rec["changed"]:
                cur = _cell(current.get(ch["ref"]), rec["key"], tuple(ch["key"]), ch["column"])
                if cur == ch["new"]:
                    cells.append((ch["ref"], ch["column"], ch["old"]))
                elif cur != ch["old"]:   # 等于 old 说明这格当时没写成，跳过
                    conflicts.append(_conflict(ch["key"], ch["column"], ch["new"], cur))
            for ref, row in zip(rec["created"], rec["added"]):
                cur = current.get(ref)
                if cur is None:
                    continue   # 已经被删了
                if any(cur.get(c, "") != v for c, v in row.items()):
                    who = show_key([row.get(c, "") for c in rec["key"]]) if rec["key"] else ref
                    conflicts.append(f"新增的行 {who} 之后被改过")
                else:
                    drop.append(ref)
            if conflicts:
                raise LarkError("撤销会覆盖别人之后的修改，已中止：\n" + brief(conflicts))
            total = len(cells) + len(drop)
            for i in range(0, len(cells), _PROGRESS_STEP):
                self._backend.update(cells[i:i + _PROGRESS_STEP])
                _report(progress, "撤销", min(i + _PROGRESS_STEP, len(cells)), total)
            self._backend.delete(drop)
            _report(progress, "撤销", total, total)
        rec["status"] = "undone"
        history.save(rec)

    def _apply(self, plan, progress=None):
        with self._explained():
            _report(progress, "检查", 0, len(plan.changed) + len(plan.added))
            current = self._backend.fetch([ch.ref for ch in plan.changed])   # 只读涉及的行
            taken = {}
            if plan.added:   # 确认新增的主键没被别人抢先加上
                rows, refs, _ = self._backend.lookup(plan.key, {r[plan.key[0]] for r in plan.added})
                taken = keyed(rows, plan.key, refs)
            conflicts, cells = [], []
            for ch in plan.changed:
                cur = _cell(current.get(ch.ref), plan.key, ch.key, ch.column)
                if cur != ch.old:
                    conflicts.append(_conflict(ch.key, ch.column, ch.old, cur))
                else:
                    cells.append((ch.ref, ch.column, ch.new))
            for r in plan.added:
                k = tuple(r[c] for c in plan.key)
                if k in taken:
                    conflicts.append(f"{show_key(k)}：已经被别人新增")
            if conflicts:
                raise LarkError("在线表在 diff 之后被改过，已中止写入，请重新 diff：\n"
                                + brief(conflicts))
            rec = history.new(self.url, self._backend.target, plan.key, plan.changed, plan.added)
            self._write(rec, cells, plan.added, progress)
        return rec["id"]

    def _write(self, rec, cells, added, progress=None):
        total = len(cells) + len(added)
        for i in range(0, len(cells), _PROGRESS_STEP):
            self._backend.update(cells[i:i + _PROGRESS_STEP])
            _report(progress, "写入", min(i + _PROGRESS_STEP, len(cells)), total)
        for refs in self._backend.create(added):
            if not refs:
                continue
            rec["created"] += refs
            history.save(rec)   # 每批落盘，中途失败也能撤销已写入的部分
            _report(progress, "写入", len(cells) + len(rec["created"]), total)
        rec["status"] = "done"
        history.save(rec)

    def _canon(self, rows, cols):
        errors, out = [], []
        for i, r in enumerate(rows, 1):
            r = dict(r)
            for c in cols:
                try:
                    r[c] = self._backend.canon(c, r.get(c, ""))
                except LarkError as e:
                    errors.append(f"第 {i} 条「{c}」：{e}")
            out.append(r)
        if errors:
            raise LarkError("本地数据里有写不进在线表的值：\n" + brief(errors))
        return out

    @contextmanager
    def _explained(self):
        """把权限类错误码翻译成能照着做的提示。"""
        try:
            yield
        except LarkError as e:
            if e.code in _DENIED:
                hint = ("把你的应用加为这张表的协作者，或改用 auth=\"user\""
                        if self._auth.method == "tenant" else "确认你的飞书账号能编辑这张表")
                raise LarkError(f"没有权限访问 {self.url}：{hint}", e.code) from e
            if e.code in _MISSING_SCOPE:
                raise LarkError(f"应用缺少权限：请在飞书开发者后台开通 {SCOPES} 并发布，"
                                f"然后重新登录", e.code) from e
            raise


def _report(progress, stage, done, total):
    if progress:
        progress(stage, done, total)


def _cell(row, key_cols, key, column):
    """行还在、主键没变时返回该格的值，否则 None（行被删或电子表格行位置变了）。"""
    if row is None or tuple(row.get(c, "") for c in key_cols) != tuple(key):
        return None
    return row.get(column, "")


def _conflict(key, column, expected, current):
    now = "（行已被删除）" if current is None else repr(current)
    return f"{show_key(key)}「{column}」：应为 {expected!r}，现在是 {now}"


def parse_url(url):
    """返回 (类型, token, sheet/table id)；类型为 wiki / sheet / bitable。"""
    u = urlparse(url.strip())
    parts = [p for p in u.path.split("/") if p]
    q = parse_qs(u.query)
    sub = (q.get("sheet") or q.get("table") or [None])[0]
    kinds = {"wiki": "wiki", "sheets": "sheet", "base": "bitable"}
    if len(parts) >= 2 and parts[-2] in kinds:
        return kinds[parts[-2]], parts[-1], sub
    raise LarkError(f"认不出的飞书链接：{url}（支持 /wiki/、/sheets/、/base/ 链接）")
