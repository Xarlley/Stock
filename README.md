# Stock 行情查询

中国大陆 A 股 / ETF 实时与历史行情查询工具。基于 [akshare](https://github.com/akfamily/akshare) + Sina 行情接口。

## 安装

```bash
pip install -r requirements.txt
```

## 使用

```bash
python main.py <代码> [--no-intraday] [--chart-dir DIR] [--years N]
```

代码支持 6 位数字，可带 `sh/sz` 前缀：

| 类型             | 示例代码 | 说明                 |
| ---------------- | -------- | -------------------- |
| 沪市主板         | 600519   | 贵州茅台             |
| 深市主板         | 000001   | 平安银行             |
| 创业板           | 300750   | 宁德时代             |
| 科创板           | 688981   | 中芯国际             |
| 上交所 ETF       | 510300   | 沪深300ETF           |
| 深交所 ETF       | 159915   | 易方达创业板 ETF     |

## 输出

控制台：
- 实时盘口（最新价 / 涨跌幅 / 五档 / 成交 / 估值）
- 4 个窗口统计表：近 3 年、1 年、1 个月、5 日

图表（PNG，默认输出到 `./charts/`）：
- 6 宫格：3 年 / 1 年 / 1 个月 / 5 日日K + 当日 1 分钟分时 + 近 1 年成交量

## 模块结构

```
stock_info/
  classifier.py   # 代码 → (类型, 市场)
  fetcher.py      # 实时 / 历史日K / 日内分时，含 Sina 兜底
  display.py      # 控制台报表 + matplotlib 出图
main.py           # CLI 入口
```

## 数据源

- **实时行情**：股票走 Sina (`hq.sinajs.cn`)，ETF 走 EastMoney（含 IOPV）+ Sina 直连兜底
- **历史日K**：股票/ETF 都是 EastMoney 主 + Sina 兜底
- **日内分时**：股票走 Sina (`stock_zh_a_minute`)；ETF 暂无可靠 1 分钟源

**详细数据获取方法手册**：见 [docs/data_sources.md](docs/data_sources.md) —— 包括每个接口的字段说明、调用示例、失败模式、重试策略，以及「QDII 真假涨 60 秒判别法」等应用案例。
