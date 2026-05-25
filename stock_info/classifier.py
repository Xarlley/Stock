"""根据 6 位代码判断标的类型与所属市场。"""

from dataclasses import dataclass
from enum import Enum


class SecurityType(str, Enum):
    STOCK = "stock"
    ETF = "etf"


class Market(str, Enum):
    SH = "sh"
    SZ = "sz"
    BJ = "bj"


@dataclass(frozen=True)
class Security:
    code: str
    type: SecurityType
    market: Market


def classify(raw: str) -> Security:
    code = _normalize(raw)

    head = code[0]
    head2 = code[:2]
    head3 = code[:3]

    # ETF 代码段：上交所 51/56/58，深交所 15/16/18
    if head2 in {"51", "56", "58"}:
        return Security(code, SecurityType.ETF, Market.SH)
    if head2 in {"15", "16", "18"}:
        return Security(code, SecurityType.ETF, Market.SZ)

    # 股票
    if head == "6":  # 沪市主板/科创板（688）
        return Security(code, SecurityType.STOCK, Market.SH)
    if head in {"0", "3"}:  # 深市主板/创业板
        return Security(code, SecurityType.STOCK, Market.SZ)
    if head in {"4", "8"} or head3 in {"920"}:  # 北交所
        return Security(code, SecurityType.STOCK, Market.BJ)

    raise ValueError(f"无法识别的代码: {raw}")


def _normalize(raw: str) -> str:
    s = raw.strip().lower()
    for prefix in ("sh", "sz", "bj"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    s = s.lstrip(".").lstrip(":")
    if not s.isdigit() or len(s) != 6:
        raise ValueError(f"代码必须为 6 位数字: {raw}")
    return s
