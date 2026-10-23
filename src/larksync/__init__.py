"""larksync：飞书电子表格 / 多维表格的拉取与按主键更新。"""
from .auth import configure
from .http import LarkError
from .table import Table

__all__ = ["Table", "LarkError", "configure"]
