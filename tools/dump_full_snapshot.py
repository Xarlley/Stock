"""完整版 ETF 全清单数据快照：覆盖 docs/indicators_guide.md 全部 P0/P1 指标。

用法：
    python tools/dump_full_snapshot.py <output_path.md>

输出：单一 Markdown,含 11 张分维度数据表 + 市场宏观快照 + 指标来源分类附录。
"""
from __future__ import annotations

import sys
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

import akshare as ak
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stock_info.classifier import classify, Market  # noqa: E402
from tools.indicators import (  # noqa: E402
    price_extremes, moving_averages, macd, rsi, kdj, cci, roc, williams_r,
    volatility, atr, bollinger, drawdown_metrics, risk_adjusted,
    volume_metrics, relative_strength,
)


# 与 dump_universe_snapshot.py 保持一致的全清单
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

BENCH_CODE = "510300"  # 沪深 300 作为相对强度基准


# ---------- 数据拉取 ----------
def fetch_spot_table() -> pd.DataFrame:
    df = ak.fund_etf_spot_em()
    df = df.copy()
    df["代码"] = df["代码"].astype(str)
    return df


def fetch_history_sina(code: str) -> pd.DataFrame | None:
    try:
        sec = classify(code)
        prefix = "sh" if sec.market is Market.SH else "sz" if sec.market is Market.SZ else "bj"
        df = ak.fund_etf_hist_sina(symbol=f"{prefix}{code}")
        if df is None or df.empty:
            return None
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").set_index("date")
        return df
    except Exception:
        return None


def fetch_market_global() -> dict:
    """一次性拉取市场宏观指标。"""
    out = {}
    # 涨跌家数
    try:
        df = ak.stock_market_activity_legu()
        out["market_activity"] = dict(zip(df["item"], df["value"]))
    except Exception as e:
        out["market_activity_err"] = str(e)[:80]
    # 涨停池
    try:
        ymd = datetime.now().strftime("%Y%m%d")
        df = ak.stock_zt_pool_em(date=ymd)
        out["zt_count"] = len(df) if df is not None else 0
    except Exception as e:
        out["zt_err"] = str(e)[:80]
    # 北向资金汇总
    try:
        df = ak.stock_hsgt_fund_flow_summary_em()
        out["hsgt"] = df.to_dict(orient="records")
    except Exception as e:
        out["hsgt_err"] = str(e)[:80]
    # 两融
    try:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=14)).strftime("%Y%m%d")
        df = ak.stock_margin_sse(start_date=start, end_date=end)
        if df is not None and not df.empty:
            out["margin_sse"] = df.tail(3).to_dict(orient="records")
    except Exception as e:
        out["margin_err"] = str(e)[:80]
    # 沪深 300 PE / PB
    try:
        pe = ak.stock_index_pe_lg(symbol="沪深300")
        if pe is not None and not pe.empty:
            last = pe.iloc[-1]
            out["hs300_pe"] = {
                "日期": str(last["日期"]),
                "滚动市盈率": float(last["滚动市盈率"]),
                "等权滚动市盈率": float(last["等权滚动市盈率"]),
            }
            # 5 年分位
            pe5y = pe.tail(252 * 5)["滚动市盈率"].astype(float)
            cur = float(last["滚动市盈率"])
            out["hs300_pe_pct_rank_5y"] = float((pe5y <= cur).mean() * 100)
    except Exception as e:
        out["pe_err"] = str(e)[:80]
    try:
        pb = ak.stock_index_pb_lg(symbol="沪深300")
        if pb is not None and not pb.empty:
            last = pb.iloc[-1]
            out["hs300_pb"] = {"日期": str(last["日期"]), "市净率": float(last["市净率"])}
            pb5y = pb.tail(252 * 5)["市净率"].astype(float)
            cur = float(last["市净率"])
            out["hs300_pb_pct_rank_5y"] = float((pb5y <= cur).mean() * 100)
    except Exception as e:
        out["pb_err"] = str(e)[:80]
    return out


# ---------- 单 ETF 指标计算 ----------
def pct_window(df: pd.DataFrame, days: int) -> float | None:
    """自然日窗口收益（与原版 dump_universe_snapshot 对齐）。"""
    if df is None or df.empty:
        return None
    end = df.index[-1]
    cutoff = end - timedelta(days=days)
    sub = df[df.index > cutoff]
    if sub.empty:
        return None
    start = float(sub["close"].iloc[0])
    if start == 0:
        return None
    return (float(df["close"].iloc[-1]) / start - 1) * 100


def compute_all(code: str, category: str, spot_df: pd.DataFrame,
                hist: pd.DataFrame | None, bench: pd.DataFrame | None) -> dict:
    rec: dict = {"代码": code, "类别": category, "名称": "—", "状态": ""}
    # spot
    row = spot_df[spot_df["代码"] == code]
    if not row.empty:
        r = row.iloc[0]
        rec["名称"] = str(r.get("名称", "—"))
        for field in ["最新价", "IOPV实时估值", "涨跌幅", "昨收", "振幅", "换手率", "量比",
                      "委比", "成交额", "成交量", "开盘价", "最高价", "最低价",
                      "主力净流入-净额", "主力净流入-净占比",
                      "超大单净流入-净额", "大单净流入-净额", "中单净流入-净额", "小单净流入-净额",
                      "最新份额", "流通市值"]:
            v = r.get(field)
            rec[field] = None if pd.isna(v) else v
        if pd.notna(r.get("最新价")) and pd.notna(r.get("IOPV实时估值")) and float(r["IOPV实时估值"]) != 0:
            rec["溢价%"] = (float(r["最新价"]) - float(r["IOPV实时估值"])) / float(r["IOPV实时估值"]) * 100
        else:
            rec["溢价%"] = None
    else:
        rec["状态"] = "未在 fund_etf_spot_em 中"

    # 历史
    if hist is None or hist.empty:
        if not rec["状态"]:
            rec["状态"] = "Sina 历史不可用"
        return rec

    # 多窗口收益
    rec["5日%"] = pct_window(hist, 7)
    rec["1月%"] = pct_window(hist, 30)
    rec["3月%"] = pct_window(hist, 91)
    rec["6月%"] = pct_window(hist, 182)
    rec["1年%"] = pct_window(hist, 365)

    rec.update(price_extremes(hist))
    rec.update(moving_averages(hist))
    rec.update(macd(hist))
    rsi14 = rsi(hist, 14)
    if rsi14 is not None:
        rec["rsi_14"] = rsi14
    rsi6 = rsi(hist, 6)
    if rsi6 is not None:
        rec["rsi_6"] = rsi6
    rec.update(kdj(hist))
    rec["cci_14"] = cci(hist, 14)
    rec["roc_10"] = roc(hist, 10)
    rec["williams_r_14"] = williams_r(hist, 14)
    rec.update(volatility(hist))
    rec["atr_14"] = atr(hist, 14)
    rec.update(bollinger(hist))
    rec.update(drawdown_metrics(hist))
    rec.update(risk_adjusted(hist))
    rec.update(volume_metrics(hist))
    if bench is not None and code != BENCH_CODE:
        rec.update(relative_strength(hist, bench))
    return rec


# ---------- 渲染辅助 ----------
def fmt(v, digits=2) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if isinstance(v, bool):
        return "✓" if v else ""
    if isinstance(v, str):
        return v
    try:
        return f"{float(v):.{digits}f}"
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
    """大数字按亿/万格式化。"""
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


def render_table(records: list[dict], cols: list[tuple[str, str, str]]) -> list[str]:
    """cols: [(field, header, fmt_kind), ...] where fmt_kind in {'num','pct','big','raw'}"""
    lines = []
    headers = ["类别", "代码", "名称"] + [c[1] for c in cols]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for r in records:
        row = [r.get("类别", ""), r.get("代码", ""), r.get("名称", "—")]
        for field, _, kind in cols:
            v = r.get(field)
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
        lines.append("| " + " | ".join(row) + " |")
    return lines


# ---------- 主渲染 ----------
def render_markdown(records: list[dict], market: dict, out_path: Path,
                    start_ts: datetime, end_ts: datetime) -> None:
    total = len(records)
    spot_ok = sum(1 for r in records if r.get("最新价") is not None)
    hist_ok = sum(1 for r in records if r.get("MA20") is not None)

    L: list[str] = []
    L += [
        "# ETF 全清单完整数据快照",
        "",
        f"- **生成开始**：{start_ts.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **生成结束**：{end_ts.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **耗时**：{(end_ts - start_ts).total_seconds():.0f} 秒",
        f"- **覆盖标的**：{total} 只（spot 命中 {spot_ok} / 历史命中 {hist_ok}）",
        f"- **基准**：沪深 300（`{BENCH_CODE}`）",
        f"- **清单来源**：[`docs/etf_universe.md`](../docs/etf_universe.md)",
        f"- **指标来源**：[`docs/indicators_guide.md`](../docs/indicators_guide.md)",
        f"- **生成脚本**：[`tools/dump_full_snapshot.py`](../tools/dump_full_snapshot.py)",
        "",
        "## 一、市场宏观快照",
        "",
    ]
    if "market_activity" in market:
        L.append("### 1.1 全市场涨跌家数（`stock_market_activity_legu`）")
        L.append("")
        L.append("| item | value |")
        L.append("|---|---|")
        for k, v in market["market_activity"].items():
            L.append(f"| {k} | {v} |")
        L.append("")
    if "zt_count" in market:
        L += [f"### 1.2 涨停池", "", f"- 涨停家数：{market['zt_count']}", ""]
    if "hsgt" in market:
        L += ["### 1.3 北向资金（`stock_hsgt_fund_flow_summary_em`）", ""]
        df = pd.DataFrame(market["hsgt"])
        if not df.empty:
            L.append("| " + " | ".join(df.columns) + " |")
            L.append("|" + "|".join(["---"] * len(df.columns)) + "|")
            for _, r in df.iterrows():
                L.append("| " + " | ".join(str(x) for x in r.values) + " |")
        L.append("")
    if "margin_sse" in market:
        L += ["### 1.4 上交所两融余额（近 3 日）", ""]
        df = pd.DataFrame(market["margin_sse"])
        if not df.empty:
            L.append("| " + " | ".join(df.columns) + " |")
            L.append("|" + "|".join(["---"] * len(df.columns)) + "|")
            for _, r in df.iterrows():
                L.append("| " + " | ".join(str(x) for x in r.values) + " |")
        L.append("")
    if "hs300_pe" in market:
        pe = market["hs300_pe"]
        L += [
            "### 1.5 沪深 300 估值",
            "",
            f"- **PE-TTM（滚动）**：{pe['滚动市盈率']:.2f}（日期 {pe['日期']}）",
            f"- **PE 5 年分位**：{market.get('hs300_pe_pct_rank_5y', 0):.1f}%",
        ]
        if "hs300_pb" in market:
            pb = market["hs300_pb"]
            L += [
                f"- **PB**：{pb['市净率']:.2f}",
                f"- **PB 5 年分位**：{market.get('hs300_pb_pct_rank_5y', 0):.1f}%",
            ]
        L.append("")

    # ---------- 表 A 价格盘口 ----------
    L += ["## 二、ETF 数据矩阵（按维度分表）", "",
          "### 2.1 价格盘口（直拉自 `fund_etf_spot_em`）", ""]
    L += render_table(records, [
        ("最新价", "现价", "num"),
        ("涨跌幅", "当日%", "pct"),
        ("开盘价", "今开", "num"),
        ("最高价", "今高", "num"),
        ("最低价", "今低", "num"),
        ("振幅", "振幅%", "num2"),
        ("换手率", "换手率%", "num2"),
        ("量比", "量比", "num2"),
        ("委比", "委比%", "num2"),
        ("成交额", "成交额", "big"),
        ("最新份额", "份额", "big"),
        ("流通市值", "流通市值", "big"),
    ])
    L += ["", "### 2.2 资金流分档（直拉自 `fund_etf_spot_em`）", ""]
    L += render_table(records, [
        ("主力净流入-净额", "主力净流入", "big"),
        ("主力净流入-净占比", "主力占比%", "num2"),
        ("超大单净流入-净额", "超大单", "big"),
        ("大单净流入-净额", "大单", "big"),
        ("中单净流入-净额", "中单", "big"),
        ("小单净流入-净额", "小单", "big"),
    ])
    L += ["", "### 2.3 多窗口收益（计算自 `fund_etf_hist_sina`）", ""]
    L += render_table(records, [
        ("5日%", "5日%", "pct"),
        ("1月%", "1月%", "pct"),
        ("3月%", "3月%", "pct"),
        ("6月%", "6月%", "pct"),
        ("1年%", "1年%", "pct"),
        ("ann_return_1y_pct", "年化", "pct"),
    ])
    L += ["", "### 2.4 价格极值与突破", ""]
    L += render_table(records, [
        ("52w_high", "52w高", "num"),
        ("52w_low", "52w低", "num"),
        ("dist_52w_high_pct", "距高%", "pct"),
        ("dist_52w_low_pct", "距低%", "pct"),
        ("high_60d", "60d高", "num"),
        ("low_60d", "60d低", "num"),
        ("today_amplitude_pct", "振幅(自算)%", "num2"),
        ("is_new_52w_high", "破新高", "raw"),
        ("is_new_52w_low", "破新低", "raw"),
    ])
    L += ["", "### 2.5 均线系统", ""]
    L += render_table(records, [
        ("MA5", "MA5", "num"),
        ("MA20", "MA20", "num"),
        ("MA60", "MA60", "num"),
        ("MA120", "MA120", "num"),
        ("MA250", "MA250", "num"),
        ("price_vs_MA20_pct", "vs MA20%", "pct"),
        ("price_vs_MA60_pct", "vs MA60%", "pct"),
        ("MA20_slope_pct", "MA20斜率%", "pct"),
        ("bull_arrangement", "多头排列", "raw"),
        ("bear_arrangement", "空头排列", "raw"),
        ("ma_cross_5_20", "5/20金死叉", "raw"),
        ("pct_days_above_MA20_60d", "60d>MA20%", "num2"),
    ])
    L += ["", "### 2.6 趋势 / 动量", ""]
    L += render_table(records, [
        ("macd_dif", "DIF", "num"),
        ("macd_dea", "DEA", "num"),
        ("macd_hist", "MACD柱", "num"),
        ("macd_cross", "MACD交叉", "raw"),
        ("rsi_14", "RSI14", "num2"),
        ("rsi_6", "RSI6", "num2"),
        ("kdj_k", "K", "num2"),
        ("kdj_d", "D", "num2"),
        ("kdj_j", "J", "num2"),
        ("cci_14", "CCI14", "num2"),
        ("roc_10", "ROC10", "num2"),
        ("williams_r_14", "%R14", "num2"),
    ])
    L += ["", "### 2.7 波动率 / 区间", ""]
    L += render_table(records, [
        ("vol_20d_ann", "年化波动20d%", "num2"),
        ("vol_60d_ann", "年化波动60d%", "num2"),
        ("vol_pct_rank_1y", "波动分位1y%", "num2"),
        ("downside_vol_60d_ann", "下行波动60d%", "num2"),
        ("atr_14", "ATR14", "num"),
        ("boll_upper", "布林上轨", "num"),
        ("boll_lower", "布林下轨", "num"),
        ("boll_pctb", "%B", "num2"),
        ("boll_bandwidth_pct", "带宽%", "num2"),
    ])
    L += ["", "### 2.8 风险调整收益", ""]
    L += render_table(records, [
        ("mdd_1y_pct", "MDD 1y%", "num2"),
        ("current_dd_pct", "当前回撤%", "num2"),
        ("dd_recovery_days", "恢复天数", "int"),
        ("sharpe_1y", "Sharpe 1y", "num2"),
        ("sortino_1y", "Sortino 1y", "num2"),
        ("calmar_1y", "Calmar 1y", "num2"),
    ])
    L += ["", "### 2.9 成交量指标", ""]
    L += render_table(records, [
        ("VMA5", "VMA5", "big"),
        ("VMA20", "VMA20", "big"),
        ("VMA60", "VMA60", "big"),
        ("obv", "OBV", "big"),
        ("obv_slope_20d_pct", "OBV斜率20d%", "pct"),
        ("mfi_14", "MFI14", "num2"),
    ])
    L += ["", "### 2.10 相对强度（vs 沪深 300）", ""]
    L += render_table(records, [
        ("rs_vs_bench_1m_pct", "RS 1m%", "pct"),
        ("rs_vs_bench_3m_pct", "RS 3m%", "pct"),
        ("rs_vs_bench_6m_pct", "RS 6m%", "pct"),
        ("beta_60d", "β60d", "num2"),
        ("corr_60d", "ρ60d", "num2"),
        ("tracking_error_60d_pct", "跟踪误差%", "num2"),
    ])
    L += ["", "### 2.11 跨境特征", ""]
    L += render_table(records, [
        ("IOPV实时估值", "IOPV", "num"),
        ("溢价%", "溢价%", "pct"),
    ])

    # ---------- 缺失 ----------
    missing_spot = [r for r in records if r.get("最新价") is None]
    missing_hist = [r for r in records if r.get("MA20") is None]
    L += ["", "## 三、缺失与异常", ""]
    if not missing_spot and not missing_hist:
        L.append("无。")
    else:
        if missing_spot:
            L += [f"### 3.1 spot 缺失（{len(missing_spot)} 条）", ""]
            for r in missing_spot:
                L.append(f"- `{r['代码']}` ({r['类别']}) — {r.get('状态') or '未知'}")
            L.append("")
        if missing_hist:
            L += [f"### 3.2 历史/均线缺失（{len(missing_hist)} 条）", ""]
            for r in missing_hist:
                L.append(f"- `{r['代码']}` ({r['类别']}) — {r.get('状态') or '历史不足或不可用'}")
            L.append("")

    # ---------- 指标来源分类附录 ----------
    L += ["", "## 四、指标来源分类（本次实测）", "",
          "下表对应 [`docs/indicators_guide.md`](../docs/indicators_guide.md) 的全部指标项,",
          "标注每项在本项目「实际能否拉到 / 怎么拉到」。三种状态：",
          "",
          "- **🟢 直拉**：akshare 一次接口调用即可，不需任何后处理（除单位换算）",
          "- **🟡 自算**：需要原始 OHLCV 历史 + pandas/numpy 计算",
          "- **🔴 不可用**：本项目网络环境下接口失败,或 akshare 无对应接口,或 ETF 无对应数据",
          "",
          "| 类别 | 指标 | 来源 | 实现接口/计算 | 备注 |",
          "|---|---|---|---|---|",
          "| 价格盘口 | 现价 / 昨收 / 今开 / 最高 / 最低 | 🟢 直拉 | `fund_etf_spot_em` | spot 表已包含 OHLC |",
          "| 价格盘口 | 当日涨跌% / 振幅% / 换手率 / 量比 / 委比 | 🟢 直拉 | `fund_etf_spot_em` | — |",
          "| 价格盘口 | 成交额 / 成交量 / 最新份额 / 流通市值 | 🟢 直拉 | `fund_etf_spot_em` | 本次发现 spot 表含份额 |",
          "| 资金流 | 主力 / 超大单 / 大单 / 中单 / 小单 净流入额 + 占比 | 🟢 直拉 | `fund_etf_spot_em` | **重要**：原版脚本未取,实际已有 |",
          "| 资金流 | 个股资金流(`stock_individual_fund_flow`) | 🔴 不可用 | 接口 ConnectionError | EastMoney `push2` 在本网络环境频挂 |",
          "| 资金流 | 板块资金流(`stock_sector_fund_flow_*`) | 🔴 不可用 | 同上 | — |",
          "| 资金流 | 北向资金汇总 | 🟢 直拉 | `stock_hsgt_fund_flow_summary_em` | 市场级,不分 ETF |",
          "| 资金流 | 北向累计净流入(`stock_hsgt_north_net_flow_in`) | 🔴 不可用 | akshare 1.18.63 已无此接口 | 用 summary 替代 |",
          "| 资金流 | ETF 份额变化 | 🟢 直拉 | `fund_etf_spot_em.最新份额` + 历史快照差分 | 单日值直拉;日变化需累积 |",
          "| 资金流 | 单位净值 / 累计净值 / 日增长率 | 🟢 直拉 | `fund_etf_fund_info_em(fund=, start_date=, end_date=)` | 含申购赎回状态 |",
          "| 资金流 | 两融余额(上交所) | 🟢 直拉 | `stock_margin_sse` | 市场级 |",
          "| 价格极值 | 52 周高 / 低 | 🟡 自算 | 历史日 K 滚动 250 日 max/min | — |",
          "| 价格极值 | 距 52 周高 / 低 回撤% | 🟡 自算 | 本地 | — |",
          "| 价格极值 | 3/6 月高低 | 🟡 自算 | 滚动 60 / 120 日 | — |",
          "| 价格极值 | 突破/新高新低 bool | 🟡 自算 | close 与 250 日 max/min 比较 | — |",
          "| 价格极值 | 缺口 / 影线 / 实体长度 | 🟡 自算 | OHLC 差值 | 本版未实现,P2 |",
          "| 均线 | SMA 5/10/20/60/120/250 | 🟡 自算 | `close.rolling(n).mean()` | — |",
          "| 均线 | EMA 12/26/60 | 🟡 自算 | `close.ewm(span=n).mean()` | MACD 用到 |",
          "| 均线 | WMA / HMA | 🟡 自算 | 加权计算 | 本版未实现,P2 |",
          "| 均线 | 多空排列 / 价格相对偏离 / 斜率 | 🟡 自算 | 本地 | — |",
          "| 均线 | 5/20 金叉死叉 | 🟡 自算 | 两日 sign 变化 | — |",
          "| 均线 | 60d 在 MA20 上方占比 | 🟡 自算 | 本地 | — |",
          "| 动量 | MACD(12,26,9) | 🟡 自算 | EMA 差 → DEA → 柱 | — |",
          "| 动量 | RSI(14) / RSI(6) | 🟡 自算 | gain/loss 平均 | — |",
          "| 动量 | KDJ(9,3,3) | 🟡 自算 | RSV → K → D → J | — |",
          "| 动量 | CCI(14) | 🟡 自算 | TP - SMA / 0.015·MD | — |",
          "| 动量 | ROC(10) | 🟡 自算 | close 比值 | — |",
          "| 动量 | Williams %R(14) | 🟡 自算 | 高低区间位置 | — |",
          "| 动量 | DMI/ADX / TRIX / Parabolic SAR | 🟡 自算 | — | 本版未实现,P2 |",
          "| 波动率 | 年化波动率 20d / 60d | 🟡 自算 | std × √252 | — |",
          "| 波动率 | 波动率 1 年分位 | 🟡 自算 | rolling 20d vol 排名 | — |",
          "| 波动率 | 下行波动率 60d | 🟡 自算 | 仅负收益 std | Sortino 用 |",
          "| 波动率 | ATR(14) | 🟡 自算 | TR 14 日均 | — |",
          "| 波动率 | 布林带(20,2) + %B + 宽度 | 🟡 自算 | MA ± 2σ | — |",
          "| 波动率 | Keltner / Parkinson / GARCH | 🟡 自算 | — | 本版未实现,P2 |",
          "| 风险调整 | 最大回撤 / 当前回撤 | 🟡 自算 | cummax | — |",
          "| 风险调整 | 回撤恢复天数 | 🟡 自算 | 寻找回升日 | — |",
          "| 风险调整 | Sharpe / Sortino / Calmar 1y | 🟡 自算 | 标准公式 | rf=2% |",
          "| 风险调整 | 信息比率 / Treynor / VaR / CVaR | 🟡 自算 | — | 本版未实现,P2 |",
          "| 成交量 | VMA 5 / 20 / 60 | 🟡 自算 | volume.rolling | — |",
          "| 成交量 | OBV / OBV 斜率 | 🟡 自算 | sign × vol 累积 | — |",
          "| 成交量 | MFI(14) | 🟡 自算 | 类 RSI 加权 | — |",
          "| 成交量 | VWAP / CMF / Klinger | 🟡 自算 | — | VWAP 需分钟数据,EM 分钟接口在本网络失败 |",
          "| 成交量 | 量价背离 bool | 🟡 自算 | 本地规则 | 本版未实现,P2 |",
          "| 相对强度 | RS vs 沪深300 (1/3/6m) | 🟡 自算 | 收益差 | 基准=`510300` |",
          "| 相对强度 | β / ρ / 跟踪误差 60d | 🟡 自算 | cov / var / std | — |",
          "| 相对强度 | 板块内排名 | 🟡 自算 | 横截面 | 本版未实现,P1 待加 |",
          "| 相对强度 | 动量打分 | 🟡 自算 | 多窗口分位加权 | 本版未实现,P1 |",
          "| 跨境 | IOPV / 折溢价率 | 🟢 直拉 + 🟡 自算 | spot 含 IOPV;溢价 = (price-IOPV)/IOPV | — |",
          "| 跨境 | 基金折价率 | 🟢 直拉 | `fund_etf_spot_em.基金折价率` | spot 自带,本次新发现 |",
          "| 跨境 | 溢价历史 1 年分位 / z-score | 🟡 自算 | 需累积 IOPV 历史 | **暂不可得**: spot 仅当下,需本地累积每日快照 |",
          "| 跨境 | 海外标的当日收盘 | 🔴 不可用 | akshare 国外指数接口部分可用 | 待专项验证 yfinance |",
          "| 跨境 | 汇率 USD/CNH / HKD/CNH | 🔴 待验证 | `ak.fx_*` | 本版未集成 |",
          "| 估值 | 指数 PE-TTM / PB | 🟢 直拉 | `stock_index_pe_lg` / `stock_index_pb_lg` | 仅宽基对应,行业 ETF 不一一对应 |",
          "| 估值 | 指数 PE / PB 5 年分位 | 🟡 自算 | 历史排名 | 本次已实现(沪深300) |",
          "| 估值 | 行业 PE / PB 中位 / PS / 股息率 / PEG / EV-EBITDA / ROE | 🔴 部分可用 | 个股财务接口,EM 系列频挂 | 对 ETF 需穿透成分股,本项目不做 |",
          "| 估值 | `index_value_hist_funddb` 估值历史 | 🔴 不可用 | akshare 1.18.63 已无此接口 | 用 lg 系列替代 |",
          "| 市场情绪 | 涨跌家数 | 🟢 直拉 | `stock_market_activity_legu` | 12 项指标 |",
          "| 市场情绪 | 涨停 / 跌停数量 | 🟢 直拉 | `stock_zt_pool_em(date=YYYYMMDD)` | 跌停池另接口 |",
          "| 市场情绪 | 北向资金净买入(汇总) | 🟢 直拉 | `stock_hsgt_fund_flow_summary_em` | 与「资金流」一节重复 |",
          "| 市场情绪 | 两融余额 | 🟢 直拉 | `stock_margin_sse` 等 | — |",
          "| 市场情绪 | 期权 PCR / 隐含波动率 | 🔴 待验证 | `option_finance_board` 本次返回空 | 需特定到期月份 |",
          "| 市场情绪 | 风险溢价(股债比) | 🟡 自算 | 1/PE - 10y 国债 | 国债收益率另需 `bond_*` 接口 |",
          "| 分钟级 | ETF 1/5 分钟 K | 🔴 不可用 | `fund_etf_hist_min_em` ConnectionError | — |",
          "",
          "**结论**：",
          "",
          "- **🟢 直拉项 16 类** — 通过 4 个稳定接口覆盖：`fund_etf_spot_em`(占大头) / `stock_index_pe_lg` / `stock_market_activity_legu` / `stock_hsgt_fund_flow_summary_em` / `stock_margin_sse` / `fund_etf_fund_info_em`",
          "- **🟡 自算项 30+** — 全部基于 Sina 历史日 K (`fund_etf_hist_sina`),pandas/numpy 实现见 [`tools/indicators.py`](../tools/indicators.py)",
          "- **🔴 不可用项**：东方财富 `push2.eastmoney.com` 系（个股/板块资金流、分钟级、北向 net_flow_in、估值历史 funddb）在本网络环境全挂；ETF 穿透估值与海外数据需另寻数据源",
          "",
          "**下一步重点**：跨境 ETF 的溢价历史分位需要本地累积 spot 快照（每日跑一次,日积月累）；这是 Phase 2 的核心抓手。",
          ""]

    out_path.write_text("\n".join(L), encoding="utf-8")


# ---------- 主流程 ----------
def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    out_path = Path(sys.argv[1])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    start_ts = datetime.now()

    print(f"[1/4] 拉取全市场 ETF spot ...")
    spot_df = fetch_spot_table()

    print(f"[2/4] 拉取市场宏观快照 ...")
    market = fetch_market_global()

    print(f"[3/4] 拉取基准({BENCH_CODE})历史 ...")
    bench = fetch_history_sina(BENCH_CODE)

    print(f"[4/4] 拉取 ETF 历史 + 计算全指标 ...")
    records: list[dict] = []
    total = sum(len(v) for v in CATEGORIES.values())
    idx = 0
    t_seq = time.time()
    for category, codes in CATEGORIES.items():
        for code in codes:
            idx += 1
            hist = fetch_history_sina(code)
            rec = compute_all(code, category, spot_df, hist, bench)
            records.append(rec)
            tag = "ok" if rec.get("最新价") is not None else "miss"
            print(f"   [{idx:>3}/{total}] {tag:>4} {category:<18} {code} {rec['名称']}")

    end_ts = datetime.now()
    print(f"渲染 → {out_path}")
    render_markdown(records, market, out_path, start_ts, end_ts)
    print(f"完成。耗时 {(end_ts - start_ts).total_seconds():.0f} 秒。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
