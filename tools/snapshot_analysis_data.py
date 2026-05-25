"""导出本次分析依赖的全部数据到磁盘，作为决策当时的数据快照。

用法：
    python tools/snapshot_analysis_data.py <output_dir> <code1> [code2 ...]

输出：
    <output_dir>/README.txt
    <output_dir>/spot_all_sina_raw.txt
    <output_dir>/spot_<code>.txt          # 单标的可读盘口
    <output_dir>/daily_<code>.csv         # 日 K 历史（≥3 年）
    <output_dir>/window_stats.txt         # 窗口统计汇总
"""

from __future__ import annotations

import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stock_info import classify, fetch_spot, fetch_history  # noqa: E402
from stock_info.classifier import Market  # noqa: E402


def sina_symbol(sec) -> str:
    prefix = "sh" if sec.market is Market.SH else "sz" if sec.market is Market.SZ else "bj"
    return f"{prefix}{sec.code}"


def dump_sina_raw(secs, out_path: Path) -> None:
    syms = ",".join(sina_symbol(s) for s in secs)
    url = f"http://hq.sinajs.cn/list={syms}"
    headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=10)
    r.encoding = "gbk"
    out_path.write_text(
        "# Sina hq.sinajs.cn 原始返回（gbk 解码）\n"
        f"# URL: {url}\n"
        f"# 抓取时间: {datetime.now().isoformat(timespec='seconds')}\n"
        "# 字段顺序: 名称, 今开, 昨收, 现价, 今高, 今低, 买1价, 卖1价, 成交量(股),\n"
        "#           成交额(元), [买1档:量,价]*5, [卖1档:量,价]*5, 日期, 时间, ...\n\n"
        + r.text,
        encoding="utf-8",
    )


def dump_spot(sec, spot, out_path: Path) -> None:
    lines = [
        f"# 实时盘口快照 · {sec.code}",
        f"# 抓取时间: {datetime.now().isoformat(timespec='seconds')}",
        "",
        f"名称              : {spot.name}",
        f"代码              : {sec.code}",
        f"类型              : {sec.type.value}",
        f"市场              : {sec.market.value.upper()}",
        f"最新价            : {spot.price}",
        f"昨收              : {spot.prev_close}",
        f"今开              : {spot.open}",
        f"今高              : {spot.high}",
        f"今低              : {spot.low}",
        f"涨跌额            : {spot.change:+.4f}",
        f"涨跌幅            : {spot.pct_change:+.2f}%",
        f"成交量            : {spot.volume}",
        f"成交额            : {spot.amount}",
        f"换手率            : {spot.turnover if spot.turnover is not None else '—'}",
        f"数据时间          : {spot.timestamp}",
        "",
        "# 附加字段（仅在原始接口提供时存在）:",
    ]
    for k, v in spot.extra.items():
        lines.append(f"  {k:<14} : {v}")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def dump_daily(sec, df: pd.DataFrame, out_path: Path) -> None:
    if df is None or df.empty:
        out_path.write_text(f"# {sec.code}: 历史数据为空\n", encoding="utf-8")
        return
    # 在 CSV 顶部写元数据注释
    header = (
        f"# {sec.code} 日 K 历史（前复权）\n"
        f"# 抓取时间: {datetime.now().isoformat(timespec='seconds')}\n"
        f"# 行数: {len(df)}  区间: {df['date'].iloc[0].date()} → {df['date'].iloc[-1].date()}\n"
        f"# 列说明: date 日期, open 开盘, close 收盘, high 最高, low 最低,\n"
        f"#         volume 成交量(份), amount 成交额(元), 其他列由数据源决定\n"
    )
    csv_text = df.to_csv(index=False, float_format="%.6f")
    out_path.write_text(header + csv_text, encoding="utf-8")


def compute_window_stats(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {}
    end_date = df["date"].max()
    out = {}
    for label, days in [("3年", 365 * 3), ("1年", 365), ("1月", 30), ("5日", 7)]:
        sub = df[df["date"] > end_date - timedelta(days=days)]
        if sub.empty:
            continue
        s = float(sub["close"].iloc[0])
        e = float(sub["close"].iloc[-1])
        out[label] = {
            "rows": len(sub),
            "first_date": str(sub["date"].iloc[0].date()),
            "last_date": str(sub["date"].iloc[-1].date()),
            "start_close": s,
            "end_close": e,
            "pct_change": (e / s - 1) * 100 if s else float("nan"),
            "high": float(sub["high"].max()),
            "low": float(sub["low"].min()),
            "mean_close": float(sub["close"].mean()),
            "volume_sum": float(sub["volume"].sum()),
        }
    return out


def dump_window_stats(stats_by_code: dict, out_path: Path) -> None:
    lines = [
        "# 窗口统计汇总",
        f"# 生成时间: {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]
    for code, stats in stats_by_code.items():
        lines.append(f"## {code}")
        if not stats:
            lines.append("  (无数据)")
            lines.append("")
            continue
        header = f"{'窗口':<6}{'起止区间':<27}{'起→止':<28}{'涨跌幅':>10}{'区间高':>12}{'区间低':>12}{'均价':>12}"
        lines.append(header)
        lines.append("-" * len(header))
        for label, s in stats.items():
            period = f"{s['first_date']} → {s['last_date']}"
            move = f"{s['start_close']:.4f}→{s['end_close']:.4f}"
            lines.append(
                f"{label:<6}{period:<27}{move:<28}"
                f"{s['pct_change']:+9.2f}%{s['high']:>12.4f}{s['low']:>12.4f}{s['mean_close']:>12.4f}"
            )
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def write_readme(out_dir: Path, secs, file_list: list[str]) -> None:
    txt = [
        "# 本次分析依赖数据快照",
        f"生成时间: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## 涉及标的",
    ]
    for s in secs:
        txt.append(f"- {s.code}  类型={s.type.value}  市场={s.market.value.upper()}")
    txt += [
        "",
        "## 文件清单",
    ]
    for f in file_list:
        txt.append(f"- {f}")
    txt += [
        "",
        "## 数据源",
        "- 实时盘口（Sina）：http://hq.sinajs.cn/list=...",
        "- 实时盘口（EastMoney）：通过 akshare.fund_etf_spot_em / stock_bid_ask_em",
        "- 日 K 历史（EastMoney）：通过 akshare.fund_etf_hist_em / stock_zh_a_hist",
        "- 日 K 历史（Sina 兜底）：通过 akshare.fund_etf_hist_sina / stock_zh_a_daily",
        "",
        "## 用途",
        "- 复盘当次决策所基于的市场状态",
        "- 后续回测 / 评估操作建议在事后是否正确",
        "- 训练/验证未来的分析模块",
        "",
        "## 注意",
        "- 价格数据为抓取时刻的最新一笔，盘中分钟级数据未保存（如需可单独导出 1 分钟分时）",
        "- 历史日 K 默认前复权（qfq），含分红再投资的复权处理",
    ]
    (out_dir / "README.txt").write_text("\n".join(txt), encoding="utf-8")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2

    out_dir = Path(sys.argv[1])
    codes = sys.argv[2:]
    out_dir.mkdir(parents=True, exist_ok=True)

    secs = [classify(c) for c in codes]

    print(f"[1/4] 落盘 Sina 原始报文 ...")
    dump_sina_raw(secs, out_dir / "spot_all_sina_raw.txt")

    print(f"[2/4] 逐标的拉实时盘口（{len(secs)} 只）...")
    for s in secs:
        try:
            spot = fetch_spot(s)
            dump_spot(s, spot, out_dir / f"spot_{s.code}.txt")
            print(f"   ✓ {s.code} {spot.name}  价 {spot.price}")
        except Exception as e:
            (out_dir / f"spot_{s.code}.ERROR.txt").write_text(f"{type(e).__name__}: {e}\n", encoding="utf-8")
            print(f"   ✗ {s.code} 失败: {e}")

    print(f"[3/4] 逐标的拉近 3 年日 K ...")
    end = datetime.now()
    start = end - timedelta(days=365 * 3 + 30)
    stats_by_code = {}
    for s in secs:
        try:
            df = fetch_history(s, start, end, adjust="qfq")
            dump_daily(s, df, out_dir / f"daily_{s.code}.csv")
            stats_by_code[s.code] = compute_window_stats(df)
            print(f"   ✓ {s.code} 日K {len(df)} 行")
        except Exception as e:
            (out_dir / f"daily_{s.code}.ERROR.txt").write_text(f"{type(e).__name__}: {e}\n", encoding="utf-8")
            stats_by_code[s.code] = {}
            print(f"   ✗ {s.code} 失败: {e}")

    print(f"[4/4] 写入窗口统计 + README ...")
    dump_window_stats(stats_by_code, out_dir / "window_stats.txt")

    files = sorted(p.name for p in out_dir.iterdir() if p.is_file())
    write_readme(out_dir, secs, files)

    print(f"\n完成。输出目录：{out_dir}")
    print(f"共 {len(files)} 个文件：")
    for f in files:
        size = (out_dir / f).stat().st_size
        print(f"  {f:<40} {size:>10,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
