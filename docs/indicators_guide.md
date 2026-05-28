# 金融分析指标全景指南

> **用途**：作为本项目"应该拉/计算哪些指标"的总目录。现有 [`tools/dump_universe_snapshot.py`](../tools/dump_universe_snapshot.py) 只覆盖盘口 + 多窗口收益（现价/当日%/IOPV/溢价%/5日%/1月%/3月%/6月%/1年%/成交额/量比），距离一份完整的金融分析数据仍有较大空白。本文档列出未来需要补充的指标体系，每项标注 **定义 / 默认参数 / 数据来源 / 解读阈值 / 优先级**，便于后续按 phase 推进。
>
> **优先级约定**：
> - **P0**：金融分析的"必备最小集"，下一轮快照应覆盖
> - **P1**：常用辅助，加上后能显著提升判断质量
> - **P2**：进阶/专题，按需启用（如轮动策略、跨境套利）
>
> **数据来源约定**：所有"akshare 接口"均需配合 [`data_sources.md`](data_sources.md) 中记录的稳定性兜底；本项目首选稳定接口为 Sina 实时盘口 + `fund_etf_hist_sina` 历史日 K + `fund_etf_spot_em` 全市场快照。

---

## 速查表（按类别 × 优先级）

| 类别 | P0 必备 | P1 推荐 | P2 进阶 |
|---|---|---|---|
| 价格与极值 | OHLC、52周高低、距高低回撤 | 52周高低分位、新高/新低标记 | 缺口、影线/实体长度 |
| 均线系统 | MA5/10/20/60/120/250、多空排列 | EMA12/26、价格相对均线偏离 | 均线斜率、HMA、Ichimoku 云图 |
| 趋势/动量 | MACD(12,26,9)、RSI(14) | KDJ(9,3,3)、ROC(10)、CCI(14) | DMI/ADX、Williams %R、TRIX、Parabolic SAR |
| 波动率 | 年化波动率(20/60日)、ATR(14)、布林带(20,2) | 历史波动分位、%B、Keltner 通道 | GARCH、Parkinson 波动率 |
| 风险调整收益 | 最大回撤(1年)、夏普比率(1年) | 索提诺比率、卡玛比率、回撤恢复天数 | 信息比率、特雷诺比率、VaR/CVaR |
| 成交量 | 成交量均线(5/20)、换手率、VWAP | OBV、MFI(14)、量价背离标记 | Chaikin Money Flow、Klinger |
| 资金流 | 主力净流入(当日/5日/20日) | 北向资金净买入(指数级)、ETF 份额变化 | 大单/中单/小单细分、龙虎榜 |
| 相对强度 | 相对沪深300强度(RS)、板块内排名 | β 系数、与基准相关系数 | 板块轮动得分、动量打分 |
| 跨境特征 | IOPV、溢价率、溢价历史 1 年分位 | 海外标的当日收盘、汇率 | 折溢价均值回归 z-score |
| 估值（个股/指数级） | PE-TTM、PB、股息率 | 估值 5 年/10 年分位 | PEG、EV/EBITDA |
| 市场情绪 | 全市场涨跌家数、涨停/跌停数 | 北向资金、两融余额 | 期权 PCR、波动率指数 |

---

## 一、价格与极值

| 指标 | 公式/口径 | 默认参数 | 数据来源 | 解读 |
|---|---|---|---|---|
| OHLC | 当日开/高/低/收 | — | `fund_etf_hist_sina` 已含 | 形态判断基础 |
| 振幅 | (high - low) / prev_close × 100 | 当日 | 本地计算 | >5% 视为大波动日 |
| 52 周最高/最低 | 近 250 交易日收盘最大/最小 | 250 日 | 历史日 K 切片 | 锚点 |
| 距 52 周高回撤 | (52w_high - close) / 52w_high × 100 | — | 本地计算 | >20% 进入熊市区间 |
| 距 52 周低反弹 | (close - 52w_low) / 52w_low × 100 | — | 本地计算 | 配合趋势判断底部确认 |
| 近 3 月 / 6 月最高低 | 滚动窗口极值 | 60 / 120 日 | 本地计算 | 阶段性压力/支撑 |
| 突破/新高新低标记 | close > 252日 high / close < 252日 low | bool | 本地计算 | 突破信号 |
| 缺口 | 当日 open vs 前一日 close 偏离 ≥ 1% | — | 本地计算 (P2) | 缺口未回补意味强势/弱势 |

---

## 二、均线系统

### 2.1 简单与指数移动均线

| 指标 | 公式 | 默认周期 | 数据来源 | 用途 |
|---|---|---|---|---|
| SMA(n) | 近 n 日收盘均值 | 5/10/20/60/120/250 | 本地 `pandas.rolling().mean()` | 趋势骨架 |
| EMA(n) | 指数加权 | 12 / 26 / 60 | 本地 `pandas.ewm(span=n)` | 反应更敏感，MACD 基础 |
| WMA(n) | 线性加权 | 10 / 20 | 本地计算 (P2) | 应对 SMA 滞后 |
| HMA(n) | Hull MA | 9 / 16 | 本地计算 (P2) | 平滑且低滞后 |

### 2.2 均线衍生量

| 指标 | 口径 | 解读 |
|---|---|---|
| 多空排列 | MA5 > MA10 > MA20 > MA60 (>) 看多 | 多头排列 = 趋势强 |
| 价格相对 MA 偏离% | (close - MA_n) / MA_n × 100 | 偏离过大易回归 |
| 均线斜率 | (MA_today - MA_n_ago) / MA_n_ago | 正斜率=上行 |
| 金叉/死叉 | MA(short) 上穿/下穿 MA(long) | 经典信号 |
| 价格在 MA 上方天数占比 | 近 n 日 close > MA_n 的天数 / n | 趋势持续度 |

---

## 三、趋势 / 动量类

| 指标 | 公式（要点） | 默认参数 | 解读阈值 | 优先级 |
|---|---|---|---|---|
| **MACD** | DIF = EMA12 - EMA26; DEA = EMA9(DIF); MACD柱 = 2×(DIF-DEA) | (12,26,9) | DIF 上穿 DEA = 买入；柱状由负转正 = 动量回升 | P0 |
| **RSI** | 100 - 100/(1+RS), RS = 平均涨幅/平均跌幅 | 14 (兼 6 / 24) | <30 超卖, >70 超买；50 为多空分界 | P0 |
| **KDJ** | RSV → K (3日 EMA) → D (3日 EMA) → J = 3K-2D | (9,3,3) | K<20 超卖, K>80 超买；J 突破 0/100 极端值 | P1 |
| **CCI** | (TP - SMA(TP,n)) / (0.015 × MD) | 14 | >+100 强势, <-100 弱势 | P1 |
| **ROC** | (close_t / close_{t-n} - 1) × 100 | 10 | 与零轴对照判断动量方向 | P1 |
| **DMI/ADX** | +DI / -DI 方向；ADX 强度 | 14 | ADX>25 趋势明显, <20 震荡 | P2 |
| **Williams %R** | (high_n - close)/(high_n - low_n) × -100 | 14 | <-80 超卖, >-20 超买 | P2 |
| **TRIX** | 三重 EMA 平滑后变化率 | 12 | 反趋势能力强 | P2 |
| **Parabolic SAR** | Wilder 抛物线转向 | 0.02 步长 | 紧跟趋势, 价格跌破 SAR = 转空 | P2 |

> **常用组合**：MACD 定方向 → RSI/KDJ 找入场点 → ATR 设仓位与止损。

---

## 四、波动率 / 风险

| 指标 | 公式 / 口径 | 默认参数 | 用途 | 优先级 |
|---|---|---|---|---|
| 日收益标准差 σ | std(log return) | 20 / 60 日 | 波动尺度 | P0 |
| 年化波动率 | σ × √252 | 20 / 60 日 → 年化 | 比较跨资产波动 | P0 |
| ATR(n) | 平均真实波幅，max(H-L, |H-prevC|, |L-prevC|) 的 n 日均值 | 14 | 止损/仓位（ATR 倍数法） | P0 |
| 布林带 | MA(20) ± 2σ | (20, 2) | 突破/均值回归 | P0 |
| %B | (close - lower) / (upper - lower) | 与布林带配套 | 位置打分 (0-1) | P1 |
| 布林带宽度 | (upper - lower) / MA | — | 收口=蓄势, 张口=破位 | P1 |
| Keltner 通道 | EMA ± k × ATR | (20, 2) | ATR 版布林带 | P2 |
| 历史波动分位 | 当前年化波动率在近 N 年的分位 | 252 / 1260 日 | 极端值识别 | P1 |
| 下行波动率 | 仅取负收益的 std | 60 日 | Sortino 分母 | P1 |
| Parkinson / GK 波动率 | 用 OHLC 估算 | 20 日 | 比 close-to-close 更有效 | P2 |

---

## 五、风险调整收益

| 指标 | 公式 | 默认参数 | 解读 | 优先级 |
|---|---|---|---|---|
| 最大回撤 MDD | (1 - close / 累计 max close) 的最大值 | 1 年 / 3 年 | 极端损失测量 | P0 |
| 回撤恢复天数 | 从回撤底部回到前高的交易日数 | 1 年 | 韧性 | P1 |
| 当前回撤 | 1 - close / 历史 max close | 1 年 / 全期 | 实时风险位置 | P0 |
| 夏普比率 | (年化收益 - rf) / 年化波动 | 1 年, rf=2% | >1 优秀, >2 卓越 | P0 |
| 索提诺比率 | (年化收益 - rf) / 下行波动 | 1 年 | 仅惩罚下跌 | P1 |
| 卡玛比率 | 年化收益 / 最大回撤 | 1 年 / 3 年 | 抗回撤能力 | P1 |
| 信息比率 IR | (组合收益 - 基准收益) / 跟踪误差 | vs 沪深 300 | 主动收益 | P2 |
| 特雷诺比率 | (年化收益 - rf) / β | 1 年 | 系统风险下的回报 | P2 |
| VaR (95% / 99%) | 给定置信度下的最大可能日损失 | 历史模拟法 | 风险预算 | P2 |
| CVaR (Expected Shortfall) | 超过 VaR 的平均损失 | — | 尾部风险 | P2 |

> **rf 取值**：本项目默认 2% 年化（≈ 1 年国债收益率），可按当期 10 年期国债收益率定期更新。

---

## 六、成交量类

| 指标 | 口径 | 默认参数 | 解读 | 优先级 |
|---|---|---|---|---|
| 成交量均线 VMA | rolling mean(volume) | 5 / 20 / 60 | 量能基线 | P0 |
| 量比 | 当日成交量 / 近 5 日同时段均量 | 已有于 spot | >1.5 异常放量 | P0 |
| 换手率 | 成交量 / 流通份额 | 当日 | ETF 流动性核心指标 | P0 |
| VWAP | Σ(price×vol) / Σ(vol) | 日内 | 机构成本基准 | P0 |
| OBV | 累积「上涨日加 vol, 下跌日减 vol」 | 全期 | 量价背离=反转预警 | P1 |
| MFI | 资金流量 × 类 RSI 公式 | 14 | <20 超卖, >80 超买 | P1 |
| Chaikin Money Flow | (close - low - (high - close))/(high - low) × vol | 20 | 量价综合判断 | P2 |
| 量价背离标记 | 价创新高 vs 量未跟上（bool） | 60 日窗口 | 预警 | P1 |

> **对 ETF 的特殊性**：ETF 的"换手率"分母是流通份额而非市值，AKShare `fund_etf_spot_em` 已含。份额变化（净申购/赎回）见下节。

---

## 七、资金流 / 申赎类

| 指标 | 口径 | 来源接口 | 解读 | 优先级 |
|---|---|---|---|---|
| 主力净流入（个股） | 大单+超大单净额 | `ak.stock_individual_fund_flow` | 当日 + 5/20 日累计 | P0（对个股）|
| 板块资金流排名 | 行业资金流 | `ak.stock_sector_fund_flow_rank` | 板块轮动信号 | P1 |
| 板块历史资金流 | 行业资金流时序 | `ak.stock_sector_fund_flow_hist` | 趋势 | P1 |
| 北向资金净买入 | 沪股通+深股通 | `ak.stock_hsgt_*` 系列 | 外资风向 | P1 |
| 融资融券余额 | 两融数据 | `ak.stock_margin_*` | 杠杆资金情绪 | P2 |
| ETF 份额变化 | 当日总份额 vs 前一日 | `ak.fund_etf_fund_info_em` / `ak.fund_etf_category_sina` | 净申购=资金净流入 | P1 |
| 大/中/小单细分 | 超大/大/中/小单分档 | `ak.stock_individual_fund_flow` | 散户 vs 机构判断 | P2 |
| 龙虎榜 | 当日上榜资金 | `ak.stock_lhb_detail_em` | 异常资金 | P2（仅事件触发）|

> ETF 的"主力净流入"严格意义上不存在（ETF 是集合工具），可用份额变化代理，或者拆解到成分股做加权。

---

## 八、相对强度与板块对比

| 指标 | 口径 | 默认参数 | 用途 | 优先级 |
|---|---|---|---|---|
| 相对强度 RS | ETF 收益 / 沪深 300 收益（同期） | 1 / 3 / 6 月 | 板块强弱 | P0 |
| 板块内 RS 排名 | 同类别 ETF 收益分位 | 1 / 3 月 | 替代品选择 | P0 |
| Beta(β) | cov(ETF, 基准)/var(基准) | 60 / 250 日 | 系统风险敞口 | P1 |
| 与基准相关系数 ρ | corr(ETF, 沪深300) | 60 日 | 分散化效果 | P1 |
| 跟踪误差 TE | std(ETF return - benchmark return) × √252 | 60 日 | 被动管理质量 | P1 |
| 动量打分 | 各窗口收益分位加权平均 | (1/3/6 月) | 多 ETF 排序 | P1 |
| 板块轮动得分 | 短期 + 中期 RS 加权 | — | 选板块 | P2 |

> 基准默认 **沪深 300（510300）**；港股可用 **恒生指数（159920）**，美股可用 **标普 500（513500）**。

---

## 九、跨境 ETF 特有

| 指标 | 口径 | 数据来源 | 解读 | 优先级 |
|---|---|---|---|---|
| IOPV | 实时净值估算 | `fund_etf_spot_em`（已有） | — | P0 |
| 溢价率 | (price - IOPV)/IOPV × 100 | 本地（已有） | — | P0 |
| 溢价率历史 1 年分位 | 当前溢价在近 250 日的分位 | 需累积溢价历史 | >90% 严重高估 | **P0**（重要！）|
| 溢价均值与标准差 | rolling 60 / 250 日 | 本地累积 | 均值回归边界 | P1 |
| 溢价 z-score | (当前 - 均值) / std | 250 日 | >+2σ 警戒 | P1 |
| 海外标的当日收盘 | 对应指数收盘 | yfinance / akshare 海外接口 | 解释 IOPV 的滞后 | P1 |
| 汇率（USD/CNH, HKD/CNH） | 当日中间价 | `ak.fx_*` 系列 | 调整海外收益 | P1 |
| 折溢价均值回归预期 | 当前位置 vs 1 年均值 | 本地 | 套利窗口 | P2 |

> 跨境 ETF 是本项目核心持仓（513130/513050/159941），溢价 z-score 应作为下一阶段必备字段。memory `feedback_qdii_premium` 指出 QDII 存在结构性下限 ~5%，**不能简单认为溢价会归零**——所有溢价指标的历史基准要至少 1 年。

---

## 十、估值类（对个股 / 指数级 ETF）

| 指标 | 口径 | 来源 | 适用 | 优先级 |
|---|---|---|---|---|
| PE-TTM | 最近 12 个月滚动 EPS | `ak.stock_index_pe_lg(symbol='沪深300')` （✅ 实测可用,5134 行 5 年序列）| 宽基/行业指数 | P0 |
| PB（市净率） | close / 每股净资产 | `ak.stock_index_pb_lg(symbol='沪深300')` （✅ 实测可用）| 价值类 / 银行 / 红利 | P0 |
| PS（市销率） | close / 每股营收 | `ak.stock_value_em` | 科技 / 成长 | P1 |
| 股息率 | 近 12 月分红 / close | 同上 | 红利类 | P0 |
| PEG | PE / 利润增长率 | 个股财务 + PE | 成长股估值 | P1 |
| 估值 5 / 10 年分位 | 当前 PE/PB 在 5 / 10 年的分位 | 历史 PE 序列本地排名（`index_value_hist_funddb` 在 1.18.63 已下线）| 高低估判断 | P0 |
| EV/EBITDA | 企业价值 / EBITDA | 财务接口 | 资本结构敏感行业 | P2 |
| ROE | 净利润 / 净资产 | 财务接口 | 质量因子 | P1 |
| 行业 PE/PB 中位数 | 同行业横截面 | `ak.stock_industry_pe_*` | 相对估值 | P1 |

> ETF 层面的估值需要"穿透到成分股"再加权，本项目目前不做穿透估值——以指数级 PE/PB 为主（适用宽基与行业 ETF）。

---

## 十一、市场整体情绪

| 指标 | 口径 | 来源 | 优先级 |
|---|---|---|---|
| A 股涨跌家数 | 全市场上涨 / 下跌 / 平 家数 | `ak.stock_market_activity_legu` | P1 |
| 涨停 / 跌停数量 | 当日涨跌停统计 | `ak.stock_zt_pool_em` / `ak.stock_zt_pool_previous_em` | P1 |
| 北向资金净流入（汇总） | 沪股通 + 深股通 | `ak.stock_hsgt_fund_flow_summary_em` （`stock_hsgt_north_net_flow_in` 在 akshare 1.18.63 已下线） | P1 |
| 两融余额 | 融资 + 融券 | `ak.stock_margin_underlying_info_szse` 等 | P2 |
| 上证 / 创业板换手率 | 全市场层面 | `ak.stock_market_pe_lg` 等 | P1 |
| 期权 PCR | put/call 比 | `ak.option_*` | P2 |
| 隐含波动率（300ETF 期权） | IV | `ak.option_finance_minute_sina` | P2 |
| 风险溢价（股债比） | (1/PE) - 10年国债 | 本地计算 | P1 |

---

## 十二、数据接口映射（2026-05-28 实测验证）

> 状态图例：✅ 实测可用 / ❌ 实测失败 / ⚠️ akshare 1.18.63 已下线 / 🔵 待专项验证。

| 类别 | akshare 接口 | 状态 | 实测结果 / 备注 |
|---|---|---|---|
| ETF 实时盘口 + IOPV + 资金流 + 份额 | `fund_etf_spot_em` | ✅ | **本次发现** 共 37 列,含 OHLC/振幅/换手率/委比/主力 + 超大单 + 大单 + 中单 + 小单净流入 + 最新份额 + 流通市值 + 基金折价率,远超之前的 12 列使用面 |
| ETF 历史日 K | `fund_etf_hist_sina` | ✅ | 一次返回全期 OHLCV,所有技术指标的输入 |
| ETF 单位净值 / 申购赎回状态 | `fund_etf_fund_info_em(fund=, start_date=, end_date=)` | ✅ | 含 单位净值/累计净值/日增长率/申购状态/赎回状态 |
| ETF 分类全表 | `fund_etf_category_sina(symbol='ETF基金')` | ✅ | 1535 行,可作为代码核验 |
| ETF 分钟级 K | `fund_etf_hist_min_em` | ❌ | `ConnectionError`（push2.eastmoney 系) |
| ETF 申赎名单/成分(PCF) | `fund_etf_pcf_em` | 🔵 | 待验证；穿透估值用 |
| 个股资金流（当日） | `stock_individual_fund_flow_rank` | ❌ | `ConnectionError`,EM push2 系全线挂掉 |
| 个股资金流（历史） | `stock_individual_fund_flow` | ❌ | 同上 |
| 板块资金流排名 | `stock_sector_fund_flow_rank` | ❌ | 同上 |
| 板块历史资金流 | `stock_sector_fund_flow_hist` | ❌ | 同上 |
| 北向资金累计净流入 | `stock_hsgt_north_net_flow_in` | ⚠️ | akshare 1.18.63 已下线 |
| 北向资金汇总 | `stock_hsgt_fund_flow_summary_em` | ✅ | 4 行（沪股通/深股通/北上/南下），含 成交净买额 / 资金净流入 |
| 指数 PE-TTM | `stock_index_pe_lg(symbol='沪深300')` | ✅ | 5134 行,可计算 5/10 年分位 |
| 指数 PB | `stock_index_pb_lg(symbol='沪深300')` | ✅ | 5134 行 |
| 指数估值历史(funddb) | `index_value_hist_funddb` | ⚠️ | akshare 1.18.63 已下线,用 `pe_lg`/`pb_lg` 替代 |
| 涨停池 | `stock_zt_pool_em(date='YYYYMMDD')` | ✅ | 当日涨停家数(本次 47 只真实涨停) |
| 市场情绪/活跃度 | `stock_market_activity_legu` | ✅ | 12 项,含 上涨/下跌/真实涨跌停/平盘/停牌/活跃度% |
| 上交所两融 | `stock_margin_sse(start_date=, end_date=)` | ✅ | 含 融资余额/融券余额/总额 |
| 50ETF 期权 | `option_finance_board(symbol='50ETF', end_month='2606')` | 🔵 | 本次返回空,需调整到期月份再试 |

**总结**：
- **🟢 直拉可用**：6 个稳定接口覆盖了"价格盘口 + ETF 资金流 + 估值 + 市场情绪 + 北向 + 两融"。最大单点 = `fund_etf_spot_em`,一次返回 ETF 全部当日"原子量"
- **❌ 全部失败**：`push2.eastmoney.com` 系（个股 / 板块 / 资金流 / 分钟）。本项目网络环境无法用这些接口,需找到不同的供应商
- **重要发现**：`fund_etf_spot_em` 已经直接带"主力 + 超大单 + 大单 + 中单 + 小单 净流入额 + 净占比"——之前以为 ETF 没有资金流细分实际是误判,原版脚本只是没去读这些列

---

## 十二·5、实测：指标 → 来源完整映射

> 这张表对应本指南第一节速查表的每一项指标,2026-05-28 在 109 只 ETF 全清单上实跑后回填。
> - **🟢 直拉**：单接口返回即可,无需后处理
> - **🟡 自算**：需要 OHLCV 原始历史 + pandas/numpy 计算,实现见 [`tools/indicators.py`](../tools/indicators.py)
> - **🔴 暂不可用**：接口失败 / 已下线 / 需要本项目尚未集成的数据源

### 12.5.1 直拉项（fund_etf_spot_em 一次性带出）

| 指标 | 列名（spot 表）| 备注 |
|---|---|---|
| 现价 / 昨收 / 今开 / 今高 / 今低 | 最新价 / 昨收 / 开盘价 / 最高价 / 最低价 | — |
| 当日涨跌% | 涨跌幅 | 含正负号 |
| 振幅% / 换手率% / 量比 / 委比% | 振幅 / 换手率 / 量比 / 委比 | — |
| 成交额 / 成交量 / 外盘 / 内盘 / 现手 / 买一/卖一 | 同名 | — |
| 主力 / 超大单 / 大单 / 中单 / 小单 净流入额 + 净占比 | 主力净流入-净额 / -净占比 等共 10 列 | **本次新启用** |
| 最新份额 | 最新份额 | 单日份额 |
| 流通市值 / 总市值 | 同名 | — |
| IOPV / 基金折价率 | IOPV实时估值 / 基金折价率 | 跨境必备 |

### 12.5.2 直拉项（其他稳定接口）

| 指标 | 接口 | 备注 |
|---|---|---|
| ETF 单位净值 / 日增长率 / 申购赎回状态 | `fund_etf_fund_info_em` | 按单 fund + 日期窗口 |
| 沪深 300 PE-TTM / PB | `stock_index_pe_lg` / `stock_index_pb_lg` | 历史 5000+ 行 |
| 全市场涨跌家数 / 活跃度% | `stock_market_activity_legu` | 12 项 |
| 涨停池家数 | `stock_zt_pool_em(date=YYYYMMDD)` | 当日 |
| 北向资金汇总 | `stock_hsgt_fund_flow_summary_em` | 沪股通+深股通+南下 |
| 上交所两融余额 | `stock_margin_sse` | 含融资/融券 |

### 12.5.3 自算项（输入：Sina 历史日 K）

实现已落地在 [`tools/indicators.py`](../tools/indicators.py),输出在 [`tools/dump_full_snapshot.py`](../tools/dump_full_snapshot.py) 的 §2.4-2.11 表。

| 类别 | 指标 | 函数 |
|---|---|---|
| 价格极值 | 52w 高/低、距离、3/6 月高低、新高新低 bool、当日振幅 | `price_extremes` |
| 多窗口收益 | 5d / 1m / 3m / 6m / 1y | `pct_window` |
| 均线 | MA 5/10/20/60/120/250、相对偏离%、斜率、多空排列、5/20 金死叉、60d 在 MA20 上方占比 | `moving_averages` |
| 趋势 | MACD(12,26,9) + 交叉标记 | `macd` |
| 动量 | RSI(14/6)、KDJ(9,3,3)、CCI(14)、ROC(10)、Williams %R(14) | `rsi/kdj/cci/roc/williams_r` |
| 波动率 | 年化波动 20d/60d、1 年波动分位、下行波动 60d、ATR(14)、布林(20,2) + %B + 带宽% | `volatility/atr/bollinger` |
| 风险调整 | 最大回撤 1y、当前回撤、恢复天数、Sharpe / Sortino / Calmar 1y | `drawdown_metrics/risk_adjusted` |
| 成交量 | VMA 5/20/60、OBV、OBV 斜率 20d、MFI(14) | `volume_metrics` |
| 相对强度 | vs 沪深 300 RS 1/3/6m、β 60d、ρ 60d、跟踪误差 60d | `relative_strength` |
| 跨境 | 溢价% = (现价 - IOPV)/IOPV × 100 | `compute_all` 内联 |
| 指数估值分位 | PE/PB 5 年分位 | `fetch_market_global` 内联 |

### 12.5.4 暂不可用项

| 指标 | 原因 | 替代/对策 |
|---|---|---|
| 个股主力资金流（历史/排名） | EM `push2` 在本网络全挂 | **对 ETF 直接用 spot 的资金流列即可**；个股主力流向需另找供应商或在不同网络环境下重试 |
| 板块资金流排名 / 历史 | 同上 | 暂无替代,等 EM 系恢复或换源 |
| ETF 分钟级 K | `fund_etf_hist_min_em` 同样 EM 挂 | 用 Sina 分时（个股已实测可用,ETF 待验证）|
| 跨境溢价历史分位 / z-score | spot 仅当前 IOPV 无历史 | **本地累积**：每日跑一次 `dump_full_snapshot.py`,把 IOPV / 溢价存入本地长表,~250 个交易日后即可计算分位 |
| 海外标的当日收盘 | akshare 国外指数接口不稳 | yfinance / `ak.index_global_*` 系列待专项验证 |
| 汇率（USD/CNH、HKD/CNH） | `ak.fx_*` 待验证 | Phase 2 |
| ETF 穿透估值（按成分股加权 PE/PB）| 需要成分股权重 | `fund_etf_pcf_em` 待验证,目前以指数级 PE/PB 替代 |
| 行业 PE / PB 中位 / 股息率 | EM 系挂 | 等接口恢复 |
| 50 ETF 期权 / IV / PCR | `option_finance_board` 返回空 | 调整到期月份再试 |
| 龙虎榜 | 未实测 | 事件触发型,非日常 |

---

## 十三、本地计算指标的实现路径

> 大多数衍生指标只需在拉取完原始 OHLCV 后用 pandas + numpy 本地算，不依赖额外接口。下列建议放入 `stock_info/indicators.py` 或新建 `analysis/factors.py`。

```python
# 推荐栈
pandas / numpy           # 滚动窗口、收益、相关
ta-lib 或 pandas-ta      # 一站式技术指标（MACD/RSI/KDJ/CCI/...）
empyrical                # 风险调整收益（Sharpe/Sortino/Calmar/MDD）
scipy.stats              # 分位、z-score、相关性显著性
```

**最小依赖路线**（不引入 ta-lib，纯 pandas 实现）：

```python
# 5/10/20/60 日 SMA
for w in (5, 10, 20, 60, 120, 250):
    df[f"MA{w}"] = df["close"].rolling(w).mean()

# 年化波动率
returns = df["close"].pct_change()
df["vol_20d_ann"] = returns.rolling(20).std() * (252 ** 0.5)

# 最大回撤
cummax = df["close"].cummax()
df["drawdown"] = df["close"] / cummax - 1

# RSI(14) 简化版
delta = df["close"].diff()
gain = delta.clip(lower=0).rolling(14).mean()
loss = (-delta.clip(upper=0)).rolling(14).mean()
df["rsi14"] = 100 - 100 / (1 + gain / loss)

# MACD
ema12 = df["close"].ewm(span=12).mean()
ema26 = df["close"].ewm(span=26).mean()
df["dif"] = ema12 - ema26
df["dea"] = df["dif"].ewm(span=9).mean()
df["macd"] = 2 * (df["dif"] - df["dea"])

# 布林带
mid = df["close"].rolling(20).mean()
sd = df["close"].rolling(20).std()
df["boll_upper"], df["boll_lower"] = mid + 2 * sd, mid - 2 * sd
df["boll_pctb"] = (df["close"] - df["boll_lower"]) / (df["boll_upper"] - df["boll_lower"])

# 夏普比率（1 年, rf = 2%）
rf_daily = 0.02 / 252
ann_ret = returns.tail(252).mean() * 252
ann_vol = returns.tail(252).std() * (252 ** 0.5)
sharpe = (ann_ret - 0.02) / ann_vol
```

---

## 十四、推进路线建议

| Phase | 范围 | 状态 | 产出 |
|---|---|---|---|
| **Phase 1 — P0 基础扩展** | 价格极值 + 均线 + MACD/RSI + ATR/布林带 + MDD/夏普 + ETF 资金流分档 | ✅ **2026-05-28 完成** | [`tools/dump_full_snapshot.py`](../tools/dump_full_snapshot.py) + [`tools/indicators.py`](../tools/indicators.py),11 张分维度表,109 ETF × 60+ 字段 |
| **Phase 1.5 — 市场宏观快照** | 指数 PE/PB 5 年分位、涨跌家数、涨停池、北向汇总、两融 | ✅ **2026-05-28 完成** | 已并入 `dump_full_snapshot.py` 一节宏观 |
| **Phase 2 — 跨境特化** | 溢价历史分位 + z-score + 海外收盘 + 汇率 | 🟡 待办 | 需先累积每日溢价快照（约 1 个月起效）；汇率接口待验证 |
| **Phase 3 — 板块轮动与排名** | 同类别 ETF 内 RS 排名、动量打分、板块轮动得分 | 🟡 待办 | 横截面比较,Phase 1 已铺垫 RS 数据 |
| **Phase 4 — ETF 穿透估值** | 用 `fund_etf_pcf_em` 拿成分股权重 + 个股 PE/PB → 加权 | 🟡 待办 | EM 个股估值接口当前不稳,需等接口恢复或换源 |
| **Phase 5 — 进阶因子** | DMI/CCI/TRIX、Keltner、信息比率、VaR、量价背离 | 🟡 待办 | 视需要 |

> Phase 1 完成后，快照"决策密度"从 ~12 字段 → 60+ 字段，覆盖技术面 + 风险面 + 资金面 + 跨境特征 + 市场宏观的"日常可决策集"。下一步重点是 Phase 2（跨境溢价历史）——这是本项目核心持仓 513130/513050/159941 的关键风控字段。

---

## 十五、参考资料

- **StockCharts ChartSchool**：[chartschool.stockcharts.com](https://chartschool.stockcharts.com/) 技术指标百科（英文）
- **Britannica - Technical Indicators**：[趋势/动量/波动/成交量四大类划分](https://www.britannica.com/money/technical-indicator-types)
- **TMGM Trading Academy**：[趋势 + 动量 + 波动综合应用](https://www.tmgm.com/en/academy/trading-academy/what-are-technical-indicators)
- **BigQuant - 125 个择时指标研报**：[广发证券 125 个经典技术指标择时分析](https://m.hibor.com.cn/wap_detail.aspx?id=558b49e63d44511a5b16fbb7d9f297a9)
- **WeFreeStar 博客 - MACD/KDJ/RSI/ATR 全景**：[macd-kdj-rsi-atr-indicator-guide](https://blog.wefreestar.com/archives/macd-kdj-rsi-atr-indicator-guide)
- **AKShare 文档**：[akshare.akfamily.xyz](https://akshare.akfamily.xyz/) 数据接口完整目录
- **AKShare 资金流接口知乎汇总**：[AKShare-股票数据-个股资金流](https://zhuanlan.zhihu.com/p/652960826)
- **风险调整收益（夏普 / 最大回撤 / 卡玛）对比**：[CSDN 量化交易入门](https://blog.csdn.net/benshu_001/article/details/137127463)
- **Python 计算年化收益/最大回撤/波动率/夏普比率**：[知乎实战](https://zhuanlan.zhihu.com/p/1890797469069199051)

---

## 十六、更新日志

| 日期 | 变更 | 备注 |
|---|---|---|
| 2026-05-28 | 初版，覆盖 12 大类约 80 项指标 + Phase 推进路线 | 后续按 Phase 1 落地到 `tools/dump_universe_snapshot.py` |
| 2026-05-28 | Phase 1 落地：新增 [`tools/indicators.py`](../tools/indicators.py) + [`tools/dump_full_snapshot.py`](../tools/dump_full_snapshot.py)，109 ETF × 60+ 字段实测产出 [`analysis_history/2026-05-28_002_full_snapshot.md`](../analysis_history/2026-05-28_002_full_snapshot.md) | §12 接口映射更新为实测验证版；新增 §12.5「实测：指标 → 来源完整映射」三段；§14 Phase 路线刷新进度 |
