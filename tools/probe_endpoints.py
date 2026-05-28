"""探测金融分析指标全景指南中各项指标的 akshare 直拉接口可用性。

对每个接口尝试小规模拉取,记录:成功/失败/字段示例,作为分类依据。
"""
from __future__ import annotations

import warnings
warnings.filterwarnings("ignore")

import time
import traceback

import akshare as ak

PROBES: list[tuple[str, str, callable]] = []


def add(name: str, indicator: str, fn):
    PROBES.append((name, indicator, fn))


# ---------- ETF 份额 / 资金流相关 ----------
add("fund_etf_fund_info_em", "ETF 份额变化",
    lambda: ak.fund_etf_fund_info_em(fund="510300", start_date="20260101", end_date="20260528"))

add("fund_etf_category_sina (LOF/ETF分类)", "ETF 分类全表",
    lambda: ak.fund_etf_category_sina(symbol="ETF基金"))

add("fund_etf_hist_min_em", "ETF 分钟级",
    lambda: ak.fund_etf_hist_min_em(symbol="510300", period="5", adjust="", start_date="2026-05-28 09:30:00", end_date="2026-05-28 11:30:00"))

# ---------- 资金流（个股,ETF 通常不可用,但试） ----------
add("stock_individual_fund_flow", "主力净流入(对个股)",
    lambda: ak.stock_individual_fund_flow(stock="600519", market="sh"))

add("stock_individual_fund_flow_rank", "全市场资金流排名",
    lambda: ak.stock_individual_fund_flow_rank(indicator="今日"))

add("stock_sector_fund_flow_rank", "板块资金流排名",
    lambda: ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流"))

add("stock_sector_fund_flow_hist", "板块历史资金流",
    lambda: ak.stock_sector_fund_flow_hist(symbol="电子信息"))

# ---------- 北向资金 ----------
add("stock_hsgt_north_net_flow_in", "北向资金累计净流入",
    lambda: ak.stock_hsgt_north_net_flow_in(symbol="沪股通"))

add("stock_hsgt_fund_flow_summary_em", "北向资金汇总",
    lambda: ak.stock_hsgt_fund_flow_summary_em())

# ---------- 估值（指数级 PE/PB） ----------
add("stock_index_pe_lg", "指数 PE-TTM",
    lambda: ak.stock_index_pe_lg(symbol="沪深300"))

add("stock_index_pb_lg", "指数 PB",
    lambda: ak.stock_index_pb_lg(symbol="沪深300"))

add("index_value_hist_funddb", "指数估值历史(funddb)",
    lambda: ak.index_value_hist_funddb(symbol="沪深300", indicator="市盈率"))

# ---------- 涨跌停 / 市场情绪 ----------
add("stock_zt_pool_em", "涨停池",
    lambda: ak.stock_zt_pool_em(date="20260527"))

add("stock_market_activity_legu", "市场全景(涨跌家数)",
    lambda: ak.stock_market_activity_legu())

# ---------- 两融 ----------
add("stock_margin_sse", "上交所两融汇总",
    lambda: ak.stock_margin_sse(start_date="20260520", end_date="20260528"))

# ---------- 期权/IV ----------
add("option_finance_board (50ETF期权)", "50ETF 期权",
    lambda: ak.option_finance_board(symbol="50ETF", end_month="2606"))


def main():
    print(f"=== 探测 {len(PROBES)} 个 akshare 接口 ===\n")
    results = []
    for name, indicator, fn in PROBES:
        t0 = time.time()
        try:
            df = fn()
            dt = time.time() - t0
            if df is None:
                status = "EMPTY (None)"
                cols = "—"
                rows = 0
            elif hasattr(df, "empty") and df.empty:
                status = "EMPTY (空 DataFrame)"
                cols = "—"
                rows = 0
            else:
                status = "OK"
                cols = ", ".join(list(df.columns)[:10])
                rows = len(df)
            print(f"[{status:^14}] {name:<45} | {dt:5.1f}s | rows={rows:<5} | {indicator}")
            if status == "OK":
                print(f"                 columns: {cols}\n")
            results.append((name, indicator, status, rows, cols, dt))
        except Exception as e:
            dt = time.time() - t0
            msg = str(e).split("\n")[0][:80]
            print(f"[    FAIL    ] {name:<45} | {dt:5.1f}s | {indicator}")
            print(f"                 error: {type(e).__name__}: {msg}\n")
            results.append((name, indicator, f"FAIL: {type(e).__name__}", 0, msg, dt))

    print("\n=== 汇总 ===")
    ok = sum(1 for r in results if r[2] == "OK")
    print(f"OK: {ok}/{len(results)}")
    for name, indicator, status, rows, cols, dt in results:
        print(f"  {status:<25} {name:<45} {indicator}")


if __name__ == "__main__":
    main()
