"""diff → apply → undo 全流程，用内存里的假后端跑。"""
import pytest

from larksync import LarkError, Table, history


class FakeBackend:
    target = "fake:1"

    def __init__(self, header, rows):
        self.header = list(header)
        self.rows = {f"r{i}": dict(r) for i, r in enumerate(rows)}
        self.n = len(rows)

    def read(self):
        refs = list(self.rows)
        return list(self.header), [dict(self.rows[r]) for r in refs], refs

    def tabs(self):
        return [("t1", "表1")]

    def columns(self):
        return list(self.header)

    def lookup(self, key, values):
        _, rows, refs = self.read()
        return rows, refs, len(rows)

    def fetch(self, refs):
        return {r: dict(self.rows[r]) for r in refs if r in self.rows}

    def writable(self, name):
        return name != "只读"

    def canon(self, name, s):
        return s

    def update(self, cells):
        for ref, col, val in cells:
            self.rows[ref][col] = val

    def create(self, rows):
        refs = []
        for r in rows:
            self.n += 1
            refs.append(f"r{self.n}")
            self.rows[refs[-1]] = {h: r.get(h, "") for h in self.header}
        yield refs

    def delete(self, refs):
        for r in refs:
            del self.rows[r]

    def add_fields(self, names):
        self.header += names


def table(header, rows):
    t = Table.__new__(Table)
    t.url, t._auth, t._backend = "fake://t", None, FakeBackend(header, rows)
    return t


@pytest.fixture(autouse=True)
def tmp_history(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "DIR", tmp_path)


ONLINE = [{"ID": "1", "名字": "张三", "状态": ""},
          {"ID": "2", "名字": "李四", "状态": "待定"},
          {"ID": "3", "名字": "王五", "状态": ""}]


def test_fill_blank_warn_conflict_then_undo():
    t = table(["ID", "名字", "状态"], ONLINE)
    local = [{"ID": "1", "名字": "张三改", "状态": "通过"},   # 状态为空 → 补空；名字没选，不动
             {"ID": "2", "名字": "李四", "状态": "通过"},     # 在线已有「待定」→ 不一致，只警告
             {"ID": "3", "名字": "王五", "状态": ""},         # 本地为空 → 不动
             {"ID": "007", "名字": "新人", "状态": "通过"}]
    plan = t.diff(local, key="ID", columns=["状态"])
    assert [(c.key, c.old, c.new) for c in plan.changed] == [(("1",), "", "通过")]
    assert [(c.key, c.old, c.new) for c in plan.conflicts] == [(("2",), "待定", "通过")]
    assert plan.added == [{"ID": "007", "名字": "新人", "状态": "通过"}]
    assert plan.unmatched == 0

    plan.added = []                      # GUI 默认不勾选新增
    rid = plan.apply()
    assert [r["状态"] for r in t.pull()] == ["通过", "待定", ""]
    assert t.pull()[0]["名字"] == "张三"
    assert history.load(rid)["status"] == "done"

    t.undo(rid)
    assert t.pull() == ONLINE
    with pytest.raises(LarkError, match="已经撤销"):
        t.undo(rid)


def test_confirmed_conflicts_and_added_rows():
    t = table(["ID", "名字", "状态"], ONLINE)
    plan = t.diff([{"ID": "2", "状态": "通过"}, {"ID": "007", "名字": "新人", "状态": "通过"}],
                  key="ID", columns=["状态"])
    plan.changed += plan.conflicts       # 人工确认覆盖
    rid = plan.apply()
    rows = t.pull()
    assert rows[1]["状态"] == "通过" and rows[-1]["ID"] == "007"
    t.undo(rid)
    assert t.pull() == ONLINE


def test_apply_aborts_on_conflict():
    t = table(["ID", "状态"], [{"ID": "1", "状态": ""}])
    plan = t.diff([{"ID": "1", "状态": "通过"}], key="ID")
    t._backend.rows["r0"]["状态"] = "别人填的"
    with pytest.raises(LarkError, match="被改过"):
        plan.apply()
    assert t.pull() == [{"ID": "1", "状态": "别人填的"}]


def test_undo_aborts_if_edited_after():
    t = table(["ID", "状态"], [{"ID": "1", "状态": ""}])
    rid = t.diff([{"ID": "1", "状态": "通过"}], key="ID").apply()
    t._backend.rows["r0"]["状态"] = "又改了"
    with pytest.raises(LarkError, match="覆盖别人"):
        t.undo(rid)


def test_plan_can_be_trimmed_before_apply():
    t = table(["ID", "状态"], [{"ID": "1", "状态": ""}, {"ID": "2", "状态": ""}])
    plan = t.diff([{"ID": "1", "状态": "b"}, {"ID": "2", "状态": "b"}], key="ID")
    plan.changed = plan.changed[:1]
    plan.apply()
    assert [r["状态"] for r in t.pull()] == ["b", ""]


def test_init_and_undo():
    t = table(["ID"], [])
    rid = t.init([{"ID": "1", "名字": "张三"}, {"ID": "2", "名字": "李四"}])
    assert t._backend.header == ["ID", "名字"]
    assert len(t.pull()) == 2
    with pytest.raises(LarkError, match="已经有数据"):
        t.init([{"ID": "3"}])
    t.undo(rid)
    assert t.pull() == []


def test_diff_validation():
    t = table(["ID", "状态", "只读"], [{"ID": "1", "状态": "a", "只读": "x"}])
    with pytest.raises(LarkError, match="在线表里没有列「备注」"):
        t.diff([{"ID": "1", "备注": "x"}], key="ID")
    with pytest.raises(LarkError, match="只读"):
        t.diff([{"ID": "1", "只读": "y"}], key="ID")
    with pytest.raises(LarkError, match="联合主键"):
        t.diff([{"ID": "1", "状态": "b"}, {"ID": "1", "状态": "c"}], key="ID")
    with pytest.raises(LarkError, match="主键为空"):
        t.diff([{"ID": "", "状态": "b"}], key="ID")
