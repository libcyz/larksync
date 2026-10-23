"""电子表格后端：第 1 行是表头，下面每行一条记录，行号即 ref。"""
from .http import LarkError, call

_ROWS_PER_READ = 2000
_CELLS_PER_WRITE = 5000
_DIM_MAX = 5000   # 一次最多增删的行 / 列数


class Sheets:
    def __init__(self, auth, token, sheet_id=None):
        self.auth, self.token = auth, token
        self._api = f"/sheets/v2/spreadsheets/{token}"
        tabs = self._meta()
        tab = next((t for t in tabs if t.get("sheetId") == sheet_id), None) if sheet_id \
            else (tabs[0] if tabs else None)
        if tab is None:
            ids = [f"{t.get('sheetId')}（{t.get('title')}）" for t in tabs]
            raise LarkError(f"没有 sheet={sheet_id} 的工作表，现有：{', '.join(ids)}")
        self.sheet_id = tab["sheetId"]
        self.title = tab.get("title", "")
        self.target = f"sheet:{token}:{self.sheet_id}"
        self._size(tab)
        self._col = {}    # 列名 → 列下标，每次读取都刷新
        self._last = 1    # 最后一个非空数据行的行号

    def tabs(self):
        return list(self._tabs)

    def columns(self):
        self._refresh()
        header = self._grid(1, 1)
        return self._index(header[0] if header else [])

    def read(self):
        """返回 (列名, 记录, 行号)。"""
        self._refresh()
        grid = []
        for start in range(1, self._rows + 1, _ROWS_PER_READ):
            grid += self._grid(start, min(start + _ROWS_PER_READ - 1, self._rows))
        header, rows, refs = records(grid)
        self._index(grid[0] if grid else [])
        self._last = max(refs, default=1)
        return header, rows, refs

    def lookup(self, key, values):
        """主键第一列取值在 values 里的行。电子表格读全表很快，直接读全表。返回 (记录, 行号, 总行数)。"""
        _, rows, refs = self.read()
        return rows, refs, len(rows)

    def fetch(self, refs):
        """{行号: 记录}。电子表格读全表也很快，直接读全表再挑。"""
        _, rows, all_refs = self.read()
        current = dict(zip(all_refs, rows))
        return {r: current[r] for r in refs if r in current}

    def writable(self, name):
        return True

    def canon(self, name, s):
        return s

    def update(self, cells):
        """按列把相邻行合并成一个区域写入。"""
        by_col = {}
        for row, col, val in cells:
            by_col.setdefault(self._col[col], []).append((row, val))
        ranges = []
        for ci, items in by_col.items():
            items.sort()
            run = [items[0]]
            for it in items[1:]:
                if it[0] != run[-1][0] + 1:
                    ranges.append(self._range(ci, ci, run[0][0], [[v] for _, v in run]))
                    run = []
                run.append(it)
            ranges.append(self._range(ci, ci, run[0][0], [[v] for _, v in run]))
        self._write(ranges)

    def create(self, rows):
        """追加到最后一个数据行之后，不够就先加行；每批写完 yield 这批的行号。"""
        if not rows:
            return
        width = max(self._col.values()) + 1
        names = {i: c for c, i in self._col.items()}
        start = self._last + 1
        self._grow("ROWS", start + len(rows) - 1 - self._rows)
        step = max(1, _CELLS_PER_WRITE // width)
        for i in range(0, len(rows), step):
            chunk = rows[i:i + step]
            values = [[r.get(names.get(j), "") for j in range(width)] for r in chunk]
            self._write([self._range(0, width - 1, start + i, values)])
            yield list(range(start + i, start + i + len(chunk)))
        self._last = start + len(rows) - 1

    def delete(self, refs):
        """从下往上删，避免删掉上面的行后下面的行号变化。"""
        for hi, lo in _runs(sorted(refs, reverse=True)):
            call("DELETE", f"{self._api}/dimension_range", token=self.auth.token(),
                 json={"dimension": {"sheetId": self.sheet_id, "majorDimension": "ROWS",
                                     "startIndex": lo, "endIndex": hi}})

    def add_fields(self, names):
        """在表头最后一列之后追加列名。"""
        if not names:
            return
        start = max(self._col.values(), default=-1) + 1
        self._grow("COLUMNS", start + len(names) - self._cols)
        self._write([self._range(start, start + len(names) - 1, 1, [list(names)])])
        self._col.update({n: start + i for i, n in enumerate(names)})

    # -- 内部 --

    def _meta(self):
        data = call("GET", f"{self._api}/metainfo", token=self.auth.token())["data"]
        self.doc_title = (data.get("properties") or {}).get("title", "")
        tabs = data.get("sheets") or []
        self._tabs = [(t.get("sheetId"), t.get("title", "")) for t in tabs]
        return tabs

    def _refresh(self):
        """行列数可能被别人改过，读之前先刷新。"""
        tab = next((t for t in self._meta() if t.get("sheetId") == self.sheet_id), None)
        if tab is None:
            raise LarkError(f"工作表 {self.title}（{self.sheet_id}）已被删除")
        self._size(tab)

    def _size(self, tab):
        self._rows = int(tab.get("rowCount") or 0)
        self._cols = int(tab.get("columnCount") or 0)

    def _index(self, header):
        names = [h for h in header if h]
        records([header])   # 顺便检查重复列名
        self._col = {h: i for i, h in enumerate(header) if h}
        return names

    def _grid(self, start, end):
        if self._cols == 0:
            return []
        body = call("GET", f"{self._api}/values/"
                           f"{self.sheet_id}!A{start}:{column_letter(self._cols - 1)}{end}",
                    token=self.auth.token(), params={"valueRenderOption": "FormattedValue"})
        return [[cell_str(c) for c in row] for row in body["data"]["valueRange"].get("values") or []]

    def _range(self, c1, c2, row, values):
        rng = f"{self.sheet_id}!{column_letter(c1)}{row}:{column_letter(c2)}{row + len(values) - 1}"
        return {"range": rng, "values": values}

    def _write(self, ranges):
        batch, cells = [], 0
        for r in ranges + [None]:
            n = sum(len(v) for v in r["values"]) if r else 0
            if batch and (r is None or cells + n > _CELLS_PER_WRITE):
                call("POST", f"{self._api}/values_batch_update", token=self.auth.token(),
                     json={"valueRanges": batch})
                batch, cells = [], 0
            if r:
                batch.append(r)
                cells += n

    def _grow(self, dim, n):
        """末尾补 n 行 / 列（n <= 0 时什么都不做）。"""
        while n > 0:
            k = min(n, _DIM_MAX)
            call("POST", f"{self._api}/dimension_range", token=self.auth.token(),
                 json={"dimension": {"sheetId": self.sheet_id, "majorDimension": dim, "length": k}})
            if dim == "ROWS":
                self._rows += k
            else:
                self._cols += k
            n -= k


def _runs(desc):
    """降序行号 → 连续段 [(hi, lo)]。"""
    out = []
    for r in desc:
        if out and out[-1][1] == r + 1:
            out[-1] = (out[-1][0], r)
        else:
            out.append((r, r))
    return out


def records(grid):
    """表头为空的列跳过，整行为空的行跳过；列名重复直接报错。返回 (列名, 记录, 行号)。"""
    if not grid:
        return [], [], []
    header = grid[0]
    cols = [i for i, h in enumerate(header) if h]
    dupes = sorted({header[i] for i in cols if header.count(header[i]) > 1})
    if dupes:
        raise LarkError(f"表头有重复的列名：{', '.join(dupes)}")
    rows, refs = [], []
    for n, r in enumerate(grid[1:], start=2):
        r = r + [""] * (len(header) - len(r))
        if any(r[i] for i in cols):
            rows.append({header[i]: r[i] for i in cols})
            refs.append(n)
    return [header[i] for i in cols], rows, refs


def cell_str(v):
    """飞书单元格 / 字段值 → 文本（两种表共用）。"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        if v and all(isinstance(x, dict) and "text" in x for x in v):   # 富文本分段
            return "".join(str(x["text"]) for x in v).strip()
        return ",".join(s for s in map(cell_str, v) if s)              # 多选、人员等
    if isinstance(v, dict):   # 链接、人员、附件、公式等
        for k in ("text", "name", "link", "full_address"):
            if v.get(k):
                return str(v[k]).strip()
        return cell_str(v.get("value"))
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def column_letter(index):
    """0 -> A, 25 -> Z, 26 -> AA"""
    out = ""
    while True:
        out = chr(ord("A") + index % 26) + out
        index = index // 26 - 1
        if index < 0:
            return out
