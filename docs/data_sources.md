# 数据获取方法手册

> 本文档总结本项目实际跑通过的所有数据获取方法，每条均经过本会话实测。
> 网络环境：中国大陆 / 一般家用宽带，akshare 1.18.63，Python 3.13。
> **本会话观察到的主要风险**：东方财富 `push2.eastmoney.com` 系列接口频繁出现
> `('Connection aborted.', RemoteDisconnected(...))` 错误，需要重试 + 兜底机制。
> 新浪 `hq.sinajs.cn` 等接口在本会话中始终稳定。

---

## 速查表

| 我想要的数据 | 首选方法 | 失败时的兜底 | 平均耗时 |
| --- | --- | --- | --- |
| 单股实时盘口（最新价/五档） | Sina 直连 | `ak.stock_bid_ask_em` | < 1 s |
| 单 ETF 实时盘口（不含 IOPV） | Sina 直连 | — | < 1 s |
| ETF 实时 IOPV / 溢价率 | `ak.fund_etf_spot_em()` | 无替代 | ~15 s |
| 股票日 K 历史 | `ak.stock_zh_a_hist` | `ak.stock_zh_a_daily`（Sina） | 1-3 s |
| ETF 日 K 历史 | `ak.fund_etf_hist_em` | `ak.fund_etf_hist_sina` | 1-3 s |
| 股票 1 分钟分时 | `ak.stock_zh_a_minute`（Sina） | — | 1-2 s |
| 股票代码 → 名称字典 | `ak.stock_info_a_code_name` | — | ~3 s |

---

## 1. 实时盘口

### 1.1 ✅ Sina 直连（**首选**：单条 GET，支持批量）

```python
import requests

url = "http://hq.sinajs.cn/list=sh600519,sh510300,sz159941"  # 逗号分隔批量
r = requests.get(
    url,
    headers={
        "Referer": "https://finance.sina.com.cn",   # 必须
        "User-Agent": "Mozilla/5.0",
    },
    timeout=10,
)
r.encoding = "gbk"  # Sina 用 gbk 编码

# 返回 var hq_str_sh600519="贵州茅台,1287.000,1290.200,..."；
for line in r.text.strip().split("\n"):
    sym = line.split('"')[0].split('_')[-1].rstrip('=')
    parts = line.split('"')[1].split(",")
    name        = parts[0]
    today_open  = float(parts[1])
    prev_close  = float(parts[2])
    current     = float(parts[3])
    high        = float(parts[4])
    low         = float(parts[5])
    bid1_price  = float(parts[6])
    ask1_price  = float(parts[7])
    volume_shares = float(parts[8])    # 单位：股（ETF 单位：份）
    amount_yuan = float(parts[9])
    # 10..29: 5 档买卖盘，格式 [vol_i, price_i] × 5（买）+ [vol_i, price_i] × 5（卖）
    date_s      = parts[30]
    time_s      = parts[31]
```

**优点**：
- 单次 HTTP 调用，响应通常 < 1 秒
- 支持一次拉多个标的（逗号分隔）
- 本会话中**未观察到任何失败**

**限制**：
- 只有市场价，**没有 IOPV / 溢价率**
- ETF / 股票都能用，但需用 `sh` / `sz` / `bj` 前缀
- 闭市后返回的是最后一笔成交

**调用规范**：必须带 `Referer: https://finance.sina.com.cn`，否则会被拒。

### 1.2 ✅ 单股 EastMoney（含 5 档 + 涨跌停 + 内外盘）

```python
import akshare as ak

df = ak.stock_bid_ask_em(symbol="600519")
# 返回长格式 DataFrame，列: item, value
kv = dict(zip(df["item"], df["value"]))
# 关键字段: 最新, 昨收, 今开, 最高, 最低, 涨幅, 涨跌, 总手, 金额, 换手,
#           均价, 量比, 涨停, 跌停, 外盘, 内盘,
#           sell_5..sell_1, sell_5_vol..sell_1_vol,
#           buy_1..buy_5, buy_1_vol..buy_5_vol
```

**优点**：单股，比 `stock_zh_a_spot_em` 快得多
**风险**：本会话中部分时段失败（push2.eastmoney.com 连接被中断）

### 1.3 ✅ ETF 全市场快照（**唯一能拿 IOPV 的方法**）

```python
import akshare as ak

df = ak.fund_etf_spot_em()  # 全市场 ETF，14 页分页，~15 秒
row = df[df["代码"] == "513100"].iloc[0]
# 关键字段:
#   名称, 最新价, 涨跌幅, 开盘价, 最高价, 最低价, 昨收, 成交额, 换手率,
#   IOPV实时估值, 基金折价率,   ← 这俩 Sina 接口拿不到
#   总市值, 流通市值, 量比, 委比, 主力净流入-净额 等
```

**优点**：**唯一稳定能拿到 IOPV 和溢价率的接口**
**限制**：
- 14 页分页，每次 ~15 秒
- 拉全市场 ETF（500+ 只），单标的需求时浪费带宽
- 缓存：同一进程内不应短时间多次调用，应自己缓存

**重要**：QDII / 跨境 ETF 的真假涨判别完全依赖这个接口（见下文「应用案例」）。

### 1.4 ❌ **不要用** `ak.stock_zh_a_spot_em()`

全 A 股快照，**58 页分页**，本会话中**多次中途失败**。即使想拉单股也得跑完整批次。
**替代**：用 1.1（Sina）或 1.2（单股 EM）。

### 1.5 ❌ **不要用** `ak.stock_individual_info_em()`

本会话连续 3 次连接被拒，未见成功过。若需股票元数据（行业、市值等）用其他途径。

---

## 2. 历史日 K

### 2.1 ✅ 股票日 K（首选 EastMoney + Sina 兜底）

```python
import akshare as ak

# 首选：EastMoney，支持日期切片
df = ak.stock_zh_a_hist(
    symbol="600519",         # 不带前缀
    period="daily",          # 或 "weekly" / "monthly"
    start_date="20230101",
    end_date="20261231",
    adjust="qfq",            # "" 不复权 / "qfq" 前复权 / "hfq" 后复权
)
# 列（中文）：日期, 股票代码, 开盘, 收盘, 最高, 最低, 成交量, 成交额,
#             振幅, 涨跌幅, 涨跌额, 换手率
```

**Sina 兜底（不支持日期切片，返回全部历史，需自己过滤）**：

```python
df = ak.stock_zh_a_daily(symbol="sh600519", adjust="qfq")  # 注意带前缀
# 列（英文）：date, open, high, low, close, volume, amount,
#             outstanding_share, turnover
import pandas as pd
df["date"] = pd.to_datetime(df["date"])
df = df[(df["date"] >= "2023-01-01") & (df["date"] <= "2026-12-31")]
```

**本项目封装**：[stock_info/fetcher.py:fetch_history()](../stock_info/fetcher.py) 已实现「EM 优先 + Sina 兜底」。

### 2.2 ✅ ETF 日 K

```python
df = ak.fund_etf_hist_em(
    symbol="510300",         # 不带前缀
    period="daily",
    start_date="20230101",
    end_date="20261231",
    adjust="qfq",
)
# 列同股票，但无「股票代码」列
```

**兜底**：

```python
df = ak.fund_etf_hist_sina(symbol="sh510300")  # 带前缀，全量
```

**本会话踩过的坑**：`fund_etf_hist_em` 在 2026-05-25 当日多次失败，需 5 次重试。
[stock_info/fetcher.py](../stock_info/fetcher.py) 的 `_retry()` 函数已封装好。

---

## 3. 日内分时（1 分钟 K）

### 3.1 ✅ 股票 1 分钟（**首选 Sina**）

```python
df = ak.stock_zh_a_minute(
    symbol="sh600519",       # 带前缀
    period="1",              # "1" / "5" / "15" / "30" / "60"
    adjust="",
)
# 列：day, open, high, low, close, volume, amount
# day 列是字符串 "2026-05-25 13:27:00"
df["day"] = pd.to_datetime(df["day"])
# 返回最近 N 天的 1 分钟 K（通常 5-10 天）
```

**本会话观察**：Sina 接口稳定，未失败。

### 3.2 ⚠️ EastMoney 1 分钟（**会失败，不推荐**）

```python
ak.stock_zh_a_hist_min_em(symbol="600519",
                          start_date="2026-05-25 09:30:00",
                          end_date="2026-05-25 15:00:00",
                          period="1", adjust="")
ak.fund_etf_hist_min_em(symbol="510300", ...)  # ETF 版本
```

本会话调用全部失败。如需 ETF 1 分钟，目前无可靠方法（待后续探索）。

---

## 4. 元数据

### 4.1 ✅ 全 A 股代码 → 名称字典

```python
df = ak.stock_info_a_code_name()  # ~3 秒，16 页分页
# 列：code, name
name_map = dict(zip(df["code"], df["name"]))
print(name_map["600519"])  # 贵州茅台
```

**用途**：[stock_info/fetcher.py](../stock_info/fetcher.py) 在 `stock_bid_ask_em` 不返回名称时调用，**进程内缓存一次即可**。

---

## 5. 通用网络容错模式

### 5.1 指数退避重试

```python
import time

def retry(fn, attempts=4, base_delay=1.0):
    last_err = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_err = e
            time.sleep(base_delay * (2 ** i))
    raise last_err

# 用法
df = retry(lambda: ak.fund_etf_hist_em(symbol="159941",
                                       period="daily",
                                       start_date="20230101",
                                       end_date="20261231",
                                       adjust="qfq"),
           attempts=5)
```

**实测**：5 次重试基本能覆盖 EastMoney 的瞬时抖动。
**何时该放弃**：5 次都失败说明端点本身有问题（不是网络抖动），改用 Sina 兜底。

### 5.2 双源策略（EM 优先 / Sina 兜底）

```python
def get_etf_history(code, start, end):
    try:
        return retry(lambda: ak.fund_etf_hist_em(
            symbol=code, period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="qfq"
        ), attempts=3)
    except Exception:
        sym = ("sh" if code.startswith("5") else "sz") + code
        df = retry(lambda: ak.fund_etf_hist_sina(symbol=sym), attempts=3)
        # Sina 返回全量，自己切片
        df["date"] = pd.to_datetime(df["date"])
        return df[(df["date"] >= start) & (df["date"] <= end)]
```

### 5.3 并发降级

不要并发调用 EastMoney 接口（push2.eastmoney.com 单 IP 限流明显）。
**串行 + 重试 > 并发 + 失败**。

### 5.4 警惕「数据对齐」陷阱

不同接口对「今日」数据处理不同：
- EastMoney `stock_zh_a_hist` / `fund_etf_hist_em`：盘中调用会把最新一笔作为今日的 close
- Sina `stock_zh_a_daily` / `fund_etf_hist_sina`：只有真正收盘后才有今日数据
- 若同一报告里对比两个时序的「近 5 日涨幅」等指标，**必须确保两边的截止日期完全一致**

本会话已经因此犯过错（v1 报告里 159941 vs 513100 的 5 日涨幅对比），后被用户修正。

---

## 6. 应用案例

### 6.1 QDII 真假涨 60 秒判别法

**场景**：盘中纳指 ETF / 标普 ETF 突然上涨，需判断是真利好（NDX 真动）还是国内尾盘抢筹（纯溢价扩张）。

```python
import requests, akshare as ak

# Step 1: Sina 拿瞬时价（< 1 秒）
url = "http://hq.sinajs.cn/list=sh513100,sz159941"
r = requests.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=8)
r.encoding = "gbk"
# 解析略...

# Step 2: EastMoney 拿 IOPV（~15 秒）
df = ak.fund_etf_spot_em()
iopv_513100 = float(df[df["代码"] == "513100"]["IOPV实时估值"].iloc[0])
iopv_159941 = float(df[df["代码"] == "159941"]["IOPV实时估值"].iloc[0])

# Step 3: 判别
# - IOPV 同步上涨 → 真利好（美股期货动了）
# - IOPV 不动     → 纯国内溢价扩张（散户抢筹，警惕回归）
```

**实测案例**（2026-05-25 本会话）：
- 13:48: 513100 价 2.214，IOPV 2.013 → 溢价 10.0%
- 14:45: 513100 价 2.234，IOPV 2.013 → 溢价 11.0%
- 港股两只 ETF（513050、513130）完全没跟涨
- **诊断**：100% 国内抢筹，无任何真利好
- **结果**：促成 v5 紧急减仓决策

完整记录见 [analysis_history/2026-05-25_001_data/intraday_premium_timeline.txt](../analysis_history/2026-05-25_001_data/intraday_premium_timeline.txt)。

### 6.2 单股快速行情查询

```bash
python3 main.py 600519              # 含历史 + 图表
python3 main.py 600519 --no-intraday  # 跳过日内分时（更快）
```

### 6.3 批量数据快照（分析归档用）

```bash
python3 tools/snapshot_analysis_data.py <output_dir> <code1> [code2 ...]
```

输出 spot + 日 K + 窗口统计，用于决策时的数据冻结。

---

## 7. 已知问题与待办

| 问题 | 影响 | 临时方案 | 长期方案 |
| --- | --- | --- | --- |
| ETF 1 分钟分时无可靠源 | 无法精确复盘 ETF 日内 | 用 5 分钟 / Sina 股票分时近似 | 找替代源（雪球？腾讯？）|
| IOPV 没有历史时序接口 | 无法回测溢价均值回归 | 自建 `--watch` 模式持续落盘 | 长期沉淀数据资产 |
| `stock_zh_a_spot_em` 太重 | 单股查询浪费 50+ 秒 | 用 `stock_bid_ask_em` 或 Sina | — |
| `push2.eastmoney.com` 偶发拒连 | 关键时刻数据获取延迟 | 5 次重试 + Sina 兜底 | 多源加权 + 实时切换 |
| 没有北交所（4xx/8xx）测试 | 北交所标的可能未覆盖 | — | 补测试用例 |

---

## 8. 参考

- akshare 文档: https://akshare.akfamily.xyz
- Sina 行情接口（非官方文档）: 各端口字段说明见 [stock_info/fetcher.py:_fetch_sina_spot()](../stock_info/fetcher.py)
- 本项目封装的数据层: [stock_info/fetcher.py](../stock_info/fetcher.py)
- 本项目数据归档脚本: [tools/snapshot_analysis_data.py](../tools/snapshot_analysis_data.py)
