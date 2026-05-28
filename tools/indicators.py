"""技术指标 + 风险调整收益计算库（纯 pandas/numpy 实现）。

对应 docs/indicators_guide.md 的 P0/P1 项。所有函数都对单只标的的日线 DataFrame
（columns: date, open, high, low, close, volume）操作,返回扩展后的 DataFrame
或单标量字典。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


TRADING_DAYS = 252
RF_ANNUAL = 0.02


# ---------- 价格与极值 ----------
def price_extremes(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    close = df["close"]
    last = float(close.iloc[-1])
    tail252 = close.tail(TRADING_DAYS)
    tail60 = close.tail(60)
    tail120 = close.tail(120)
    high52, low52 = float(tail252.max()), float(tail252.min())
    out = {
        "52w_high": high52,
        "52w_low": low52,
        "dist_52w_high_pct": (last - high52) / high52 * 100 if high52 else None,
        "dist_52w_low_pct": (last - low52) / low52 * 100 if low52 else None,
        "high_60d": float(tail60.max()) if not tail60.empty else None,
        "low_60d": float(tail60.min()) if not tail60.empty else None,
        "high_120d": float(tail120.max()) if not tail120.empty else None,
        "low_120d": float(tail120.min()) if not tail120.empty else None,
        "is_new_52w_high": bool(last >= high52),
        "is_new_52w_low": bool(last <= low52),
    }
    # 振幅
    if len(df) >= 2:
        prev = float(close.iloc[-2])
        h = float(df["high"].iloc[-1])
        l = float(df["low"].iloc[-1])
        out["today_amplitude_pct"] = (h - l) / prev * 100 if prev else None
    return out


# ---------- 均线 ----------
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
            out[f"price_vs_MA{w}_pct"] = None
            continue
        ma = float(close.rolling(w).mean().iloc[-1])
        mas[w] = ma
        out[f"MA{w}"] = ma
        out[f"price_vs_MA{w}_pct"] = (last - ma) / ma * 100 if ma else None
        # 斜率：近 n 日均线相对 n 日前的均线
        ma_series = close.rolling(w).mean()
        if len(ma_series) > w:
            past = float(ma_series.iloc[-w])
            out[f"MA{w}_slope_pct"] = (ma - past) / past * 100 if past else None
    # 多空排列
    if all(k in mas for k in (5, 10, 20, 60)):
        out["bull_arrangement"] = mas[5] > mas[10] > mas[20] > mas[60]
        out["bear_arrangement"] = mas[5] < mas[10] < mas[20] < mas[60]
    # 金叉/死叉：MA5 vs MA20
    if len(close) >= 21:
        ma5 = close.rolling(5).mean()
        ma20 = close.rolling(20).mean()
        if len(ma5) >= 2 and len(ma20) >= 2:
            cross_today = ma5.iloc[-1] - ma20.iloc[-1]
            cross_prev = ma5.iloc[-2] - ma20.iloc[-2]
            if cross_prev < 0 and cross_today > 0:
                out["ma_cross_5_20"] = "golden"
            elif cross_prev > 0 and cross_today < 0:
                out["ma_cross_5_20"] = "death"
            else:
                out["ma_cross_5_20"] = "none"
    # 近 60 日价格在 MA20 上方的占比
    if len(close) >= 80:
        ma20 = close.rolling(20).mean()
        tail = (close.tail(60) > ma20.tail(60)).mean()
        out["pct_days_above_MA20_60d"] = float(tail) * 100
    return out


# ---------- 动量/趋势 ----------
def macd(df: pd.DataFrame, fast=12, slow=26, signal=9) -> dict:
    if df.empty or len(df) < slow + signal:
        return {}
    close = df["close"]
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = 2 * (dif - dea)
    cross = "none"
    if len(dif) >= 2 and len(dea) >= 2:
        diff_today = dif.iloc[-1] - dea.iloc[-1]
        diff_prev = dif.iloc[-2] - dea.iloc[-2]
        if diff_prev < 0 and diff_today > 0:
            cross = "golden"
        elif diff_prev > 0 and diff_today < 0:
            cross = "death"
    return {
        "macd_dif": float(dif.iloc[-1]),
        "macd_dea": float(dea.iloc[-1]),
        "macd_hist": float(hist.iloc[-1]),
        "macd_cross": cross,
    }


def rsi(df: pd.DataFrame, period=14) -> dict | None:
    if df.empty or len(df) < period + 1:
        return None
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    val = 100 - 100 / (1 + rs)
    if val.empty or pd.isna(val.iloc[-1]):
        return None
    return float(val.iloc[-1])


def kdj(df: pd.DataFrame, n=9, k_period=3, d_period=3) -> dict:
    if df.empty or len(df) < n:
        return {}
    low_n = df["low"].rolling(n).min()
    high_n = df["high"].rolling(n).max()
    rsv = (df["close"] - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    k = rsv.ewm(alpha=1 / k_period, adjust=False).mean()
    d = k.ewm(alpha=1 / d_period, adjust=False).mean()
    j = 3 * k - 2 * d
    return {
        "kdj_k": float(k.iloc[-1]) if pd.notna(k.iloc[-1]) else None,
        "kdj_d": float(d.iloc[-1]) if pd.notna(d.iloc[-1]) else None,
        "kdj_j": float(j.iloc[-1]) if pd.notna(j.iloc[-1]) else None,
    }


def cci(df: pd.DataFrame, period=14) -> float | None:
    if df.empty or len(df) < period:
        return None
    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma = tp.rolling(period).mean()
    md = tp.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    val = (tp - sma) / (0.015 * md.replace(0, np.nan))
    return float(val.iloc[-1]) if pd.notna(val.iloc[-1]) else None


def roc(df: pd.DataFrame, period=10) -> float | None:
    if df.empty or len(df) <= period:
        return None
    return float((df["close"].iloc[-1] / df["close"].iloc[-1 - period] - 1) * 100)


def williams_r(df: pd.DataFrame, period=14) -> float | None:
    if df.empty or len(df) < period:
        return None
    hh = df["high"].rolling(period).max().iloc[-1]
    ll = df["low"].rolling(period).min().iloc[-1]
    if hh == ll:
        return None
    return float((hh - df["close"].iloc[-1]) / (hh - ll) * -100)


# ---------- 波动率 ----------
def volatility(df: pd.DataFrame) -> dict:
    if df.empty or len(df) < 21:
        return {}
    ret = df["close"].pct_change().dropna()
    out = {}
    for w, name in [(20, "vol_20d_ann"), (60, "vol_60d_ann")]:
        if len(ret) >= w:
            out[name] = float(ret.tail(w).std() * np.sqrt(TRADING_DAYS) * 100)
    # 下行波动
    if len(ret) >= 60:
        downside = ret[ret < 0].tail(60)
        if len(downside) > 0:
            out["downside_vol_60d_ann"] = float(downside.std() * np.sqrt(TRADING_DAYS) * 100)
    # 历史波动分位（近 1 年滚动 20 日年化波动的当前分位）
    if len(ret) >= TRADING_DAYS + 20:
        rolling_vol = ret.rolling(20).std() * np.sqrt(TRADING_DAYS)
        recent_year = rolling_vol.tail(TRADING_DAYS).dropna()
        cur = rolling_vol.iloc[-1]
        if pd.notna(cur) and len(recent_year) > 0:
            out["vol_pct_rank_1y"] = float((recent_year <= cur).mean() * 100)
    return out


def atr(df: pd.DataFrame, period=14) -> float | None:
    if df.empty or len(df) < period + 1:
        return None
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


def bollinger(df: pd.DataFrame, period=20, k=2) -> dict:
    if df.empty or len(df) < period:
        return {}
    mid = df["close"].rolling(period).mean()
    sd = df["close"].rolling(period).std()
    upper = mid + k * sd
    lower = mid - k * sd
    close = df["close"].iloc[-1]
    band_width = (upper.iloc[-1] - lower.iloc[-1]) / mid.iloc[-1] * 100 if mid.iloc[-1] else None
    pctb = (close - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1]) if upper.iloc[-1] != lower.iloc[-1] else None
    return {
        "boll_upper": float(upper.iloc[-1]),
        "boll_mid": float(mid.iloc[-1]),
        "boll_lower": float(lower.iloc[-1]),
        "boll_pctb": float(pctb) if pctb is not None else None,
        "boll_bandwidth_pct": float(band_width) if band_width is not None else None,
    }


# ---------- 风险调整收益 ----------
def drawdown_metrics(df: pd.DataFrame, lookback=TRADING_DAYS) -> dict:
    if df.empty:
        return {}
    close = df["close"].tail(lookback)
    cummax = close.cummax()
    dd = close / cummax - 1
    mdd = float(dd.min() * 100)
    cur_dd = float(dd.iloc[-1] * 100)
    # 回撤恢复天数：最近一次跌至 MDD 后回到新高所用日数；未恢复则给当前持续天数
    out = {"mdd_1y_pct": mdd, "current_dd_pct": cur_dd}
    if mdd < 0:
        bottom_idx = dd.idxmin()
        peak_before = close.loc[:bottom_idx].idxmax()
        post = close.loc[bottom_idx:]
        target = close.loc[peak_before]
        recovered = post[post >= target]
        if not recovered.empty:
            out["dd_recovery_days"] = int((recovered.index[0] - bottom_idx).days)
        else:
            out["dd_recovery_days"] = None
            out["days_since_mdd_bottom"] = int((close.index[-1] - bottom_idx).days)
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
    # MDD for Calmar
    close = df["close"].tail(TRADING_DAYS)
    dd = close / close.cummax() - 1
    mdd_abs = abs(dd.min())
    calmar = ann_ret / mdd_abs if mdd_abs > 0 else None
    return {
        "ann_return_1y_pct": float(ann_ret * 100),
        "sharpe_1y": float(sharpe) if sharpe is not None else None,
        "sortino_1y": float(sortino) if sortino is not None else None,
        "calmar_1y": float(calmar) if calmar is not None else None,
    }


# ---------- 成交量 ----------
def volume_metrics(df: pd.DataFrame) -> dict:
    if df.empty or "volume" not in df.columns:
        return {}
    vol = df["volume"]
    out = {}
    for w in (5, 20, 60):
        if len(vol) >= w:
            out[f"VMA{w}"] = float(vol.rolling(w).mean().iloc[-1])
    # OBV
    if len(df) >= 2:
        sign = np.sign(df["close"].diff().fillna(0))
        obv = (sign * vol).cumsum()
        out["obv"] = float(obv.iloc[-1])
        # OBV 斜率（近 20 日）
        if len(obv) >= 20:
            past = obv.iloc[-20]
            cur = obv.iloc[-1]
            if past != 0:
                out["obv_slope_20d_pct"] = float((cur - past) / abs(past) * 100)
    # MFI
    if len(df) >= 15 and all(c in df.columns for c in ("high", "low", "close", "volume")):
        tp = (df["high"] + df["low"] + df["close"]) / 3
        mf = tp * vol
        pos = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
        neg = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
        mfi = 100 - 100 / (1 + pos / neg.replace(0, np.nan))
        if pd.notna(mfi.iloc[-1]):
            out["mfi_14"] = float(mfi.iloc[-1])
    return out


# ---------- 相对强度（vs 基准） ----------
def relative_strength(df: pd.DataFrame, bench: pd.DataFrame, windows=(21, 63, 126)) -> dict:
    if df.empty or bench.empty:
        return {}
    out = {}
    close, bench_close = df["close"], bench["close"]
    for w, label in zip(windows, ("1m", "3m", "6m")):
        if len(close) > w and len(bench_close) > w:
            etf_ret = close.iloc[-1] / close.iloc[-1 - w] - 1
            bench_ret = bench_close.iloc[-1] / bench_close.iloc[-1 - w] - 1
            out[f"rs_vs_bench_{label}_pct"] = float((etf_ret - bench_ret) * 100)
    # β 与 ρ（60 日）
    ret_e = close.pct_change().dropna().tail(60)
    ret_b = bench_close.pct_change().dropna().tail(60)
    n = min(len(ret_e), len(ret_b))
    if n >= 30:
        ret_e2 = ret_e.tail(n).reset_index(drop=True)
        ret_b2 = ret_b.tail(n).reset_index(drop=True)
        var_b = ret_b2.var()
        if var_b > 0:
            out["beta_60d"] = float(ret_e2.cov(ret_b2) / var_b)
        out["corr_60d"] = float(ret_e2.corr(ret_b2))
        # 跟踪误差
        diff = ret_e2 - ret_b2
        out["tracking_error_60d_pct"] = float(diff.std() * np.sqrt(TRADING_DAYS) * 100)
    return out
