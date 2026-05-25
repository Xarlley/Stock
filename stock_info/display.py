"""控制台报表 + matplotlib 行情图。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # 无显示环境默认导出文件
import matplotlib.dates as mdates
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import pandas as pd

from .classifier import Security, SecurityType
from .fetcher import SpotQuote


def _setup_cjk_font() -> None:
    """matplotlib 默认拿不到 .ttc 内的多语种子字体，这里手动注册一次。"""
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]
    for path in candidates:
        try:
            fm.fontManager.addfont(path)
        except Exception:
            continue
    available = {f.name for f in fm.fontManager.ttflist}
    preferred = [
        "Noto Sans CJK SC", "Noto Sans CJK JP", "Noto Sans CJK",
        "WenQuanYi Zen Hei", "WenQuanYi Micro Hei",
        "Source Han Sans SC", "Microsoft YaHei", "PingFang SC", "SimHei",
    ]
    chosen = [n for n in preferred if n in available] + ["DejaVu Sans"]
    plt.rcParams["font.sans-serif"] = chosen
    plt.rcParams["axes.unicode_minus"] = False


_setup_cjk_font()


@dataclass
class WindowStats:
    label: str
    rows: int
    first_date: str
    last_date: str
    start_close: float
    end_close: float
    abs_change: float
    pct_change: float
    high: float
    low: float
    mean: float
    vol_total: float


def _slice_by_days(df_daily: pd.DataFrame, days: int) -> pd.DataFrame:
    if df_daily.empty:
        return df_daily
    cutoff = df_daily["date"].max() - timedelta(days=days)
    return df_daily[df_daily["date"] > cutoff].reset_index(drop=True)


def _stats(df: pd.DataFrame, label: str) -> Optional[WindowStats]:
    if df is None or df.empty:
        return None
    start_close = float(df["close"].iloc[0])
    end_close = float(df["close"].iloc[-1])
    return WindowStats(
        label=label,
        rows=len(df),
        first_date=str(df["date"].iloc[0].date()),
        last_date=str(df["date"].iloc[-1].date()),
        start_close=start_close,
        end_close=end_close,
        abs_change=end_close - start_close,
        pct_change=(end_close / start_close - 1) * 100 if start_close else float("nan"),
        high=float(df["high"].max()),
        low=float(df["low"].min()),
        mean=float(df["close"].mean()),
        vol_total=float(df["volume"].sum()),
    )


def _fmt_money(v: float) -> str:
    if v is None or pd.isna(v):
        return "—"
    av = abs(v)
    if av >= 1e8:
        return f"{v/1e8:.2f}亿"
    if av >= 1e4:
        return f"{v/1e4:.2f}万"
    return f"{v:,.2f}"


def _fmt_pct(v: float) -> str:
    if v is None or pd.isna(v):
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}%"


def _print_spot(spot: SpotQuote, sec: Security) -> None:
    kind = "ETF" if sec.type is SecurityType.ETF else "股票"
    market = sec.market.value.upper()
    arrow = "▲" if spot.pct_change >= 0 else "▼"
    print("=" * 72)
    print(f"{spot.name}  ({kind} · {market}{spot.code})")
    print("-" * 72)
    print(f"  最新价: {spot.price:>10.4f}   {arrow} {_fmt_pct(spot.pct_change)}   "
          f"涨跌额: {spot.change:+.4f}")
    print(f"  今开:   {spot.open:>10.4f}   昨收:   {spot.prev_close:>10.4f}")
    print(f"  最高:   {spot.high:>10.4f}   最低:   {spot.low:>10.4f}")
    print(f"  成交量: {_fmt_money(spot.volume):>10}   成交额: {_fmt_money(spot.amount):>10}")
    if spot.turnover is not None:
        print(f"  换手率: {spot.turnover:.2f}%")
    extras = []
    for k, v in spot.extra.items():
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        if k in {"总市值", "流通市值"}:
            extras.append(f"{k}: {_fmt_money(float(v))}")
        else:
            try:
                extras.append(f"{k}: {float(v):.2f}")
            except (TypeError, ValueError):
                extras.append(f"{k}: {v}")
    if extras:
        print("  " + "   ".join(extras))
    print(f"  数据时间: {spot.timestamp}")
    print("=" * 72)


def _print_window_table(rows: list[WindowStats]) -> None:
    if not rows:
        print("(无历史数据)")
        return
    headers = ["窗口", "区间", "起→止", "涨跌幅", "区间高", "区间低", "均价"]
    fmt = "{:<6}  {:<23}  {:>17}  {:>9}  {:>10}  {:>10}  {:>10}"
    print(fmt.format(*headers))
    print("-" * 100)
    for s in rows:
        period = f"{s.first_date} → {s.last_date}"
        move = f"{s.start_close:.4f}→{s.end_close:.4f}"
        print(fmt.format(
            s.label,
            period,
            move,
            _fmt_pct(s.pct_change),
            f"{s.high:.4f}",
            f"{s.low:.4f}",
            f"{s.mean:.4f}",
        ))


def _plot_panel(ax, df: pd.DataFrame, title: str, x_col: str, y_col: str = "close", *, date_axis: bool = True):
    if df is None or df.empty:
        ax.set_title(f"{title}（无数据）")
        ax.axis("off")
        return
    x = df[x_col]
    y = df[y_col]
    line_color = "#c0392b" if y.iloc[-1] >= y.iloc[0] else "#27ae60"  # 红涨绿跌（A股习惯）
    ax.plot(x, y, color=line_color, linewidth=1.3)
    ax.fill_between(x, y, y.min(), color=line_color, alpha=0.08)
    ax.set_title(title, fontsize=11)
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.tick_params(axis="x", rotation=0, labelsize=8)
    ax.tick_params(axis="y", labelsize=8)
    if date_axis:
        span_days = (x.iloc[-1] - x.iloc[0]).days if len(x) > 1 else 0
        if span_days > 500:
            ax.xaxis.set_major_locator(mdates.YearLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        elif span_days > 90:
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=max(1, span_days // 200)))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))
        else:
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))


def _draw_charts(
    name_label: str,
    df_3y: pd.DataFrame,
    df_1y: pd.DataFrame,
    df_1m: pd.DataFrame,
    df_5d: pd.DataFrame,
    df_today: pd.DataFrame,
    out_path: Path,
) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    fig.suptitle(name_label, fontsize=14, fontweight="bold")

    _plot_panel(axes[0, 0], df_3y, "近3年（日K收盘）", "date")
    _plot_panel(axes[0, 1], df_1y, "近1年（日K收盘）", "date")
    _plot_panel(axes[0, 2], df_1m, "近1个月（日K收盘）", "date")
    _plot_panel(axes[1, 0], df_5d, "近5个交易日（日K收盘）", "date")

    if df_today is not None and not df_today.empty:
        _plot_panel(axes[1, 1], df_today, "今日分时（1分钟）", "time", date_axis=False)
        axes[1, 1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        if "avg" in df_today.columns:
            axes[1, 1].plot(df_today["time"], df_today["avg"], color="#f39c12", linewidth=1, label="均价")
            axes[1, 1].legend(fontsize=8, loc="best")
    else:
        axes[1, 1].set_title("今日分时（无数据）")
        axes[1, 1].axis("off")

    # 第六格用于显示成交量（近1年）
    ax_vol = axes[1, 2]
    if df_1y is not None and not df_1y.empty:
        ax_vol.bar(df_1y["date"], df_1y["volume"], color="#7f8c8d", width=1.0)
        ax_vol.set_title("近1年成交量", fontsize=11)
        ax_vol.grid(True, linestyle="--", alpha=0.4, axis="y")
        ax_vol.tick_params(labelsize=8)
        ax_vol.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
        ax_vol.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))
    else:
        ax_vol.set_title("近1年成交量（无数据）")
        ax_vol.axis("off")

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def render_report(
    sec: Security,
    spot: SpotQuote,
    df_daily_3y: pd.DataFrame,
    df_intraday_today: pd.DataFrame,
    chart_path: Path,
) -> None:
    _print_spot(spot, sec)

    df_3y = df_daily_3y
    df_1y = _slice_by_days(df_daily_3y, 365)
    df_1m = _slice_by_days(df_daily_3y, 30)
    df_5d = df_daily_3y.tail(5).reset_index(drop=True) if not df_daily_3y.empty else df_daily_3y

    stats = [s for s in (
        _stats(df_3y, "3年"),
        _stats(df_1y, "1年"),
        _stats(df_1m, "1月"),
        _stats(df_5d, "5日"),
    ) if s is not None]

    print("\n窗口统计：")
    _print_window_table(stats)

    name_label = f"{spot.name}  {sec.code}  ({'ETF' if sec.type is SecurityType.ETF else '股票'})"
    _draw_charts(name_label, df_3y, df_1y, df_1m, df_5d, df_intraday_today, chart_path)
    print(f"\n行情图已保存: {chart_path}")
