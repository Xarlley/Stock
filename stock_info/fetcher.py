"""通过 akshare 获取行情：实时、历史日K、日内分时。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional

import pandas as pd
import requests

import akshare as ak

from .classifier import Security, SecurityType, Market


_HIST_RENAME = {
    "日期": "date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude",
    "涨跌幅": "pct_change",
    "涨跌额": "change",
    "换手率": "turnover",
}

_INTRADAY_RENAME = {
    "时间": "time",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "最新价": "close",
    "均价": "avg",
}


@dataclass
class SpotQuote:
    code: str
    name: str
    price: float
    prev_close: float
    open: float
    high: float
    low: float
    volume: float
    amount: float
    pct_change: float
    change: float
    turnover: Optional[float]
    timestamp: str
    extra: dict


def _retry(fn: Callable, attempts: int = 4, base_delay: float = 1.0):
    last_err = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # akshare 偶发网络抖动，统一重试
            last_err = e
            time.sleep(base_delay * (2 ** i))
    raise last_err


_STOCK_NAME_CACHE: dict[str, str] = {}


def _lookup_stock_name(code: str) -> str:
    if not _STOCK_NAME_CACHE:
        try:
            df = _retry(lambda: ak.stock_info_a_code_name(), attempts=3)
            for _, row in df.iterrows():
                _STOCK_NAME_CACHE[str(row["code"])] = str(row["name"]).strip()
        except Exception:
            pass
    return _STOCK_NAME_CACHE.get(code, "")


def fetch_spot(sec: Security) -> SpotQuote:
    """获取实时盘口快照。"""
    if sec.type is SecurityType.ETF:
        return _fetch_etf_spot(sec)
    return _fetch_stock_spot(sec)


def _fetch_etf_spot(sec: Security) -> SpotQuote:
    df = _retry(lambda: ak.fund_etf_spot_em())
    row = df[df["代码"] == sec.code]
    if row.empty:
        raise LookupError(f"未在实时行情中找到 ETF {sec.code}")
    r = row.iloc[0]

    def g(*keys, default=None):
        for k in keys:
            if k in r and pd.notna(r[k]):
                return r[k]
        return default

    return SpotQuote(
        code=sec.code,
        name=str(g("名称", default="")),
        price=float(g("最新价", default="nan")),
        prev_close=float(g("昨收", default="nan")),
        open=float(g("开盘", "开盘价", default="nan")),
        high=float(g("最高", "最高价", default="nan")),
        low=float(g("最低", "最低价", default="nan")),
        volume=float(g("成交量", default=0) or 0),
        amount=float(g("成交额", default=0) or 0),
        pct_change=float(g("涨跌幅", default=0) or 0),
        change=float(g("涨跌额", default=0) or 0),
        turnover=_optional_float(g("换手率")),
        timestamp=str(g("更新时间", "数据日期", default="")),
        extra={
            "总市值": g("总市值"),
            "流通市值": g("流通市值"),
            "量比": g("量比"),
            "委比": g("委比"),
            "IOPV实时估值": g("IOPV实时估值"),
            "基金折价率": g("基金折价率"),
        },
    )


def _fetch_stock_spot(sec: Security) -> SpotQuote:
    """优先 Sina 行情接口（轻量、稳定），失败时回退到 EastMoney。"""
    try:
        return _fetch_sina_spot(sec)
    except Exception:
        pass
    return _fetch_em_stock_spot(sec)


def _fetch_em_stock_spot(sec: Security) -> SpotQuote:
    df = _retry(lambda: ak.stock_bid_ask_em(symbol=sec.code))
    if df is None or df.empty:
        raise LookupError(f"未获取到股票 {sec.code} 的实时行情")
    kv = dict(zip(df["item"], df["value"]))

    def f(key, default=float("nan")):
        v = kv.get(key, default)
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    return SpotQuote(
        code=sec.code,
        name=_lookup_stock_name(sec.code),
        price=f("最新"),
        prev_close=f("昨收"),
        open=f("今开"),
        high=f("最高"),
        low=f("最低"),
        volume=f("总手", 0.0),
        amount=f("金额", 0.0),
        pct_change=f("涨幅", 0.0),
        change=f("涨跌", 0.0),
        turnover=_optional_float(kv.get("换手")),
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        extra={
            "均价": kv.get("均价"),
            "量比": kv.get("量比"),
            "涨停": kv.get("涨停"),
            "跌停": kv.get("跌停"),
            "外盘": kv.get("外盘"),
            "内盘": kv.get("内盘"),
            "买一": kv.get("buy_1"),
            "卖一": kv.get("sell_1"),
        },
    )


def _sina_symbol(sec: Security) -> str:
    prefix = "sh" if sec.market is Market.SH else "sz" if sec.market is Market.SZ else "bj"
    return f"{prefix}{sec.code}"


def _fetch_sina_spot(sec: Security) -> SpotQuote:
    """直连 Sina hq.sinajs.cn — 单条 GET，含名称、五档、当日价。"""
    sym = _sina_symbol(sec)
    url = f"http://hq.sinajs.cn/list={sym}"
    headers = {
        "Referer": "https://finance.sina.com.cn",
        "User-Agent": "Mozilla/5.0",
    }

    def _do():
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = "gbk"
        return r.text

    text = _retry(_do)
    # 解析 var hq_str_xxx="...";
    try:
        payload = text.split('="', 1)[1].rsplit('";', 1)[0]
    except IndexError as e:
        raise LookupError(f"Sina 行情解析失败: {text!r}") from e
    parts = payload.split(",")
    if len(parts) < 32 or not parts[0]:
        raise LookupError(f"Sina 行情数据为空，可能停牌或代码错误: {sym}")

    name = parts[0]
    today_open = float(parts[1])
    prev_close = float(parts[2])
    current = float(parts[3])
    high = float(parts[4])
    low = float(parts[5])
    volume = float(parts[8])  # 股
    amount = float(parts[9])  # 元
    bid1 = parts[11] if len(parts) > 11 else None
    ask1 = parts[21] if len(parts) > 21 else None
    date_s = parts[30] if len(parts) > 30 else ""
    time_s = parts[31] if len(parts) > 31 else ""

    chg = current - prev_close
    pct = (chg / prev_close * 100) if prev_close else 0.0

    return SpotQuote(
        code=sec.code,
        name=name,
        price=current,
        prev_close=prev_close,
        open=today_open,
        high=high,
        low=low,
        volume=volume,
        amount=amount,
        pct_change=pct,
        change=chg,
        turnover=None,  # Sina 接口未提供
        timestamp=f"{date_s} {time_s}".strip(),
        extra={
            "买一": bid1,
            "卖一": ask1,
        },
    )


def fetch_history(
    sec: Security,
    start: datetime,
    end: datetime,
    adjust: str = "qfq",
) -> pd.DataFrame:
    """获取日K历史。adjust: '' 不复权 / 'qfq' 前复权 / 'hfq' 后复权。"""
    if sec.type is SecurityType.ETF:
        return _fetch_etf_history(sec, start, end, adjust)
    # 股票优先 EastMoney（支持日期切片），失败回退到 Sina 全量
    try:
        return _fetch_stock_history_em(sec, start, end, adjust)
    except Exception:
        return _fetch_stock_history_sina(sec, start, end, adjust)


def _fetch_etf_history(sec, start, end, adjust):
    df = _retry(lambda: ak.fund_etf_hist_em(
        symbol=sec.code,
        period="daily",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust=adjust,
    ))
    return _normalize_hist(df)


def _fetch_stock_history_em(sec, start, end, adjust):
    df = _retry(lambda: ak.stock_zh_a_hist(
        symbol=sec.code,
        period="daily",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust=adjust,
    ))
    return _normalize_hist(df)


def _fetch_stock_history_sina(sec, start, end, adjust):
    sym = _sina_symbol(sec)
    df = _retry(lambda: ak.stock_zh_a_daily(symbol=sym, adjust=adjust))
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]
    df = df.sort_values("date").reset_index(drop=True)
    return df  # 已经是英文列名


def _normalize_hist(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(columns=_HIST_RENAME).copy()
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def fetch_intraday(sec: Security, day: Optional[datetime] = None) -> pd.DataFrame:
    """获取指定交易日 1 分钟分时；默认当日。"""
    day = day or datetime.now()
    start = day.replace(hour=9, minute=30, second=0, microsecond=0)
    end = day.replace(hour=15, minute=0, second=0, microsecond=0)
    start_s = start.strftime("%Y-%m-%d %H:%M:%S")
    end_s = end.strftime("%Y-%m-%d %H:%M:%S")

    if sec.type is SecurityType.ETF:
        df = _retry(lambda: ak.fund_etf_hist_min_em(
            symbol=sec.code,
            period="1",
            adjust="",
            start_date=start_s,
            end_date=end_s,
        ))
    else:
        df = _retry(lambda: ak.stock_zh_a_hist_min_em(
            symbol=sec.code,
            period="1",
            adjust="",
            start_date=start_s,
            end_date=end_s,
        ))

    if df is None or df.empty:
        return pd.DataFrame()

    df = df.rename(columns=_INTRADAY_RENAME).copy()
    df["time"] = pd.to_datetime(df["time"])
    # 仅保留当日交易时段
    df = df[(df["time"] >= start) & (df["time"] <= end)].reset_index(drop=True)
    return df


def _optional_float(v) -> Optional[float]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
