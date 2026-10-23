import pytest

from larksync import LarkError
from larksync.sheets import cell_str, column_letter, records
from larksync.table import parse_url


def test_parse_url():
    assert parse_url("https://x.feishu.cn/wiki/Abc?sheet=2aBAcO") == ("wiki", "Abc", "2aBAcO")
    assert parse_url("https://x.feishu.cn/sheets/shtX") == ("sheet", "shtX", None)
    assert parse_url("https://x.feishu.cn/base/basX?table=tblY&view=v") == ("bitable", "basX", "tblY")
    with pytest.raises(LarkError):
        parse_url("https://x.feishu.cn/docx/abc")


def test_cell_str():
    assert cell_str(None) == ""
    assert cell_str(12.0) == "12"
    assert cell_str(" 007 ") == "007"
    assert cell_str([{"text": "a"}, {"text": "b"}]) == "ab"
    assert cell_str({"text": "链接", "link": "http://x"}) == "链接"
    assert cell_str(True) == "true"
    assert cell_str(["a", "b"]) == "a,b"                                 # 多选
    assert cell_str([{"id": "ou_1", "name": "张三"}]) == "张三"           # 人员
    assert cell_str({"type": 1, "value": [{"text": "x", "type": "text"}]}) == "x"   # 公式


def test_column_letter():
    assert [column_letter(i) for i in (0, 25, 26, 701, 702)] == ["A", "Z", "AA", "ZZ", "AAA"]


def test_records_skips_blank_header_and_rows():
    header, rows, refs = records([["ID", "", "名字"], ["1", "x", "张三"], ["", "", ""], ["2"]])
    assert header == ["ID", "名字"]
    assert rows == [{"ID": "1", "名字": "张三"}, {"ID": "2", "名字": ""}]
    assert refs == [2, 4]


def test_records_duplicate_header():
    with pytest.raises(LarkError, match="重复"):
        records([["ID", "ID"]])


def test_runs_for_row_delete():
    from larksync.sheets import _runs
    assert _runs([9, 8, 7, 5, 2, 1]) == [(9, 7), (5, 5), (2, 1)]


def test_load_csv_bytes_utf8_and_gbk():
    from larksync.diff import load
    text = "ID,名字\n007,张三\n"
    for raw in (text.encode("utf-8-sig"), text.encode("gbk")):
        assert load(raw) == (["ID", "名字"], [{"ID": "007", "名字": "张三"}])


def test_load_xlsx(tmp_path):
    from datetime import datetime
    from openpyxl import Workbook
    from larksync.diff import load
    wb = Workbook()
    ws = wb.active
    ws.append(["ID", "数量", "日期", "空"])
    ws.append(["007", 3.0, datetime(2026, 1, 2), None])
    ws.append([None, None, None, None])
    wb.save(tmp_path / "t.xlsx")
    assert load(tmp_path / "t.xlsx") == (["ID", "数量", "日期", "空"],
                                         [{"ID": "007", "数量": "3", "日期": "2026-01-02", "空": ""}])
