"""多维表格后端：字段即列，record_id 即行。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .http import LarkError, call
from .sheets import cell_str

_BATCH = 500
_OR_MAX = 50          # 一次查询里 OR 的条件数
_LOOKUP_MAX = 2000    # 主键值再多就不如直接读全表
_WORKERS = 5
_FILTERABLE = {1, 13}  # 能按「等于」精确查询的主键类型：文本、电话
_WRITABLE = {1, 2, 3, 4, 5, 7, 13}   # 文本 数字 单选 多选 日期 复选框 电话
_DATES = {5, 1001, 1002}             # 日期 创建时间 修改时间
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M",
                 "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S")
_TRUE = {"true", "1", "是", "yes", "y", "✓"}
_FALSE = {"false", "0", "否", "no", "n"}


class Bitable:
    def __init__(self, auth, app_token, table_id=None):
        self.auth = auth
        tables = call("GET", f"/bitable/v1/apps/{app_token}/tables", token=auth.token(),
                      params={"page_size": 100})["data"].get("items") or []
        self._tabs = [(t["table_id"], t.get("name", "")) for t in tables]
        if not self._tabs:
            raise LarkError("这个多维表格里没有数据表")
        table_id = table_id or self._tabs[0][0]
        if table_id not in dict(self._tabs):
            ids = [f"{i}（{n}）" for i, n in self._tabs]
            raise LarkError(f"没有 table={table_id} 的数据表，现有：{', '.join(ids)}")
        self.target = f"bitable:{app_token}:{table_id}"
        app = call("GET", f"/bitable/v1/apps/{app_token}", token=auth.token())["data"].get("app") or {}
        self.doc_title = app.get("name", "")
        self._base = f"/bitable/v1/apps/{app_token}/tables/{table_id}"
        self._fields = {}   # 字段名 → 类型，每次读取都刷新

    def tabs(self):
        return list(self._tabs)

    def columns(self):
        self._fields = {f["field_name"]: f["type"] for f in self._pages("GET", "/fields", 100)}
        return list(self._fields)

    def read(self):
        """返回 (列名, 记录, record_id)；全空的记录跳过。"""
        header = self.columns()
        rows, refs = [], []
        for it in self._pages("POST", "/records/search", 500, json={}):
            row = self._row(it["fields"])
            if any(row.values()):
                rows.append(row)
                refs.append(it["record_id"])
        return header, rows, refs

    def lookup(self, key, values):
        """主键第一列取值在 values 里的记录。返回 (记录, record_id, 表的总记录数)。

        按条件查询，每次 OR 50 个值、并发 5 个请求；主键不是文本类或值太多时退回读全表。
        """
        self.columns()
        values = sorted(v for v in values if v)
        if self._fields.get(key[0]) not in _FILTERABLE or len(values) > _LOOKUP_MAX:
            _, rows, refs = self.read()
            return rows, refs, len(rows)

        def search(chunk):
            flt = {"conjunction": "or", "conditions": [
                {"field_name": key[0], "operator": "is", "value": [v]} for v in chunk]}
            return [(it["record_id"], self._row(it["fields"]))
                    for it in self._pages("POST", "/records/search", 500, json={"filter": flt})]

        chunks = [values[i:i + _OR_MAX] for i in range(0, len(values), _OR_MAX)]
        with ThreadPoolExecutor(_WORKERS) as pool:
            total = pool.submit(self._total)
            found = [hit for part in pool.map(search, chunks) for hit in part]
        return [r for _, r in found], [ref for ref, _ in found], total.result()

    def _total(self):
        return call("POST", self._base + "/records/search", token=self.auth.token(),
                    params={"page_size": 1}, json={})["data"].get("total", 0)

    def fetch(self, refs):
        """只读指定的记录：{record_id: 记录}，已删除的不在结果里。"""
        self.columns()
        out = {}
        for i in range(0, len(refs), 100):
            data = self._post("/records/batch_get", {"record_ids": refs[i:i + 100]})
            for it in data.get("records") or []:
                out[it["record_id"]] = self._row(it.get("fields") or {})
        return out

    def writable(self, name):
        return self._fields.get(name) in _WRITABLE

    def canon(self, name, s):
        """本地文本按字段类型规整成读回来的样子（如 1.50 → 1.5），值不合法就报错。"""
        if not s or not self.writable(name):
            return s
        return self._text(name, self._value(name, s))

    def update(self, cells):
        fields = {}
        for ref, col, val in cells:
            fields.setdefault(ref, {})[col] = self._value(col, val)
        recs = [{"record_id": r, "fields": f} for r, f in fields.items()]
        for i in range(0, len(recs), _BATCH):
            self._post("/records/batch_update", {"records": recs[i:i + _BATCH]})

    def create(self, rows):
        """分批新增，每批写完 yield 这批的 record_id。"""
        for i in range(0, len(rows), _BATCH):
            recs = [{"fields": {c: self._value(c, v) for c, v in r.items() if v}}
                    for r in rows[i:i + _BATCH]]
            data = self._post("/records/batch_create", {"records": recs})
            yield [r["record_id"] for r in data["records"]]

    def delete(self, refs):
        for i in range(0, len(refs), _BATCH):
            self._post("/records/batch_delete", {"records": refs[i:i + _BATCH]})

    def add_fields(self, names):
        for n in names:
            self._post("/fields", {"field_name": n, "type": 1})
            self._fields[n] = 1

    # -- 值转换 --

    def _row(self, fields):
        return {h: self._text(h, fields.get(h)) for h in self._fields}

    def _text(self, name, v):
        if self._fields.get(name) in _DATES and isinstance(v, (int, float)):
            dt = datetime.fromtimestamp(v / 1000)
            return dt.strftime("%Y-%m-%d" if dt.time() == datetime.min.time() else "%Y-%m-%d %H:%M")
        return cell_str(v)

    def _value(self, name, s):
        """文本 → 飞书字段值；空串表示清空。"""
        if not s:
            return None
        t = self._fields[name]
        if t == 2:
            s = s.replace(",", "")
            try:
                return int(s)
            except ValueError:
                pass
            try:
                n = float(s)
            except ValueError:
                raise LarkError(f"{s!r} 不是数字") from None
            return int(n) if n.is_integer() else n
        if t == 4:
            return [x.strip() for x in s.split(",") if x.strip()]
        if t == 5:
            for fmt in _DATE_FORMATS:
                try:
                    return int(datetime.strptime(s, fmt).timestamp() * 1000)
                except ValueError:
                    pass
            raise LarkError(f"{s!r} 不是日期（支持 2026-01-02、2026/01/02、可带 HH:MM[:SS]）")
        if t == 7:
            if s.lower() in _TRUE:
                return True
            if s.lower() in _FALSE:
                return False
            raise LarkError(f"{s!r} 不是勾选值（支持 true/false、是/否、1/0）")
        return s

    # -- HTTP --

    def _pages(self, method, path, size, json=None):
        page = None
        while True:
            params = {"page_size": size, **({"page_token": page} if page else {})}
            data = call(method, self._base + path, token=self.auth.token(),
                        params=params, json=json)["data"]
            yield from data.get("items") or []
            if not data.get("has_more"):
                return
            page = data["page_token"]

    def _post(self, path, payload):
        return call("POST", self._base + path, token=self.auth.token(), json=payload)["data"]
