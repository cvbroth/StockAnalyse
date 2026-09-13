# 技术分析公式汇总

本文记录当前代码真正执行的Layer1资格公式和Layer2质量评分。公式中的价格均为统一
前复权价格，成交量为原始“手”数。默认参数来自 `layer1.toml` 和 `layer2.toml`。

## 1. 符号约定

| 符号 | 含义 |
|---|---|
| `C_t, H_t, L_t, V_t` | 第t个交易日的收盘、最高、最低和成交量 |
| `MA_n(t)` | 截至t日最近n个收盘价的算术平均 |
| `R_n` | n个交易日收益率 |
| `B_n` | 同期沪深300收益率 |
| `ER_n` | 超额收益 `R_n - B_n` |
| `clip(x,0,1)` | 把x限制到0至1 |
| `W` | 某评分项的满分权重 |

交易日收益率使用第 `n+1` 个观测点：

```text
R_n = C_t / C_(t-n) - 1
```

股票与沪深300先按日期做内连接，再取共同交易日窗口，因此不会把错位日期相除。

## 2. 基础过滤

股票进入五项条件前必须同时满足：

```text
支持的A股代码
且 历史行数 >= min_history_days
且 截面日期 - 最新交易日期 <= max_stale_calendar_days
且 最近20日日均成交量 >= min_average_volume_lots
且 名称不含ST（exclude_st=true时）
```

默认最低历史为120日。分析器还要求：

```text
required_rows = max(
    min_history_days,
    breakout_lookback + breakout_search_days,
    71
)
```

默认实际最低为 `max(120, 60+20, 71)=120` 行。

## 3. Layer1：五项资格条件

### 3.1 高低点抬升 `price_structure`

取最近20日窗口和紧邻它之前的20日窗口：

```text
recent_high   = max(H, 最近20日)
previous_high = max(H, 前一段20日)
recent_low    = min(L, 最近20日)
previous_low  = min(L, 前一段20日)

通过 = recent_high > previous_high
   且 recent_low  > previous_low
```

判断使用严格大于；相等不通过。

### 3.2 均线多头 `ma_trend`

```text
MA20_t = mean(C_(t-19) ... C_t)
MA60_t = mean(C_(t-59) ... C_t)

通过 = C_t > MA20_t > MA60_t
   且 MA20_t > MA20_(t-5)
   且 MA60_t > MA60_(t-10)
```

同时保存：

```text
ma20_5d_rise  = MA20_t / MA20_(t-5) - 1
ma60_10d_rise = MA60_t / MA60_(t-10) - 1
```

### 3.3 上涨放量 `volume_price`

最近20个收益观测日按收盘涨跌分组：

```text
change_t = C_t / C_(t-1) - 1
up_mean   = mean(V_t | change_t > 0)
down_mean = mean(V_t | change_t < 0)
volume_ratio = up_mean / down_mean

通过 = volume_ratio > 1.15
```

平盘日不属于任何组。没有上涨日、没有下跌日或下跌日均量不大于0时，比例不可用，
该条件不通过。

### 3.4 放量突破并守住 `breakout_retest`

在最近20个交易位置内逐日寻找事件。对候选日 `d`：

```text
prior_high_d = max(H_(d-60) ... H_(d-1))
prior_avg_volume_d = mean(V_(d-20) ... V_(d-1))

突破事件 = C_d > prior_high_d
       且 V_d > prior_avg_volume_d × 1.30
```

如果找到多个事件，使用最近一个。突破价是此前60日最高价，而不是突破日收盘价：

```text
breakout_price = prior_high_d
support_floor  = breakout_price × (1 - 0.03)
minimum_close  = min(C_d ... C_t)

通过 = minimum_close >= support_floor
```

也就是突破后任何收盘价都不能低于突破位3%以上。最低价影线不会直接触发失败，当前
实现检查的是收盘价。

辅助量能：

```text
post_breakout_volume_ratio
  = mean(突破日之后的成交量) / 突破前20日均量
```

该辅助量能不参与Layer1通过判断，但进入Layer2评分。

### 3.5 相对强度 `relative_strength`

```text
ER20 = 股票20日收益 - 沪深300同期20日收益
ER60 = 股票60日收益 - 沪深300同期60日收益

基准规则通过 = ER20 > 0
           且 股票60日收益 > 沪深300同期60日收益
           且 ER60 > 0.08
```

全市场模式再计算股票自身60日收益在所有有效股票中的百分位。Pandas使用平均秩处理
并列值：

```text
percentile_i = average_rank(R60_i) / 有效样本数

最终通过 = 基准规则通过 且 percentile_i >= 0.70
```

`--symbols` 小样本模式不使用几只测试股票相互排名，百分位设为不可用，只检查基准
规则。

## 4. Layer1分层

五项条件每项通过计1分：

```text
technical_score = Σ I(condition passed)，范围0至5
```

基础过滤不通过时，无论五项分数多少都不能进入有效层级：

| 条件 | 层级 |
|---|---|
| 基础过滤未通过 | `基础过滤未通过` |
| 基础过滤通过且5分 | `5/5 技术确认` |
| 基础过滤通过且4分 | `4/5 观察池` |
| 基础过滤通过且3分 | `3/5 潜在观察` |
| 其他 | `N/5` |

Layer2不能把4/5股票提升成5/5，它只在每个技术层级内部排序。

## 5. Layer2通用评分函数

### 5.1 递增型

适合“越高越好”的指标：

```text
rising(x; zero, full, W)
  = W × clip((x-zero)/(full-zero), 0, 1)
```

### 5.2 递减型

适合“越低越好”的指标：

```text
falling(x; full, zero, W)
  = W × [1 - clip((x-full)/(zero-full), 0, 1)]
```

### 5.3 甜蜜区型

```text
sweet(x; L0, L1, H1, H0, W) =
  0                              x <= L0 或 x >= H0
  W×(x-L0)/(L1-L0)               L0 < x < L1
  W                              L1 <= x <= H1
  W×(H0-x)/(H0-H1)               H1 < x < H0
```

缺失、无穷或非数值输入均得到0项分。

## 6. Layer2派生指标

```text
high_strength  = recent_high / previous_high - 1
low_strength   = recent_low / previous_low - 1
distance_ma20  = C_t / MA20_t - 1
ma_spread      = MA20_t / MA60_t - 1

breakout_extension = C_t / breakout_price - 1
breakout_volume_multiple = breakout_volume / prior_20d_avg_volume
support_margin = minimum_close_since_breakout / breakout_price - 1
retest_volume_ratio = post_breakout_avg_volume / prior_20d_avg_volume
```

## 7. Layer2正向分

### 7.1 价格结构，满分15

```text
structure_high = rising(high_strength; 0, 0.10, 7.5)
structure_low  = rising(low_strength;  0, 0.10, 7.5)
```

### 7.2 均线趋势，满分20

```text
ma20_slope    = rising(ma20_5d_rise;  0, 0.04, 6)
ma60_slope    = rising(ma60_10d_rise; 0, 0.05, 5)
ma_spread     = rising(ma_spread;      0, 0.12, 4)
price_position = sweet(distance_ma20; -0.03, 0, 0.08, 0.15, 5)
```

### 7.3 量价，满分20

```text
up_down_volume = rising(volume_ratio; 1.00, 2.00, 8)
breakout_volume = rising(breakout_volume_multiple; 1.00, 2.00, 7)
retest_volume = falling(retest_volume_ratio; 0.80, 1.50, 5)
```

突破后的平均量低于或等于突破前均量80%得满分，达到150%为0分。

### 7.4 突破质量，满分25

```text
breakout_recency = falling(days_since_breakout; 5, 20, 8)
breakout_extension = sweet(extension; -0.10, -0.03, 0.08, 0.30, 10)
breakout_support = rising(support_margin; -0.10, -0.03, 7)
```

未找到突破事件时，相关输入不可用，对应项为0分。

### 7.5 相对强度，满分20

```text
market_percentile = rising(percentile_0_to_100; 50, 100, 10)
excess_return_20d = rising(ER20; 0, 0.10, 4)
excess_return_60d = rising(ER60; 0, 0.30, 6)
```

## 8. 缺失百分位时的归一化

全市场正向权重总和为100：

```text
raw_quality_score = 所有可计算正向项得分之和
available_weight = 100 - 缺失的市场百分位权重
normalized_score = raw_quality_score × 100 / available_weight
```

当前只有市场百分位被显式当作可选权重，因此小样本模式通常
`available_weight=90`。其他缺失指标会得到0分，不减少 `available_weight`。
小样本质量分标记为 `score_comparable_to_full_market=false`，不应直接和全市场分数
做横向比较。

## 9. 过热扣分与最终质量分

```text
ma20_penalty = rising(distance_ma20; 0.15, 0.25, 10)
breakout_penalty = rising(breakout_extension; 0.20, 0.30, 10)
overheat_penalty = ma20_penalty + breakout_penalty

technical_quality_score
  = clip(normalized_score - overheat_penalty, 0, 100)
```

所以Layer2最高100分、最多额外扣20分。价格远离均线或突破位不会直接改变Layer1
资格，但会降低同层排名。

## 10. Layer2排序

只对基础过滤通过的股票排序，排序键从高到低为：

```text
technical_score
technical_quality_score
return_60d
```

然后在每个 `technical_score` 层级内分别生成 `rank_within_tier`。5/5和4/5不是同一
张榜单。

## 11. 前复权输入

Tushare数据库保存原始价格和复权因子，读取时动态计算：

```text
QFQ_price_t = raw_price_t × adj_factor_t / adj_factor_latest
```

腾讯数据库直接保存腾讯前复权价格，`adj_factor=1`，不会二次复权。成交量两种模式
均不复权。不同数据源不能拼在同一个数据库，否则会在人为切换处产生假跳空。

## 12. 调试定位顺序

1. 查看 `base_filters`，排除历史不足、陈旧、ST或流动性问题；
2. 查看 `conditions.<name>.detail`，确认是哪条Layer1公式失败；
3. 查看 `quality.metrics`，确认Layer2派生指标；
4. 查看 `quality.component_scores` 和 `overheat_penalty`；
5. 检查 `score_comparable_to_full_market`，避免误用小样本分；
6. 只改Layer2时用 `--from-layer 2` 复用同一Layer1快照；
7. 用历史评估比较参数版本，不以单只股票是否入选作为调参依据。
