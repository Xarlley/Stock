"""ETF 全清单完整数据快照 —— 单文件一站式实现。

覆盖 docs/etf_universe.md 中全部 109 只 ETF, 输出 docs/indicators_guide.md 所列
P0/P1 指标的完整集合。所有「可拉」走主接口 + 兜底重试, 所有「需算」就地从
OHLCV 推导。同时把每日 IOPV / 溢价写入本地累积 CSV, 为 Phase 2 的
「溢价历史分位 / z-score」准备数据基础。

用法:
    python tools/etf_full_snapshot.py <output_path.md> [--no-cache] [--verbose]

冗余/兜底路径:
    - ETF spot:    fund_etf_spot_em (主) → Sina hq.sinajs.cn 批量 (备, 不含 IOPV/资金流/份额)
    - ETF 历史:    fund_etf_hist_sina (主) → fund_etf_hist_em (备)
    - 市场宏观:    每项独立 try-catch, 单点失败不影响其余
    - IOPV 历史:   本地 analysis_history/iopv_history.csv 累积
"""
from __future__ import annotations

import argparse
import sys
import time
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

warnings.filterwarnings("ignore")

import akshare as ak
import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stock_info.classifier import classify, Market  # noqa: E402


# ========== 配置 ==========
ROOT = Path(__file__).resolve().parent.parent
IOPV_CACHE = ROOT / "analysis_history" / "iopv_history.csv"
BENCH_CODE = "510300"
TRADING_DAYS = 252
RF_ANNUAL = 0.02
RETRY_MAX = 3
RETRY_BASE = 1.5

CATEGORIES: dict[str, list[str]] = {
    "宽基-沪深300": ["510300", "510310", "159919"],
    "宽基-上证50": ["510050", "510850"],
    "宽基-中证500": ["510500", "159922"],
    "宽基-中证1000": ["512100", "159845"],
    "宽基-科创50": ["588000", "588080"],
    "宽基-创业板": ["159915", "159949"],
    "宽基-科创100": ["159781", "588800"],
    "宽基-红利": ["510880", "515180", "159905"],
    "科技-半导体A股": ["512760", "159995", "159813", "159665", "512480"],
    "科技-中韩半导体": ["513310"],
    "科技-科创半导体": ["588170", "588710", "561980"],
    "科技-人工智能": ["515070", "159819", "512930", "515980", "159381", "159363"],
    "科技-通信5G": ["515880", "515050"],
    "科技-机器人": ["562500", "159770", "562990"],
    "科技-软件计算机": ["159852", "562930", "515580"],
    "科技-游戏传媒": ["159869", "516010", "159805"],
    "医药-医疗": ["512170", "512010"],
    "医药-创新药": ["159992", "159929", "512290"],
    "消费-大消费": ["159928", "510150"],
    "消费-食品饮料": ["515170", "159736", "515650"],
    "消费-家电": ["159996"],
    "新能源-车": ["515030", "159755"],
    "新能源-光伏": ["515790", "159875"],
    "新能源-电池": ["562880"],
    "金融-银行": ["512800", "512820", "512730"],
    "金融-证券": ["512880", "512000", "159842"],
    "金融-军工": ["512660", "512810", "159602"],
    "资源-有色": ["512400"],
    "资源-煤炭": ["515220"],
    "资源-钢铁": ["515210"],
    "公用-电力": ["159611", "561260"],
    "公用-房地产": ["512200", "159768"],
    "公用-农业": ["159825"],
    "公用-旅游": ["159766"],
    "商品-黄金": ["518880", "159934", "518800"],
    "商品-原油": ["162411", "159980"],
    "商品-货币": ["511990", "511880"],
    "美国-纳指100": ["513100", "159941", "513870"],
    "美国-标普500": ["513500", "159612", "513650"],
    "美国-纳指科技": ["159509", "159632"],
    "港股-恒生": ["159920"],
    "港股-H股": ["510900"],
    "港股-恒生科技": ["513130", "513180", "513380"],
    "港股-中概互联": ["513050", "159605"],
    "港股-医药": ["159892"],
    "港股-科技": ["513090"],
    "日本-日经225": ["159866", "513520"],
    "欧洲-德国": ["513030"],
    "欧洲-法国": ["513080"],
    "海外-印度": ["164824"],
    "海外-沙特": ["520830"],
    "海外-东南亚": ["513730"],
}

# 跨境标记 —— 用于触发溢价/折价的额外提示与 Phase 2 重点关注
CROSS_BORDER_CODES = {
    "513310", "513100", "159941", "513870", "513500", "159612", "513650",
    "159509", "159632", "159920", "510900", "513130", "513180", "513380",
    "513050", "159605", "159892", "513090", "159866", "513520", "513030",
    "513080", "164824", "520830", "513730",
}


# ========== 通用工具 ==========
@dataclass
class RunStats:
    spot_ok: int = 0
    spot_fallback: int = 0
    spot_fail: int = 0
    hist_sina_ok: int = 0
    hist_em_fallback: int = 0
    hist_fail: int = 0
    market_attempts: int = 0
    market_ok: int = 0
    indicator_counts: dict[str, int] = field(default_factory=dict)

    def tick(self, indicator: str):
        self.indicator_counts[indicator] = self.indicator_counts.get(indicator, 0) + 1


VERBOSE = False


def log(msg: str, verbose_only: bool = False) -> None:
    if verbose_only and not VERBOSE:
        return
    print(msg, flush=True)


def retry(fn: Callable, name: str = "", attempts: int = RETRY_MAX,
          base_delay: float = RETRY_BASE):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            log(f"      retry {name} ({i+1}/{attempts}) — {type(e).__name__}: {str(e)[:60]}",
                verbose_only=True)
            if i < attempts - 1:
                time.sleep(base_delay * (2 ** i))
    raise last


def safe_call(fn: Callable, label: str, stats: RunStats):
    stats.market_attempts += 1
    try:
        result = retry(fn, name=label)
        stats.market_ok += 1
        return result, None
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:80]}"


# ========== ETF spot ==========
def fetch_spot_primary() -> pd.DataFrame:
    df = ak.fund_etf_spot_em()
    df = df.copy()
    df["代码"] = df["代码"].astype(str)
    return df


def fetch_spot_fallback_sina(codes: list[str]) -> pd.DataFrame:
    """Sina hq.sinajs.cn 批量 — 兜底, 不含 IOPV/资金流/份额。"""
    rows = []
    chunk = 20
    headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
    for i in range(0, len(codes), chunk):
        batch = codes[i : i + chunk]
        syms = []
        for c in batch:
            try:
                sec = classify(c)
                p = "sh" if sec.market is Market.SH else "sz" if sec.market is Market.SZ else "bj"
                syms.append(f"{p}{c}")
            except Exception:
                continue
        if not syms:
            continue
        url = f"http://hq.sinajs.cn/list={','.join(syms)}"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            r.encoding = "gbk"
            for line, code in zip(r.text.strip().split("\n"), batch):
                try:
                    payload = line.split('="', 1)[1].rsplit('";', 1)[0]
                    parts = payload.split(",")
                    if len(parts) < 32 or not parts[0]:
                        continue
                    rows.append({
                        "代码": code,
                        "名称": parts[0],
                        "最新价": float(parts[3]),
                        "昨收": float(parts[2]),
                        "开盘价": float(parts[1]),
                        "最高价": float(parts[4]),
                        "最低价": float(parts[5]),
                        "成交量": float(parts[8]),
                        "成交额": float(parts[9]),
                        "涨跌幅": ((float(parts[3]) - float(parts[2])) / float(parts[2]) * 100)
                                   if float(parts[2]) else 0.0,
                    })
                except Exception:
                    continue
        except Exception:
            continue
    return pd.DataFrame(rows)


def fetch_spot(all_codes: list[str], stats: RunStats) -> pd.DataFrame:
    try:
        df = retry(fetch_spot_primary, name="fund_etf_spot_em")
        stats.spot_ok = sum(1 for c in all_codes if c in df["代码"].values)
        log(f"  [spot] fund_etf_spot_em ✅ {len(df)} 行, 命中 {stats.spot_ok}/{len(all_codes)}")
        return df
    except Exception as e:
        log(f"  [spot] fund_etf_spot_em ❌ {type(e).__name__}: {str(e)[:80]}")

    log(f"  [spot] 启用 Sina hq.sinajs.cn 兜底（不含 IOPV/资金流/份额） ...")
    df = fetch_spot_fallback_sina(all_codes)
    stats.spot_fallback = len(df)
    stats.spot_fail = len(all_codes) - len(df)
    return df


# ========== ETF 历史 ==========
def _sina_prefix(code: str) -> str:
    try:
        sec = classify(code)
        return "sh" if sec.market is Market.SH else "sz" if sec.market is Market.SZ else "bj"
    except Exception:
        return "sh"


def fetch_history_sina(code: str) -> pd.DataFrame | None:
    df = ak.fund_etf_hist_sina(symbol=f"{_sina_prefix(code)}{code}")
    if df is None or df.empty:
        return None
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").set_index("date")


def fetch_history_em(code: str) -> pd.DataFrame | None:
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=400)).strftime("%Y%m%d")
    df = ak.fund_etf_hist_em(symbol=code, period="daily",
                              start_date=start, end_date=end, adjust="")
    if df is None or df.empty:
        return None
    df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close",
                              "最高": "high", "最低": "low",
                              "成交量": "volume", "成交额": "amount"})
    df["date"] = pd.to_datetime(df["date"])
    keep = ["date", "open", "high", "low", "close", "volume"]
    if "amount" in df.columns:
        keep.append("amount")
    return df[keep].sort_values("date").set_index("date")


def fetch_history(code: str, stats: RunStats) -> tuple[pd.DataFrame | None, str]:
    try:
        hist = retry(lambda: fetch_history_sina(code), name=f"sina_hist_{code}", attempts=2)
        if hist is not None and not hist.empty:
            stats.hist_sina_ok += 1
            return hist, "sina"
    except Exception as e:
        log(f"      sina hist {code} ❌ {str(e)[:60]}", verbose_only=True)
    try:
        hist = retry(lambda: fetch_history_em(code), name=f"em_hist_{code}", attempts=2)
        if hist is not None and not hist.empty:
            stats.hist_em_fallback += 1
            return hist, "em-fallback"
    except Exception as e:
        log(f"      em hist {code} ❌ {str(e)[:60]}", verbose_only=True)
    stats.hist_fail += 1
    return None, "none"


# ========== 市场宏观 ==========
def fetch_market_globals(stats: RunStats) -> dict:
    out: dict = {}
    ymd = datetime.now().strftime("%Y%m%d")

    res, err = safe_call(lambda: ak.stock_market_activity_legu(), "market_activity", stats)
    if res is not None:
        out["market_activity"] = dict(zip(res["item"], res["value"]))
    elif err:
        out["market_activity_err"] = err

    res, err = safe_call(lambda: ak.stock_zt_pool_em(date=ymd), "zt_pool", stats)
    if res is not None:
        out["zt_count"] = len(res)
    elif err:
        out["zt_err"] = err

    res, err = safe_call(lambda: ak.stock_hsgt_fund_flow_summary_em(), "hsgt_summary", stats)
    if res is not None:
        out["hsgt"] = res.to_dict(orient="records")
    elif err:
        out["hsgt_err"] = err

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=14)).strftime("%Y%m%d")
    res, err = safe_call(lambda: ak.stock_margin_sse(start_date=start, end_date=end),
                          "margin_sse", stats)
    if res is not None and not res.empty:
        out["margin_sse"] = res.tail(3).to_dict(orient="records")
    elif err:
        out["margin_err"] = err

    res, err = safe_call(lambda: ak.stock_index_pe_lg(symbol="沪深300"), "hs300_pe", stats)
    if res is not None and not res.empty:
        last = res.iloc[-1]
        try:
            out["hs300_pe"] = {
                "日期": str(last["日期"]),
                "滚动市盈率": float(last["滚动市盈率"]),
                "等权滚动市盈率": float(last["等权滚动市盈率"]),
            }
            pe5y = res.tail(TRADING_DAYS * 5)["滚动市盈率"].astype(float)
            cur = float(last["滚动市盈率"])
            out["hs300_pe_pct_rank_5y"] = float((pe5y <= cur).mean() * 100)
        except Exception:
            pass
    elif err:
        out["pe_err"] = err

    res, err = safe_call(lambda: ak.stock_index_pb_lg(symbol="沪深300"), "hs300_pb", stats)
    if res is not None and not res.empty:
        last = res.iloc[-1]
        try:
            out["hs300_pb"] = {"日期": str(last["日期"]), "市净率": float(last["市净率"])}
            pb5y = res.tail(TRADING_DAYS * 5)["市净率"].astype(float)
            cur = float(last["市净率"])
            out["hs300_pb_pct_rank_5y"] = float((pb5y <= cur).mean() * 100)
        except Exception:
            pass
    elif err:
        out["pb_err"] = err

    return out


# ========== 指标计算 ==========
def pct_window(df: pd.DataFrame, days: int) -> float | None:
    if df is None or df.empty:
        return None
    end = df.index[-1]
    sub = df[df.index > end - timedelta(days=days)]
    if sub.empty:
        return None
    start = float(sub["close"].iloc[0])
    if start == 0:
        return None
    return (float(df["close"].iloc[-1]) / start - 1) * 100


def price_extremes(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    close = df["close"]
    last = float(close.iloc[-1])
    tail252 = close.tail(TRADING_DAYS)
    high52, low52 = float(tail252.max()), float(tail252.min())
    out = {
        "52w_high": high52,
        "52w_low": low52,
        "dist_52w_high_pct": (last - high52) / high52 * 100 if high52 else None,
        "dist_52w_low_pct": (last - low52) / low52 * 100 if low52 else None,
        "is_new_52w_high": bool(last >= high52),
        "is_new_52w_low": bool(last <= low52),
    }
    tail60, tail120 = close.tail(60), close.tail(120)
    if not tail60.empty:
        out["high_60d"], out["low_60d"] = float(tail60.max()), float(tail60.min())
    if not tail120.empty:
        out["high_120d"], out["low_120d"] = float(tail120.max()), float(tail120.min())
    if len(df) >= 2:
        prev = float(close.iloc[-2])
        h, l = float(df["high"].iloc[-1]), float(df["low"].iloc[-1])
        out["today_amplitude_pct"] = (h - l) / prev * 100 if prev else None
    return out


def moving_averages(df: pd.DataFrame, windows=(5, 10, 20, 60, 120, 250)) -> dict:
    if df.empty:
        return {}
    close = df["close"]
    last = float(close.iloc[-1])
    out: dict = {}
    mas: dict[int, float] = {}
    for w in windows:
        if len(close) < w:
            out[f"MA{w}"] = None
            continue
        ma_series = close.rolling(w).mean()
        ma = float(ma_series.iloc[-1])
        mas[w] = ma
        out[f"MA{w}"] = ma
        out[f"price_vs_MA{w}_pct"] = (last - ma) / ma * 100 if ma else None
        if len(ma_series) > w:
            past = float(ma_series.iloc[-w])
            out[f"MA{w}_slope_pct"] = (ma - past) / past * 100 if past else None
    if all(k in mas for k in (5, 10, 20, 60)):
        out["bull_arrangement"] = mas[5] > mas[10] > mas[20] > mas[60]
        out["bear_arrangement"] = mas[5] < mas[10] < mas[20] < mas[60]
    if len(close) >= 21:
        ma5, ma20 = close.rolling(5).mean(), close.rolling(20).mean()
        if len(ma5) >= 2:
            today = ma5.iloc[-1] - ma20.iloc[-1]
            prev = ma5.iloc[-2] - ma20.iloc[-2]
            if prev < 0 and today > 0:
                out["ma_cross_5_20"] = "golden"
            elif prev > 0 and today < 0:
                out["ma_cross_5_20"] = "death"
            else:
                out["ma_cross_5_20"] = "none"
    if len(close) >= 80:
        ma20 = close.rolling(20).mean()
        out["pct_days_above_MA20_60d"] = float(
            (close.tail(60) > ma20.tail(60)).mean() * 100
        )
    return out


def macd_indicator(df: pd.DataFrame, fast=12, slow=26, signal=9) -> dict:
    if df.empty or len(df) < slow + signal:
        return {}
    close = df["close"]
    dif = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = 2 * (dif - dea)
    cross = "none"
    if len(dif) >= 2:
        today, prev = dif.iloc[-1] - dea.iloc[-1], dif.iloc[-2] - dea.iloc[-2]
        if prev < 0 and today > 0:
            cross = "golden"
        elif prev > 0 and today < 0:
            cross = "death"
    return {
        "macd_dif": float(dif.iloc[-1]),
        "macd_dea": float(dea.iloc[-1]),
        "macd_hist": float(hist.iloc[-1]),
        "macd_cross": cross,
    }


def rsi_indicator(df: pd.DataFrame, period=14) -> float | None:
    if df.empty or len(df) < period + 1:
        return None
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    val = 100 - 100 / (1 + rs)
    return float(val.iloc[-1]) if pd.notna(val.iloc[-1]) else None


def kdj_indicator(df: pd.DataFrame, n=9, k_p=3, d_p=3) -> dict:
    if df.empty or len(df) < n:
        return {}
    low_n = df["low"].rolling(n).min()
    high_n = df["high"].rolling(n).max()
    rsv = (df["close"] - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    k = rsv.ewm(alpha=1 / k_p, adjust=False).mean()
    d = k.ewm(alpha=1 / d_p, adjust=False).mean()
    j = 3 * k - 2 * d
    return {
        "kdj_k": float(k.iloc[-1]) if pd.notna(k.iloc[-1]) else None,
        "kdj_d": float(d.iloc[-1]) if pd.notna(d.iloc[-1]) else None,
        "kdj_j": float(j.iloc[-1]) if pd.notna(j.iloc[-1]) else None,
    }


def cci_indicator(df: pd.DataFrame, period=14) -> float | None:
    if df.empty or len(df) < period:
        return None
    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma = tp.rolling(period).mean()
    md = tp.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    val = (tp - sma) / (0.015 * md.replace(0, np.nan))
    return float(val.iloc[-1]) if pd.notna(val.iloc[-1]) else None


def roc_indicator(df: pd.DataFrame, period=10) -> float | None:
    if df.empty or len(df) <= period:
        return None
    return float((df["close"].iloc[-1] / df["close"].iloc[-1 - period] - 1) * 100)


def williams_r_indicator(df: pd.DataFrame, period=14) -> float | None:
    if df.empty or len(df) < period:
        return None
    hh = df["high"].rolling(period).max().iloc[-1]
    ll = df["low"].rolling(period).min().iloc[-1]
    if hh == ll:
        return None
    return float((hh - df["close"].iloc[-1]) / (hh - ll) * -100)


def dmi_adx(df: pd.DataFrame, period=14) -> dict:
    if df.empty or len(df) < period * 2:
        return {}
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff()
    dn = -l.diff()
    plus_dm = ((up > dn) & (up > 0)) * up
    minus_dm = ((dn > up) & (dn > 0)) * dn
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr_n = tr.rolling(period).mean()
    plus_di = 100 * plus_dm.rolling(period).mean() / atr_n.replace(0, np.nan)
    minus_di = 100 * minus_dm.rolling(period).mean() / atr_n.replace(0, np.nan)
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    adx = dx.rolling(period).mean()
    return {
        "plus_di_14": float(plus_di.iloc[-1]) if pd.notna(plus_di.iloc[-1]) else None,
        "minus_di_14": float(minus_di.iloc[-1]) if pd.notna(minus_di.iloc[-1]) else None,
        "adx_14": float(adx.iloc[-1]) if pd.notna(adx.iloc[-1]) else None,
    }


def volatility_indicator(df: pd.DataFrame) -> dict:
    if df.empty or len(df) < 21:
        return {}
    ret = df["close"].pct_change().dropna()
    out = {}
    for w, name in [(20, "vol_20d_ann"), (60, "vol_60d_ann")]:
        if len(ret) >= w:
            out[name] = float(ret.tail(w).std() * np.sqrt(TRADING_DAYS) * 100)
    if len(ret) >= 60:
        down = ret[ret < 0].tail(60)
        if not down.empty:
            out["downside_vol_60d_ann"] = float(down.std() * np.sqrt(TRADING_DAYS) * 100)
    if len(ret) >= TRADING_DAYS + 20:
        rolling_vol = ret.rolling(20).std() * np.sqrt(TRADING_DAYS)
        recent = rolling_vol.tail(TRADING_DAYS).dropna()
        cur = rolling_vol.iloc[-1]
        if pd.notna(cur) and len(recent) > 0:
            out["vol_pct_rank_1y"] = float((recent <= cur).mean() * 100)
    # Parkinson 波动率 (用 HL 估计)
    if len(df) >= 20:
        hl = (np.log(df["high"] / df["low"]) ** 2).tail(20)
        park = float(np.sqrt(hl.mean() / (4 * np.log(2))) * np.sqrt(TRADING_DAYS) * 100)
        out["vol_parkinson_20d"] = park
    return out


def atr_indicator(df: pd.DataFrame, period=14) -> float | None:
    if df.empty or len(df) < period + 1:
        return None
    h, l, c = df["high"], df["low"], df["close"]
    prev = c.shift(1)
    tr = pd.concat([(h - l), (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


def bollinger_indicator(df: pd.DataFrame, period=20, k=2) -> dict:
    if df.empty or len(df) < period:
        return {}
    mid = df["close"].rolling(period).mean()
    sd = df["close"].rolling(period).std()
    upper, lower = mid + k * sd, mid - k * sd
    close = df["close"].iloc[-1]
    bw = (upper.iloc[-1] - lower.iloc[-1]) / mid.iloc[-1] * 100 if mid.iloc[-1] else None
    pctb = ((close - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1])
            if upper.iloc[-1] != lower.iloc[-1] else None)
    return {
        "boll_upper": float(upper.iloc[-1]),
        "boll_mid": float(mid.iloc[-1]),
        "boll_lower": float(lower.iloc[-1]),
        "boll_pctb": float(pctb) if pctb is not None else None,
        "boll_bandwidth_pct": float(bw) if bw is not None else None,
    }


def keltner_channel(df: pd.DataFrame, period=20, k=2) -> dict:
    if df.empty or len(df) < period + 14:
        return {}
    ema = df["close"].ewm(span=period, adjust=False).mean()
    a = atr_indicator(df, 14)
    if a is None:
        return {}
    return {
        "keltner_upper": float(ema.iloc[-1] + k * a),
        "keltner_lower": float(ema.iloc[-1] - k * a),
    }


def drawdown_metrics(df: pd.DataFrame, lookback=TRADING_DAYS) -> dict:
    if df.empty:
        return {}
    close = df["close"].tail(lookback)
    cummax = close.cummax()
    dd = close / cummax - 1
    out = {"mdd_1y_pct": float(dd.min() * 100), "current_dd_pct": float(dd.iloc[-1] * 100)}
    if dd.min() < 0:
        bottom = dd.idxmin()
        peak_b = close.loc[:bottom].idxmax()
        target = close.loc[peak_b]
        post = close.loc[bottom:]
        recover = post[post >= target]
        if not recover.empty:
            out["dd_recovery_days"] = int((recover.index[0] - bottom).days)
        else:
            out["dd_recovery_days"] = None
    return out


def risk_adjusted(df: pd.DataFrame, rf=RF_ANNUAL) -> dict:
    if df.empty or len(df) < TRADING_DAYS:
        return {}
    ret = df["close"].pct_change().dropna().tail(TRADING_DAYS)
    if len(ret) < 60:
        return {}
    ann_ret = (1 + ret.mean()) ** TRADING_DAYS - 1
    ann_vol = ret.std() * np.sqrt(TRADING_DAYS)
    downside = ret[ret < 0]
    ann_down = downside.std() * np.sqrt(TRADING_DAYS) if len(downside) > 5 else None
    sharpe = (ann_ret - rf) / ann_vol if ann_vol > 0 else None
    sortino = (ann_ret - rf) / ann_down if ann_down and ann_down > 0 else None
    dd = df["close"].tail(TRADING_DAYS) / df["close"].tail(TRADING_DAYS).cummax() - 1
    mdd_abs = abs(dd.min())
    calmar = ann_ret / mdd_abs if mdd_abs > 0 else None
    return {
        "ann_return_1y_pct": float(ann_ret * 100),
        "sharpe_1y": float(sharpe) if sharpe is not None else None,
        "sortino_1y": float(sortino) if sortino is not None else None,
        "calmar_1y": float(calmar) if calmar is not None else None,
    }


def volume_metrics(df: pd.DataFrame) -> dict:
    if df.empty or "volume" not in df.columns:
        return {}
    vol = df["volume"]
    out = {}
    for w in (5, 20, 60):
        if len(vol) >= w:
            out[f"VMA{w}"] = float(vol.rolling(w).mean().iloc[-1])
    if len(df) >= 2:
        sign = np.sign(df["close"].diff().fillna(0))
        obv = (sign * vol).cumsum()
        out["obv"] = float(obv.iloc[-1])
        if len(obv) >= 20:
            past = obv.iloc[-20]
            if past != 0:
                out["obv_slope_20d_pct"] = float((obv.iloc[-1] - past) / abs(past) * 100)
    if len(df) >= 15:
        tp = (df["high"] + df["low"] + df["close"]) / 3
        mf = tp * vol
        pos = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
        neg = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
        mfi = 100 - 100 / (1 + pos / neg.replace(0, np.nan))
        if pd.notna(mfi.iloc[-1]):
            out["mfi_14"] = float(mfi.iloc[-1])
    # Chaikin Money Flow
    if len(df) >= 20 and all(c in df.columns for c in ("high", "low", "close")):
        rng = (df["high"] - df["low"]).replace(0, np.nan)
        mfm = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng
        mfv = mfm * vol
        cmf = mfv.rolling(20).sum() / vol.rolling(20).sum().replace(0, np.nan)
        if pd.notna(cmf.iloc[-1]):
            out["cmf_20"] = float(cmf.iloc[-1])
    return out


def relative_strength(df: pd.DataFrame, bench: pd.DataFrame,
                       windows=(21, 63, 126)) -> dict:
    if df.empty or bench is None or bench.empty:
        return {}
    out = {}
    close, bc = df["close"], bench["close"]
    for w, label in zip(windows, ("1m", "3m", "6m")):
        if len(close) > w and len(bc) > w:
            er = close.iloc[-1] / close.iloc[-1 - w] - 1
            br = bc.iloc[-1] / bc.iloc[-1 - w] - 1
            out[f"rs_vs_bench_{label}_pct"] = float((er - br) * 100)
    re_ = close.pct_change().dropna().tail(60)
    rb_ = bc.pct_change().dropna().tail(60)
    n = min(len(re_), len(rb_))
    if n >= 30:
        re2 = re_.tail(n).reset_index(drop=True)
        rb2 = rb_.tail(n).reset_index(drop=True)
        v = rb2.var()
        if v > 0:
            out["beta_60d"] = float(re2.cov(rb2) / v)
        out["corr_60d"] = float(re2.corr(rb2))
        out["tracking_error_60d_pct"] = float((re2 - rb2).std() * np.sqrt(TRADING_DAYS) * 100)
    return out


# ========== IOPV / 溢价历史 ==========
def load_iopv_history() -> pd.DataFrame:
    if not IOPV_CACHE.exists():
        return pd.DataFrame(columns=["date", "code", "price", "iopv", "premium_pct"])
    df = pd.read_csv(IOPV_CACHE)
    df["date"] = pd.to_datetime(df["date"])
    return df


def append_iopv_today(records: list[dict]) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    new_rows = []
    for r in records:
        price, iopv = r.get("最新价"), r.get("IOPV实时估值")
        if price is None or iopv is None:
            continue
        if pd.isna(price) or pd.isna(iopv) or float(iopv) == 0:
            continue
        prem = (float(price) - float(iopv)) / float(iopv) * 100
        new_rows.append({"date": today, "code": r["代码"], "price": float(price),
                         "iopv": float(iopv), "premium_pct": prem})
    if not new_rows:
        return
    df_new = pd.DataFrame(new_rows)
    IOPV_CACHE.parent.mkdir(parents=True, exist_ok=True)
    if IOPV_CACHE.exists():
        existing = pd.read_csv(IOPV_CACHE)
        existing = existing[~((existing["date"] == today)
                              & (existing["code"].isin(df_new["code"])))]
        combined = pd.concat([existing, df_new], ignore_index=True)
    else:
        combined = df_new
    combined.to_csv(IOPV_CACHE, index=False)
    log(f"  [IOPV] 累积写入 {len(df_new)} 行 → {IOPV_CACHE.name} (总 {len(combined)} 行)")


def premium_history_stats(code: str, hist_df: pd.DataFrame) -> dict:
    if hist_df.empty:
        return {}
    sub = hist_df[hist_df["code"] == code].sort_values("date")
    if len(sub) < 5:
        return {}
    cur = sub["premium_pct"].iloc[-1]
    sub_1y = sub.tail(TRADING_DAYS)
    out = {
        "premium_days_history": len(sub),
        "premium_mean_1y": float(sub_1y["premium_pct"].mean()),
        "premium_std_1y": float(sub_1y["premium_pct"].std()),
        "premium_pct_rank_1y": float((sub_1y["premium_pct"] <= cur).mean() * 100),
    }
    if out["premium_std_1y"] and out["premium_std_1y"] > 0:
        out["premium_zscore_1y"] = float(
            (cur - out["premium_mean_1y"]) / out["premium_std_1y"]
        )
    return out


# ========== 每 ETF 全部指标 ==========
SPOT_DIRECT_FIELDS = [
    "最新价", "IOPV实时估值", "基金折价率", "涨跌幅", "昨收", "振幅", "换手率", "量比",
    "委比", "成交额", "成交量", "开盘价", "最高价", "最低价",
    "主力净流入-净额", "主力净流入-净占比",
    "超大单净流入-净额", "超大单净流入-净占比",
    "大单净流入-净额", "大单净流入-净占比",
    "中单净流入-净额", "中单净流入-净占比",
    "小单净流入-净额", "小单净流入-净占比",
    "最新份额", "流通市值", "总市值",
]


def compute_all(code: str, category: str, spot_df: pd.DataFrame,
                hist: pd.DataFrame | None, bench: pd.DataFrame | None,
                iopv_hist: pd.DataFrame, hist_source: str,
                stats: RunStats) -> dict:
    rec: dict = {"代码": code, "类别": category, "名称": "—", "状态": [],
                 "hist_source": hist_source}
    row = spot_df[spot_df["代码"] == code] if not spot_df.empty else pd.DataFrame()
    if not row.empty:
        r = row.iloc[0]
        rec["名称"] = str(r.get("名称", "—"))
        for f in SPOT_DIRECT_FIELDS:
            v = r.get(f)
            rec[f] = None if (v is None or pd.isna(v)) else v
            if rec[f] is not None:
                stats.tick(f"spot.{f}")
        if (rec.get("最新价") is not None and rec.get("IOPV实时估值") is not None
                and float(rec["IOPV实时估值"]) != 0):
            rec["溢价%"] = (float(rec["最新价"]) - float(rec["IOPV实时估值"])) / float(rec["IOPV实时估值"]) * 100
            stats.tick("compute.溢价%")
    else:
        rec["状态"].append("spot 缺失")

    if hist is None or hist.empty:
        rec["状态"].append("历史不可用,技术指标跳过")
        rec["状态"] = "; ".join(rec["状态"])
        return rec

    for d, label in [(7, "5日%"), (30, "1月%"), (91, "3月%"), (182, "6月%"), (365, "1年%")]:
        v = pct_window(hist, d)
        if v is not None:
            rec[label] = v
            stats.tick(f"window.{label}")

    for fn, label in [
        (price_extremes, "price_extremes"),
        (moving_averages, "moving_averages"),
        (macd_indicator, "macd"),
        (kdj_indicator, "kdj"),
        (volatility_indicator, "volatility"),
        (bollinger_indicator, "bollinger"),
        (keltner_channel, "keltner"),
        (drawdown_metrics, "drawdown"),
        (risk_adjusted, "risk_adj"),
        (volume_metrics, "volume"),
        (dmi_adx, "dmi_adx"),
    ]:
        try:
            d = fn(hist)
            rec.update(d)
            if d:
                stats.tick(f"calc.{label}")
        except Exception as e:
            log(f"      {code} {label} 失败: {e}", verbose_only=True)

    for f, label in [(rsi_indicator, "rsi_14"), (cci_indicator, "cci_14"),
                       (roc_indicator, "roc_10"), (williams_r_indicator, "williams_r_14")]:
        try:
            v = f(hist)
            if v is not None:
                rec[label] = v
                stats.tick(f"calc.{label}")
        except Exception:
            pass
    try:
        v = rsi_indicator(hist, 6)
        if v is not None:
            rec["rsi_6"] = v
            stats.tick("calc.rsi_6")
    except Exception:
        pass

    if bench is not None and code != BENCH_CODE:
        try:
            rec.update(relative_strength(hist, bench))
            stats.tick("calc.relative_strength")
        except Exception:
            pass

    if code in CROSS_BORDER_CODES:
        prem = premium_history_stats(code, iopv_hist)
        if prem:
            rec.update(prem)
            stats.tick("calc.premium_history")

    rec["状态"] = "; ".join(rec["状态"]) if rec["状态"] else ""
    return rec


# ========== 渲染 ==========
def fmt(v, d=2) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if isinstance(v, bool):
        return "✓" if v else ""
    if isinstance(v, str):
        return v
    try:
        return f"{float(v):.{d}f}"
    except (TypeError, ValueError):
        return str(v)


def fmt_pct(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    try:
        return f"{float(v):+.2f}"
    except (TypeError, ValueError):
        return "—"


def fmt_big(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    try:
        x = float(v)
        if abs(x) >= 1e8:
            return f"{x / 1e8:.2f}亿"
        if abs(x) >= 1e4:
            return f"{x / 1e4:.1f}万"
        return f"{x:.0f}"
    except (TypeError, ValueError):
        return "—"


def render_table(recs: list[dict], cols: list[tuple[str, str, str]]) -> list[str]:
    L = []
    headers = ["类别", "代码", "名称"] + [c[1] for c in cols]
    L.append("| " + " | ".join(headers) + " |")
    L.append("|" + "|".join(["---"] * len(headers)) + "|")
    for r in recs:
        row = [r.get("类别", ""), r.get("代码", ""), r.get("名称", "—")]
        for f, _, kind in cols:
            v = r.get(f)
            if kind == "num":
                row.append(fmt(v, 3))
            elif kind == "num2":
                row.append(fmt(v, 2))
            elif kind == "pct":
                row.append(fmt_pct(v))
            elif kind == "big":
                row.append(fmt_big(v))
            elif kind == "int":
                row.append(fmt(v, 0))
            else:
                row.append(str(v) if v not in (None, "") else "—")
        L.append("| " + " | ".join(row) + " |")
    return L


def render(records: list[dict], market: dict, stats: RunStats,
           out_path: Path, start_ts: datetime, end_ts: datetime,
           iopv_total_rows: int) -> None:
    L: list[str] = []
    L += [
        "# ETF 全清单完整数据快照（一站式 V2）",
        "",
        f"- **生成开始**: {start_ts:%Y-%m-%d %H:%M:%S}",
        f"- **生成结束**: {end_ts:%Y-%m-%d %H:%M:%S}",
        f"- **耗时**: {(end_ts - start_ts).total_seconds():.0f} 秒",
        f"- **覆盖标的**: {len(records)} 只",
        f"- **基准**: 沪深 300 (`{BENCH_CODE}`)",
        f"- **IOPV 历史累积**: {iopv_total_rows} 行（[`analysis_history/iopv_history.csv`](../analysis_history/iopv_history.csv)）",
        f"- **清单来源**: [`docs/etf_universe.md`](../docs/etf_universe.md)",
        f"- **指标参考**: [`docs/indicators_guide.md`](../docs/indicators_guide.md)",
        f"- **生成脚本**: [`tools/etf_full_snapshot.py`](../tools/etf_full_snapshot.py)",
        "",
        "## 一、运行健康度",
        "",
        f"- **spot 主接口命中**: {stats.spot_ok}",
        f"- **spot Sina 兜底**: {stats.spot_fallback}",
        f"- **spot 全失败**: {stats.spot_fail}",
        f"- **历史 Sina 主路径**: {stats.hist_sina_ok}",
        f"- **历史 EM 兜底**: {stats.hist_em_fallback}",
        f"- **历史全失败**: {stats.hist_fail}",
        f"- **市场宏观成功率**: {stats.market_ok}/{stats.market_attempts}",
        "",
        "## 二、市场宏观快照",
        "",
    ]
    if "market_activity" in market:
        L += ["### 2.1 全市场涨跌家数（`stock_market_activity_legu`）", "",
              "| 指标 | 值 |", "|---|---|"]
        for k, v in market["market_activity"].items():
            L.append(f"| {k} | {v} |")
        L.append("")
    elif "market_activity_err" in market:
        L += ["### 2.1 全市场涨跌家数", "",
              f"❌ 接口失败: {market['market_activity_err']}", ""]
    if "zt_count" in market:
        L += ["### 2.2 涨停池", "", f"- 涨停家数: **{market['zt_count']}**", ""]
    if "hsgt" in market:
        L += ["### 2.3 北向资金（`stock_hsgt_fund_flow_summary_em`）", ""]
        df = pd.DataFrame(market["hsgt"])
        if not df.empty:
            L.append("| " + " | ".join(df.columns) + " |")
            L.append("|" + "|".join(["---"] * len(df.columns)) + "|")
            for _, r in df.iterrows():
                L.append("| " + " | ".join(str(x) for x in r.values) + " |")
        L.append("")
    if "margin_sse" in market:
        L += ["### 2.4 上交所两融（近 3 日）", ""]
        df = pd.DataFrame(market["margin_sse"])
        L.append("| " + " | ".join(df.columns) + " |")
        L.append("|" + "|".join(["---"] * len(df.columns)) + "|")
        for _, r in df.iterrows():
            L.append("| " + " | ".join(str(x) for x in r.values) + " |")
        L.append("")
    if "hs300_pe" in market:
        pe = market["hs300_pe"]
        L += ["### 2.5 沪深 300 估值（`stock_index_pe_lg` / `stock_index_pb_lg`）", "",
              f"- **PE-TTM**: {pe['滚动市盈率']:.2f}（日期 {pe['日期']}）",
              f"- **PE 5 年分位**: {market.get('hs300_pe_pct_rank_5y', 0):.1f}%"]
        if "hs300_pb" in market:
            pb = market["hs300_pb"]
            L += [f"- **PB**: {pb['市净率']:.2f}",
                  f"- **PB 5 年分位**: {market.get('hs300_pb_pct_rank_5y', 0):.1f}%"]
        L.append("")

    # ETF 矩阵
    L += ["## 三、ETF 数据矩阵（按维度分表）", "",
          "### 3.1 价格盘口（🟢 直拉自 `fund_etf_spot_em`）", ""]
    L += render_table(records, [
        ("最新价", "现价", "num"),
        ("涨跌幅", "当日%", "pct"),
        ("开盘价", "今开", "num"), ("最高价", "今高", "num"), ("最低价", "今低", "num"),
        ("振幅", "振幅%", "num2"), ("换手率", "换手率%", "num2"),
        ("量比", "量比", "num2"), ("委比", "委比%", "num2"),
        ("成交额", "成交额", "big"), ("最新份额", "份额", "big"),
        ("流通市值", "流通市值", "big"),
    ])
    L += ["", "### 3.2 资金流分档（🟢 直拉自 `fund_etf_spot_em`）", ""]
    L += render_table(records, [
        ("主力净流入-净额", "主力净流入", "big"),
        ("主力净流入-净占比", "主力占比%", "num2"),
        ("超大单净流入-净额", "超大单", "big"),
        ("大单净流入-净额", "大单", "big"),
        ("中单净流入-净额", "中单", "big"),
        ("小单净流入-净额", "小单", "big"),
    ])
    L += ["", "### 3.3 多窗口收益（🟡 自算自 Sina 日 K）", ""]
    L += render_table(records, [
        ("5日%", "5日%", "pct"), ("1月%", "1月%", "pct"), ("3月%", "3月%", "pct"),
        ("6月%", "6月%", "pct"), ("1年%", "1年%", "pct"),
        ("ann_return_1y_pct", "年化%", "pct"),
    ])
    L += ["", "### 3.4 价格极值与突破（🟡 自算）", ""]
    L += render_table(records, [
        ("52w_high", "52w高", "num"), ("52w_low", "52w低", "num"),
        ("dist_52w_high_pct", "距高%", "pct"), ("dist_52w_low_pct", "距低%", "pct"),
        ("high_60d", "60d高", "num"), ("low_60d", "60d低", "num"),
        ("today_amplitude_pct", "振幅自算%", "num2"),
        ("is_new_52w_high", "破新高", "raw"), ("is_new_52w_low", "破新低", "raw"),
    ])
    L += ["", "### 3.5 均线系统（🟡 自算）", ""]
    L += render_table(records, [
        ("MA5", "MA5", "num"), ("MA20", "MA20", "num"), ("MA60", "MA60", "num"),
        ("MA120", "MA120", "num"), ("MA250", "MA250", "num"),
        ("price_vs_MA20_pct", "vs MA20%", "pct"),
        ("price_vs_MA60_pct", "vs MA60%", "pct"),
        ("MA20_slope_pct", "MA20斜率%", "pct"),
        ("bull_arrangement", "多排", "raw"), ("bear_arrangement", "空排", "raw"),
        ("ma_cross_5_20", "5/20交叉", "raw"),
        ("pct_days_above_MA20_60d", "60d>MA20%", "num2"),
    ])
    L += ["", "### 3.6 趋势 / 动量（🟡 自算）", ""]
    L += render_table(records, [
        ("macd_dif", "DIF", "num"), ("macd_dea", "DEA", "num"),
        ("macd_hist", "MACD柱", "num"), ("macd_cross", "MACD交叉", "raw"),
        ("rsi_14", "RSI14", "num2"), ("rsi_6", "RSI6", "num2"),
        ("kdj_k", "K", "num2"), ("kdj_d", "D", "num2"), ("kdj_j", "J", "num2"),
        ("cci_14", "CCI14", "num2"), ("roc_10", "ROC10", "num2"),
        ("williams_r_14", "%R14", "num2"),
        ("adx_14", "ADX14", "num2"), ("plus_di_14", "+DI14", "num2"),
        ("minus_di_14", "-DI14", "num2"),
    ])
    L += ["", "### 3.7 波动率 / 区间（🟡 自算）", ""]
    L += render_table(records, [
        ("vol_20d_ann", "年化波动20d%", "num2"),
        ("vol_60d_ann", "年化波动60d%", "num2"),
        ("vol_parkinson_20d", "Parkinson20d%", "num2"),
        ("vol_pct_rank_1y", "波动分位1y%", "num2"),
        ("downside_vol_60d_ann", "下行波动60d%", "num2"),
        ("atr_14", "ATR14", "num"),
        ("boll_upper", "布林上轨", "num"), ("boll_lower", "布林下轨", "num"),
        ("boll_pctb", "%B", "num2"), ("boll_bandwidth_pct", "带宽%", "num2"),
        ("keltner_upper", "Keltner上", "num"), ("keltner_lower", "Keltner下", "num"),
    ])
    L += ["", "### 3.8 风险调整收益（🟡 自算）", ""]
    L += render_table(records, [
        ("mdd_1y_pct", "MDD 1y%", "num2"), ("current_dd_pct", "当前回撤%", "num2"),
        ("dd_recovery_days", "恢复天数", "int"),
        ("sharpe_1y", "Sharpe", "num2"), ("sortino_1y", "Sortino", "num2"),
        ("calmar_1y", "Calmar", "num2"),
    ])
    L += ["", "### 3.9 成交量指标（🟡 自算）", ""]
    L += render_table(records, [
        ("VMA5", "VMA5", "big"), ("VMA20", "VMA20", "big"), ("VMA60", "VMA60", "big"),
        ("obv", "OBV", "big"), ("obv_slope_20d_pct", "OBV斜率20d%", "pct"),
        ("mfi_14", "MFI14", "num2"), ("cmf_20", "CMF20", "num2"),
    ])
    L += ["", "### 3.10 相对强度（🟡 vs 沪深 300）", ""]
    L += render_table(records, [
        ("rs_vs_bench_1m_pct", "RS 1m%", "pct"),
        ("rs_vs_bench_3m_pct", "RS 3m%", "pct"),
        ("rs_vs_bench_6m_pct", "RS 6m%", "pct"),
        ("beta_60d", "β60d", "num2"), ("corr_60d", "ρ60d", "num2"),
        ("tracking_error_60d_pct", "跟踪误差%", "num2"),
    ])
    L += ["", "### 3.11 跨境特征（🟢 直拉 IOPV + 🟡 自算溢价 + 累积历史分位）", ""]
    L += render_table(records, [
        ("IOPV实时估值", "IOPV", "num"),
        ("基金折价率", "折价率%", "num2"),
        ("溢价%", "溢价%", "pct"),
        ("premium_days_history", "历史天数", "int"),
        ("premium_mean_1y", "溢价均值1y", "num2"),
        ("premium_std_1y", "溢价σ1y", "num2"),
        ("premium_pct_rank_1y", "溢价分位1y%", "num2"),
        ("premium_zscore_1y", "溢价z", "num2"),
    ])

    # 缺失
    miss_spot = [r for r in records if r.get("最新价") is None]
    miss_hist = [r for r in records if r.get("MA20") is None]
    L += ["", "## 四、缺失与异常", ""]
    if not miss_spot and not miss_hist:
        L.append("无。")
    else:
        if miss_spot:
            L += [f"### 4.1 spot 缺失 ({len(miss_spot)} 条)", ""]
            for r in miss_spot:
                L.append(f"- `{r['代码']}` ({r['类别']}) — {r.get('状态') or '未知'}")
            L.append("")
        if miss_hist:
            L += [f"### 4.2 历史/均线缺失 ({len(miss_hist)} 条)", ""]
            for r in miss_hist:
                L.append(f"- `{r['代码']}` ({r['类别']}) — hist_source={r.get('hist_source')} / {r.get('状态') or ''}")
            L.append("")

    # 指标产出率
    L += ["", "## 五、指标产出率（本次实际填充率）", "",
          "| 指标 / 字段 | 命中数 | 占比 |", "|---|---|---|"]
    total = len(records)
    for k in sorted(stats.indicator_counts.keys()):
        n = stats.indicator_counts[k]
        L.append(f"| `{k}` | {n} | {n/total*100:.0f}% |")
    L.append("")

    out_path.write_text("\n".join(L), encoding="utf-8")


# ========== 主流程 ==========
def main() -> int:
    global VERBOSE
    p = argparse.ArgumentParser()
    p.add_argument("output", help="输出 Markdown 路径")
    p.add_argument("--verbose", "-v", action="store_true", help="打印重试与异常细节")
    p.add_argument("--no-iopv-cache", action="store_true",
                   help="跳过把今日 IOPV 写入本地累积 CSV")
    args = p.parse_args()
    VERBOSE = args.verbose

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    start_ts = datetime.now()
    stats = RunStats()
    all_codes = [c for codes in CATEGORIES.values() for c in codes]

    log(f"=== ETF 全清单快照 V2 ===")
    log(f"  目标: {len(all_codes)} 只 ETF, 51 类别")
    log(f"  基准: {BENCH_CODE}")
    log(f"  输出: {out_path}\n")

    log("[1/5] 拉取 ETF spot ...")
    spot = fetch_spot(all_codes, stats)

    log("[2/5] 拉取市场宏观 ...")
    market = fetch_market_globals(stats)
    log(f"  宏观成功率: {stats.market_ok}/{stats.market_attempts}")

    log(f"[3/5] 拉取基准({BENCH_CODE})历史 ...")
    bench, bsrc = fetch_history(BENCH_CODE, stats)
    log(f"  基准来源: {bsrc}, 长度: {len(bench) if bench is not None else 0}")

    log("[4/5] 加载/累积 IOPV 历史 ...")
    iopv_hist = load_iopv_history()
    pre_rows = len(iopv_hist)
    log(f"  本地累积: {pre_rows} 行")

    log("[5/5] 拉取 ETF 历史 + 计算全指标 ...")
    records: list[dict] = []
    total = len(all_codes)
    idx = 0
    for category, codes in CATEGORIES.items():
        for code in codes:
            idx += 1
            hist, hsrc = fetch_history(code, stats)
            rec = compute_all(code, category, spot, hist, bench, iopv_hist, hsrc, stats)
            records.append(rec)
            tag = "ok" if rec.get("最新价") is not None else "miss"
            log(f"   [{idx:>3}/{total}] {tag:>4} {category:<18} {code} {rec['名称']:<25} hist={hsrc}")

    if not args.no_iopv_cache:
        append_iopv_today(records)

    # 重新加载以计入今日累积
    iopv_hist_after = load_iopv_history()

    end_ts = datetime.now()
    log(f"\n渲染 → {out_path}")
    render(records, market, stats, out_path, start_ts, end_ts, len(iopv_hist_after))
    log(f"完成。耗时 {(end_ts - start_ts).total_seconds():.0f} 秒。")
    log(f"  spot 主路径: {stats.spot_ok} / 兜底: {stats.spot_fallback} / 失败: {stats.spot_fail}")
    log(f"  历史 Sina: {stats.hist_sina_ok} / EM 兜底: {stats.hist_em_fallback} / 失败: {stats.hist_fail}")
    log(f"  指标字段命中类目: {len(stats.indicator_counts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
