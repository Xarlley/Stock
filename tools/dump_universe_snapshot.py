"""根据 docs/etf_universe.md 全清单拉取 ETF 数据,输出单一 Markdown 文件。

用法：
    python tools/dump_universe_snapshot.py <output_path.md>

输出：
    单一 Markdown,包含：
      - 元信息与字段说明
      - 全清单实时盘口 + 多窗口动量
      - 失败/缺失说明
"""

from __future__ import annotations

import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

import akshare as ak
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stock_info.classifier import classify, Market  # noqa: E402


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


def fetch_spot_table() -> pd.DataFrame:
    df = ak.fund_etf_spot_em()
    df = df.copy()
    df["代码"] = df["代码"].astype(str)
    return df


def fetch_history_sina(code: str) -> pd.DataFrame | None:
    """通过 Sina ETF 历史接口拉取日 K（不复权）。"""
    try:
        sec = classify(code)
        prefix = "sh" if sec.market is Market.SH else "sz" if sec.market is Market.SZ else "bj"
        df = ak.fund_etf_hist_sina(symbol=f"{prefix}{code}")
        if df is None or df.empty:
            return None
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception:
        return None


def pct(df: pd.DataFrame, days: int, end: datetime) -> float | None:
    if df is None or df.empty:
        return None
    close_now = float(df["close"].iloc[-1])
    cutoff = end - timedelta(days=days)
    sub = df[df["date"] > cutoff]
    if sub.empty:
        return None
    start = float(sub["close"].iloc[0])
    if start == 0:
        return None
    return (close_now / start - 1) * 100


def fmt_pct(v: float | None) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v:+.2f}"


def fmt_num(v, digits=3) -> str:
    if v is None or pd.isna(v):
        return "—"
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def build_record(code: str, category: str, spot_df: pd.DataFrame, end: datetime) -> dict:
    rec: dict = {
        "类别": category,
        "代码": code,
        "名称": "—",
        "现价": None,
        "昨收": None,
        "当日%": None,
        "IOPV": None,
        "溢价%": None,
        "成交额(亿)": None,
        "量比": None,
        "5日%": None,
        "1月%": None,
        "3月%": None,
        "6月%": None,
        "1年%": None,
        "状态": "",
    }

    row = spot_df[spot_df["代码"] == code]
    if not row.empty:
        r = row.iloc[0]
        price = r.get("最新价")
        iopv = r.get("IOPV实时估值")
        rec["名称"] = str(r.get("名称", "—"))
        rec["现价"] = price
        rec["昨收"] = r.get("昨收")
        rec["当日%"] = r.get("涨跌幅")
        rec["IOPV"] = iopv
        if pd.notna(price) and pd.notna(iopv) and float(iopv) != 0:
            rec["溢价%"] = (float(price) - float(iopv)) / float(iopv) * 100
        amount = r.get("成交额")
        if pd.notna(amount):
            rec["成交额(亿)"] = float(amount) / 1e8
        rec["量比"] = r.get("量比")
    else:
        rec["状态"] = "未在 fund_etf_spot_em 中(LOF/货币/已退市)"

    hist = fetch_history_sina(code)
    if hist is None:
        if not rec["状态"]:
            rec["状态"] = "Sina 历史不可用"
    else:
        rec["5日%"] = pct(hist, 7, end)
        rec["1月%"] = pct(hist, 30, end)
        rec["3月%"] = pct(hist, 91, end)
        rec["6月%"] = pct(hist, 182, end)
        rec["1年%"] = pct(hist, 365, end)

    return rec


def render_markdown(records: list[dict], out_path: Path, start_ts: datetime, end_ts: datetime) -> None:
    total = len(records)
    spot_ok = sum(1 for r in records if r["现价"] is not None and not pd.isna(r["现价"]))
    hist_ok = sum(1 for r in records if r["1月%"] is not None)
    missing_spot = [r for r in records if r["现价"] is None or pd.isna(r["现价"])]
    missing_hist = [r for r in records if r["1月%"] is None]

    lines = []
    lines.append("# ETF 全清单数据快照")
    lines.append("")
    lines.append(f"- **生成开始**：{start_ts.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- **生成结束**：{end_ts.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- **清单来源**：[`docs/etf_universe.md`](../docs/etf_universe.md)")
    lines.append(f"- **覆盖标的**：{total} 只（spot 命中 {spot_ok} / 历史命中 {hist_ok}）")
    lines.append(f"- **生成脚本**：[`tools/dump_universe_snapshot.py`](../tools/dump_universe_snapshot.py)")
    lines.append("")

    lines.append("## 一、数据说明")
    lines.append("")
    lines.append("| 字段 | 含义 | 来源 |")
    lines.append("|---|---|---|")
    lines.append("| 类别 | 板块/区域分组,源自 `docs/etf_universe.md` 的分节结构 | 本地静态映射 |")
    lines.append("| 代码 | 6 位 ETF 代码 | — |")
    lines.append("| 名称 | ETF 中文全名 | EastMoney `fund_etf_spot_em` |")
    lines.append("| 现价 | 抓取时刻最新成交价 | EastMoney `fund_etf_spot_em` |")
    lines.append("| 昨收 | 上一交易日收盘价 | EastMoney `fund_etf_spot_em` |")
    lines.append("| 当日% | 现价相对昨收的涨跌百分比 | EastMoney `fund_etf_spot_em` |")
    lines.append("| IOPV | 实时基金净值估算（参考净值）；跨境品种因海外市场未开盘而日内不更新 | EastMoney `fund_etf_spot_em` |")
    lines.append("| 溢价% | (现价 - IOPV) / IOPV × 100；正值=溢价,负值=贴水 | 本地计算 |")
    lines.append("| 成交额(亿) | 抓取时刻当日累计成交额 | EastMoney `fund_etf_spot_em` |")
    lines.append("| 量比 | 当日成交量 / 近 5 日同期成交量均值 | EastMoney `fund_etf_spot_em` |")
    lines.append("| 5日%/1月%/3月%/6月%/1年% | 按自然日窗口（约 7/30/91/182/365 天）的收益,以窗口内最早一根日 K 收盘为起点、最新一根为终点 | Sina `fund_etf_hist_sina` |")
    lines.append("| 状态 | 异常说明,正常时为空 | 本地标注 |")
    lines.append("")
    lines.append("**重要约定**：")
    lines.append("")
    lines.append("- 多窗口收益用「自然日切片」而非「交易日切片」,5 日窗口实际包含 4-5 个交易日。")
    lines.append("- 跨境 ETF 的 IOPV 在境内交易时段对应的是上一日海外收盘价,溢价反映的是境内对海外预期与情绪。")
    lines.append("- 货币基金（`511990`/`511880`）与 LOF（`162411`/`164824`）不在 ETF spot 接口范围内,会出现在「状态」列。")
    lines.append("- Sina 历史日 K 不复权;复权数据需另行处理。")
    lines.append("")

    lines.append("## 二、全清单（按类别）")
    lines.append("")
    header_cols = ["类别", "代码", "名称", "现价", "当日%", "IOPV", "溢价%", "5日%", "1月%", "3月%", "6月%", "1年%", "成交额(亿)", "量比", "状态"]
    lines.append("| " + " | ".join(header_cols) + " |")
    lines.append("|" + "|".join(["---"] * len(header_cols)) + "|")

    for rec in records:
        row = [
            rec["类别"],
            rec["代码"],
            rec["名称"],
            fmt_num(rec["现价"], 3),
            fmt_pct(rec["当日%"]),
            fmt_num(rec["IOPV"], 4),
            fmt_pct(rec["溢价%"]),
            fmt_pct(rec["5日%"]),
            fmt_pct(rec["1月%"]),
            fmt_pct(rec["3月%"]),
            fmt_pct(rec["6月%"]),
            fmt_pct(rec["1年%"]),
            fmt_num(rec["成交额(亿)"], 2),
            fmt_num(rec["量比"], 2),
            rec["状态"] or "",
        ]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    lines.append("## 三、缺失与异常")
    lines.append("")
    if not missing_spot and not missing_hist:
        lines.append("无。")
    else:
        if missing_spot:
            lines.append(f"### 3.1 spot 数据缺失（{len(missing_spot)} 条）")
            lines.append("")
            for r in missing_spot:
                lines.append(f"- `{r['代码']}` ({r['类别']}) — {r['状态'] or '未知原因'}")
            lines.append("")
        if missing_hist:
            lines.append(f"### 3.2 1 月以上历史缺失（{len(missing_hist)} 条）")
            lines.append("")
            for r in missing_hist:
                lines.append(f"- `{r['代码']}` ({r['类别']}) — {r['状态'] or '未知原因'}")
            lines.append("")

    lines.append("## 四、数据源接口")
    lines.append("")
    lines.append("- **实时盘口**：`akshare.fund_etf_spot_em()` — 一次性拉取全市场 ETF spot + IOPV,本地按代码筛选。")
    lines.append("- **历史日 K**：`akshare.fund_etf_hist_sina(symbol='sh510300')` — 全量返回单只 ETF 历史 K 线,本地按日期窗口切片。")
    lines.append("- 备用与稳定性说明见 [`docs/data_sources.md`](../docs/data_sources.md) 与 memory `reference-akshare-quirks`。")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    out_path = Path(sys.argv[1])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    start_ts = datetime.now()
    print(f"[1/3] 拉取全市场 ETF spot ...")
    spot_df = fetch_spot_table()

    print(f"[2/3] 拉取历史 + 计算窗口动量 ...")
    records: list[dict] = []
    for category, codes in CATEGORIES.items():
        for code in codes:
            rec = build_record(code, category, spot_df, datetime.now())
            records.append(rec)
            name = rec["名称"]
            mark = "ok" if rec["现价"] is not None and not pd.isna(rec["现价"]) else "miss"
            print(f"   {mark:>4} {category:<18} {code} {name}")

    end_ts = datetime.now()
    print(f"[3/3] 渲染 Markdown → {out_path}")
    render_markdown(records, out_path, start_ts, end_ts)

    print(f"完成。耗时 {(end_ts - start_ts).total_seconds():.0f} 秒。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
