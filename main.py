"""CLI 入口：输入 A 股 / ETF 代码，输出实时行情与历史走势。

用法：
    python main.py 600519
    python main.py 510300
    python main.py 600519 --no-chart
    python main.py 510300 --chart-dir ./charts
"""

from __future__ import annotations

import argparse
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")  # 屏蔽 akshare 依赖里的 deprecation 噪音

from stock_info import classify, fetch_spot, fetch_history, fetch_intraday, render_report


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="中国大陆 A 股 / ETF 行情查询")
    p.add_argument("code", help="6 位代码，支持 sh/sz 前缀，例如 600519、sh600519、510300")
    p.add_argument("--chart-dir", default="./charts", help="行情图输出目录（默认 ./charts）")
    p.add_argument("--no-intraday", action="store_true", help="跳过日内分时（节省一次网络请求）")
    p.add_argument("--years", type=int, default=3, help="历史窗口最长年数（默认 3）")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    try:
        sec = classify(args.code)
    except ValueError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 2

    print(f"[1/3] 拉取实时行情 ...")
    spot = fetch_spot(sec)

    print(f"[2/3] 拉取近 {args.years} 年日K ...")
    end = datetime.now()
    start = end - timedelta(days=args.years * 365 + 30)
    df_daily = fetch_history(sec, start, end, adjust="qfq")
    if df_daily.empty:
        print("[警告] 历史日K为空，可能是新上市或代码错误", file=sys.stderr)

    if args.no_intraday:
        df_today = df_daily.iloc[0:0]
    else:
        print(f"[3/3] 拉取今日分时 ...")
        try:
            df_today = fetch_intraday(sec)
        except Exception as e:
            print(f"[警告] 分时数据失败：{e}", file=sys.stderr)
            df_today = df_daily.iloc[0:0]

    chart_dir = Path(args.chart_dir)
    chart_file = chart_dir / f"{sec.code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"

    render_report(sec, spot, df_daily, df_today, chart_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
