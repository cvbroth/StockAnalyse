# 基本面分析公式汇总

基本面分为两部分：Python根据已公开财务观测值计算“盈利动量”和“经营质量”；
OpenClaw或其他外部研究工具只提供“行业景气”“预期变化”和“风险”。Python最后
校验、合并、否决并排名。基本面分不会与技术分直接相加。

## 1. 输入与时间边界

当前财务提供者把同花顺财务摘要标准化为长表观测值，东方财富只用于补充准确公告
日期。常用标准字段：

| 财务含义 | 标准字段 |
|---|---|
| 营业收入 | `revenue` |
| 归母净利润 | `net_profit` |
| 扣非归母净利润 | `deduct_net_profit` |
| 基本每股收益 | `basic_eps` |
| 毛利率 | `gross_margin` |
| 净利率 | `net_margin` |
| 加权ROE | `roe_weighted` |
| 每股经营现金流 | `operating_cash_flow_per_share` |
| 存货周转天数 | `inventory_turnover_days` |
| 应收账款周转天数 | `receivables_turnover_days` |
| 资产负债率 | `debt_to_assets` |

比例全部标准化为小数，例如20%保存为 `0.20`。金额和每股值不参与跨股票绝对规模
比较，主要使用增长、利润质量和效率。

真实公告日期存在时：

```text
available_at = published_date + 1个自然日
```

没有公告日期时采用保守最晚披露日，并同样从下一自然日才允许使用：

| 报告期 | 保守发布日期 |
|---|---|
| 3月31日 | 当年4月30日 |
| 6月30日 | 当年8月31日 |
| 9月30日 | 当年10月31日 |
| 12月31日 | 次年4月30日 |

只有 `available_at <= as_of_date` 的观测值可以进入分析，避免历史回测偷看未来财报。

## 2. 通用归一函数

### 2.1 越高越好

```text
rising(x; low, high)
  = clip((x-low)/(high-low), 0, 1)
```

### 2.2 越低越好

```text
falling(x; full, zero)
  = 1 - rising(x; full, zero)
```

### 2.3 缺失项重分配

设可用组件归一分为 `s_i`，配置权重为 `w_i`：

```text
group_score = 100 × Σ(s_i × w_i) / Σ(w_i)，仅对可用项求和
```

因此缺失指标不会被直接当成0分；其权重会在其他可用项之间重新分配。同时系统另行
计算数据覆盖率，防止少量指标得到的高分冒充完整结论。

## 3. 增长与趋势

优先使用单季度同比；缺失时才使用累计同比：

```text
revenue_yoy = latest(revenue_single_quarter_yoy, revenue_yoy)
profit_yoy  = latest(net_profit_single_quarter_yoy, net_profit_yoy)
deduct_yoy  = latest(deduct_net_profit_single_quarter_yoy,
                     deduct_net_profit_yoy)
```

同比加速度是最新一期与前一期同比之差：

```text
acceleration = yoy_latest - yoy_previous
```

最近趋势最多使用最近4个季度，当前实现是端点平均变化，不是线性回归：

```text
trend = (value_latest - value_first) / (n - 1)
```

效率指标使用相对趋势：

```text
relative_trend
  = (value_latest - value_first) / abs(value_first)
```

当期数不足2或首值接近0时，趋势不可用。

## 4. 盈利动量分

各组件先归一到0至1，再按下表加权。完整权重合计100。

| 组件 | 原始指标 | 0分点 | 满分点 | 权重 |
|---|---|---:|---:|---:|
| 收入增长 | 最新营收同比 | -10% | 30% | 20 |
| 收入加速度 | 最新同比－前期同比 | -15% | 15% | 15 |
| 利润增长 | 最新归母净利同比 | -20% | 50% | 25 |
| 利润加速度 | 最新同比－前期同比 | -25% | 25% | 20 |
| 扣非利润增长 | 最新扣非净利同比 | -20% | 50% | 10 |
| 扣非利润加速度 | 最新同比－前期同比 | -25% | 25% | 10 |

公式：

```text
earnings_momentum
  = weighted_available_score(上述6项)
```

例如营收同比10%的收入增长子项：

```text
rising(0.10; -0.10, 0.30) = 0.50
```

它在所有指标完整时贡献 `0.50 × 20 = 10` 分。

## 5. 经营质量派生指标

### 5.1 现金利润支撑

```text
cash_profit_support
  = 每股经营现金流 / 基本每股收益
```

只有EPS大于0时计算；EPS为0或负数时该项记为缺失，而不是强行除法。

### 5.2 ROE年化

最新报告期加权ROE按月份年化：

```text
3月：ROE × 4
6月：ROE × 2
9月：ROE × 4/3
12月：ROE × 1
```

这是简单年化，用于统一季度尺度，不代表未来实际全年ROE。

### 5.3 利润率和效率趋势

```text
gross_margin_trend = 最近最多4期毛利率的端点平均变化
net_margin_trend   = 最近最多4期净利率的端点平均变化
inventory_days_relative_trend = 最近最多4期存货天数相对变化
receivables_days_relative_trend = 最近最多4期应收天数相对变化
```

周转天数下降代表效率改善，所以后两项使用“越低越好”函数。

## 6. 经营质量分

| 组件 | 归一公式 | 满分/0分点 | 权重 |
|---|---|---|---:|
| 现金利润支撑 | `rising(cash_profit_support; 0, 1.25)` | 1.25满分 | 25 |
| 毛利率趋势 | `rising(trend; -0.01, 0.01)` | 每季-1%至+1% | 15 |
| 净利率趋势 | `rising(trend; -0.01, 0.01)` | 每季-1%至+1% | 15 |
| ROE水平 | `rising(annualized_roe; 0, 0.20)` | 年化20%满分 | 20 |
| 存货效率 | `falling(relative_trend; -0.20, 0.20)` | 下降20%满分，上升20%为0 | 10 |
| 应收效率 | `falling(relative_trend; -0.20, 0.20)` | 下降20%满分，上升20%为0 | 10 |
| 负债水平 | `falling(debt_ratio; 0.30, 0.85)` | 30%满分，85%为0 | 5 |

```text
business_quality
  = weighted_available_score(上述7项)
```

这是通用启发式评分，不区分银行、券商等高杠杆行业。调试特殊行业时应先检查指标
适用性，不要仅凭该分数否决公司。

## 7. 数据覆盖率与财务状态

覆盖率检查11个必需指标：营收增长、利润增长、扣非利润增长、毛利率、净利率、
ROE、每股经营现金流、EPS、存货周转天数、应收周转天数、资产负债率。

```text
data_coverage = 可用必需指标数 / 11
```

财务量化状态：

| 条件 | status |
|---|---|
| 覆盖率至少80%，且可用报告期至少6期 | `complete` |
| 覆盖率至少50%，且可用报告期至少4期 | `partial` |
| 其他 | `insufficient` |

基本面方向：

```text
若 status=insufficient 或盈利动量缺失：UNCERTAIN
否则若 盈利动量 >= 65 且（经营质量缺失或 >=45）：IMPROVING
否则若 盈利动量 <= 35：DETERIORATING
否则：STABLE
```

## 8. 外部研究三项分

外部研究不能重算前两项，只能提供：

- `industry_cycle`：行业价格、需求、产能利用率、订单与库存的方向，0至100；
- `expectation_delta`：未来3至12个月盈利路径相对既有预期的变化，0至100；
- `risk`：越高越差，0至100。

行业与预期分数参考区间：

| 分数 | 含义 |
|---:|---|
| 80至100 | 强改善 |
| 60至79 | 中度改善 |
| 40至59 | 中性或混合 |
| 20至39 | 走弱 |
| 0至19 | 明显恶化 |

风险等级使用独立区间：LOW 0至29、MEDIUM 30至59、HIGH 60至79、RED 80至100。
定性评分必须有截至 `as_of_date` 的可追溯证据；证据不足时应输出 `partial`，而不是
猜一个精确分数。

## 9. Layer3正向分与风险扣分

默认正向权重合计85：

```text
positive_score
  = (25×盈利动量
   + 20×经营质量
   + 15×行业景气
   + 25×预期变化) / 85
```

只有四项全部存在时才计算正向分。

风险最高扣15分：

```text
risk_penalty = risk_score × 15 / 100
final_score  = max(0, positive_score - risk_penalty)
```

例如正向分80、风险分40：

```text
risk_penalty = 40 × 15 / 100 = 6
final_score = 80 - 6 = 74
```

最终分只在结果状态为 `complete` 或 `rejected` 且正向分可计算时产生。被否决股票
可能保留最终分用于解释，但绝不进入排名。

## 10. Layer3状态判定

按以下优先级：

1. 外部研究明确提供任意 `vetoes`：`rejected`；
2. `risk_level=RED`：自动增加否决理由并 `rejected`；
3. 完整研究的风险分达到 `red_risk_threshold=80`：`rejected`；
4. 研究执行失败：`failed`；
5. 财务量化不是 `complete`：`partial`；
6. 研究不是 `complete` 或五项分数有缺失：`partial`；
7. 研究可信度低于0.60：`partial`；
8. 其他：`complete`。

没有研究结果时：

```text
status = pending
focus_status = PENDING_RESEARCH
final_score = null
```

系统不会用0分代替缺失研究。

## 11. 综合可信度

```text
confidence = (财务数据覆盖率 + 研究可信度) / 2
```

如果财务覆盖率不存在，则只使用研究可信度。这里的综合可信度用于结果解释和同分
排序；是否能成为 `complete` 仍要求财务状态完整且研究可信度至少0.60。

## 12. 关注状态

```text
若 rejected：REJECTED
否则若不是complete或没有最终分：PENDING_REVIEW
否则若 final_score >= 75 且基本面方向=IMPROVING：KEY_FOCUS
否则若 final_score >= 60：FOLLOW_UP
否则：WATCH
```

`KEY_FOCUS` 是研究优先级，不是买入信号。

## 13. 排名

只有 `status=complete` 且有最终分的股票参加排名：

```text
第一排序键：final_score，降序
第二排序键：confidence，降序
```

`rejected`、`partial`、`failed`、`pending` 均保留在输出中，但 `rank=null`。

## 14. 证据契约

完整研究至少要求：

- 行业、预期和风险三项0至100分；
- 五个固定信号全部为布尔值；
- 至少一项风险；
- 至少一条可追溯证据；
- `why_now`、行业、预期和风险摘要均非空；
- 证据发布日期不晚于运行截止日；
- `run_id`、股票代码和 `input_hash` 与请求完全一致。

证据等级：交易所公告和财报为1级；公司、协会和政府数据为2级；券商研究和专业
财经媒体为3级；普通媒体和网络讨论为4级。4级证据不能单独支撑关键分数、催化、
否决或RED风险。

## 15. 调试定位顺序

1. 检查 `request.json` 中候选与截止日期；
2. 检查 `sync_summary.json` 的抓取、缓存和失败数量；
3. 检查 `financial_quant.json` 的 `missing_metrics`、覆盖率和组件贡献；
4. 确认证据的 `published_date <= as_of_date`；
5. 检查研究 `status`、三项分、可信度、五个signals和风险列表；
6. 查看 `research/execution_summary.json` 的逐股校验错误；
7. 查看 `layer3.json` 的否决理由、风险扣分和最终状态；
8. 调权重时复用同一运行和同一研究结果，避免输入变化干扰对比。
