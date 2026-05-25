"""中国大陆股市/ETF 行情查询模块。"""

from .classifier import SecurityType, classify
from .fetcher import (
    fetch_spot,
    fetch_history,
    fetch_intraday,
    SpotQuote,
)
from .display import render_report

__all__ = [
    "SecurityType",
    "classify",
    "fetch_spot",
    "fetch_history",
    "fetch_intraday",
    "SpotQuote",
    "render_report",
]
