# 参数手册

本文列出稳定CLI和三份TOML配置的参数。任何时候都可以用
`python -m <入口> --help` 查看当前版本的命令行定义。

## 1. 参数优先级与单位

路径选择优先级：

```text
命令行明确参数 > config/project.json > 项目默认路径
```

分析参数优先级：

```text
命令行单项覆盖 > 命令行指定TOML > config/analysis中的默认TOML
```

常用单位：

- 收益率、比例和增长率在代码中使用小数：`0.08` 表示8%；
- 市场百分位配置使用0到1：`0.70` 表示第70百分位及以上；
- 输出中的 `market_percentile` 使用0到100；
- 成交量单位为“手”；
- 天数未特别说明时为交易日，`stale_calendar_days` 为自然日；
- Layer2和Layer3分数范围为0到100，研究可信度范围为0到1。

## 2. 项目路径配置

初始化后自动生成且不提交Git的 `config/project.json`：

```json
{
  "version": 1,
  "database": "data/market_tx.db",
  "fundamental_database": "data/fundamentals.db",
  "output_directory": "output",
  "data_provider": "tx"
}
```

相对路径以项目根目录为基准。`data_provider` 必须与行情数据库内绑定的数据源一致，
不要手工改它来切换数据源。

## 3. 行情更新 `app.cli.update`

三种模式必须且只能选一种：

| 参数 | 含义 |
|---|---|
| `--init` | 第一次初始化或继续未完成初始化 |
| `--daily` | 按数据库已绑定的数据源做日常更新 |
| `--status` | 只读显示数据库状态 |

初始化时必须且只能选择：

| 参数 | 含义 |
|---|---|
| `--tx` | 腾讯前复权沪深行情 |
| `--tushare` | Tushare未复权日线＋复权因子 |

通用参数：

| 参数 | 默认值 | 约束/作用 |
|---|---:|---|
| `--db PATH` | 项目配置或 `data/market.db` | 行情SQLite路径 |
| `--days N` | 250 | 初始化交易日数量；至少80 |
| `--end-date YYYYMMDD` | 当天 | 初始化或更新截止日期 |
| `--repair-days N` | 0 | 强制重取最近N个交易日；不能为负 |
| `--retries N` | 3 | 接口总尝试次数；至少1 |
| `--metadata-timeout SEC` | 30 | 股票列表和沪深300单次超时；必须大于0 |
| `--set-current` | 关闭 | 只能与 `--status` 使用，将指定库写入项目配置 |
| `--min-daily-rows N` | 1000 | Tushare单日最少股票行数安全门槛 |

腾讯参数：

| 参数 | 默认值 | 作用与调试建议 |
|---|---:|---|
| `--tx-workers N` | 6 | 并发股票数；速度慢可逐步调到8，频繁断连则降到2至4 |
| `--tx-timeout SEC` | 15 | 单次历史行情请求超时；弱网络可调到30至60 |

Tushare参数：

| 参数 | 默认值 | 作用与调试建议 |
|---|---:|---|
| `--pause SEC` | 0.15 | 两次普通请求的基础间隔；不能为负 |
| `--daily-per-minute N` | 50 | `daily` 每分钟主动上限；0表示不主动限速 |
| `--adj-factor-per-minute N` | 1 | `adj_factor` 每分钟主动上限；必须与账号权限一致 |
| `--token-env NAME` | `TUSHARE_TOKEN` | Token环境变量名称，不是Token本身 |
| `--env-file PATH` | 项目根目录 `.env` | 环境变量不存在时读取的文件 |

典型命令：

```bash
python -m app.cli.update --init --tx --days 250 --db data/market_tx.db
python -m app.cli.update --daily
python -m app.cli.update --status
python -m app.cli.update --daily --repair-days 5
```

## 4. 技术筛选 `app.cli.screen`

三种入口必须且只能选一种：

| 参数 | 含义 |
|---|---|
| `--all` | 扫描数据库全市场并计算真实市场百分位 |
| `--symbols CODE...` | 小样本调试；不计算也不强制样本内百分位 |
| `--from-layer 2 --run-id ID` | 复用历史Layer1快照，只重跑Layer2 |

其余参数：

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `--db PATH` | 项目配置 | 行情数据库 |
| `--output-dir PATH` | 项目配置或 `output` | 结果目录 |
| `--analysis-config PATH` | `config/analysis/layer1.toml` | Layer1配置 |
| `--quality-config PATH` | `config/analysis/layer2.toml` | Layer2配置 |
| `--end-date YYYYMMDD` | 数据库最新日期 | 历史截面日期 |
| `--history-dates N` | 250 | 每只股票最多读取的市场交易日；至少80且不能小于最少历史 |
| `--percentile-cutoff X` | TOML中的0.70 | 临时覆盖全市场百分位门槛 |
| `--min-history-days N` | TOML中的120 | 临时覆盖最低历史长度 |
| `--min-average-volume-lots N` | TOML中的0 | 临时覆盖近20日日均成交量门槛 |
| `--max-stale-calendar-days N` | TOML中的10 | 临时覆盖最大行情陈旧自然日 |
| `--include-st` | 关闭 | 临时允许ST和*ST |
| `--limit N` | 不限制 | 只处理前N只用于调试；结果不代表全市场 |
| `--progress-every N` | 500 | 每处理N只打印进度；0表示不打印周期进度 |

调试示例：

```bash
python -m app.cli.screen --symbols 603505 600519
python -m app.cli.screen --all --limit 100 --progress-every 10
python -m app.cli.screen --from-layer 2 \
  --run-id 20260911-153000123456 \
  --quality-config config/analysis/layer2-experiment.toml
```

## 5. 每日技术任务 `app.cli.daily`

该入口等价于“日常行情更新成功后执行全市场筛选”。不接受 `--tx` 或 `--tushare`，
数据源从数据库读取。

| 参数 | 默认值 | 含义 |
|---|---:|---|
| `--db` | 项目配置 | 行情库 |
| `--output-dir` | 项目配置 | 输出目录 |
| `--retries` | 3 | 更新重试次数 |
| `--metadata-timeout` | 30 | 元数据请求超时秒数 |
| `--tx-workers` | 6 | 腾讯并发数 |
| `--tx-timeout` | 15 | 腾讯请求超时秒数 |
| `--daily-per-minute` | 50 | Tushare日线频率 |
| `--adj-factor-per-minute` | 1 | Tushare复权因子频率 |
| `--token-env` | `TUSHARE_TOKEN` | Token变量名称 |
| `--env-file` | `.env` | Token文件 |
| `--percentile-cutoff` | 0.70 | 全市场60日收益百分位门槛 |
| `--include-st` | 关闭 | 允许ST股票 |

注意：该入口的 `--percentile-cutoff` 默认值会明确覆盖Layer1 TOML中的同名值。

## 6. 基本面同步 `app.cli.fundamentals`

| 参数 | 默认值 | 含义 |
|---|---:|---|
| `--run-id ID` | 最近完整全市场运行 | 指定筛选快照 |
| `--output-dir PATH` | 项目配置 | 快照所在输出目录 |
| `--fundamental-db PATH` | 项目配置或 `data/fundamentals.db` | 独立基本面缓存库 |
| `--config PATH` | `config/analysis/fundamental.toml` | 收集与Layer3配置 |
| `--top-n N` | `financial_top_n=30` | 临时覆盖财务候选数；至少1 |
| `--quarters N` | `quarters=8` | 临时覆盖季度数；至少1 |
| `--prepare-only` | 关闭 | 只生成请求和缓存范围，不访问真实接口 |
| `--timeout SEC` | 15 | 公告日期辅助接口超时；必须大于0 |
| `--retries N` | 3 | 单股失败总尝试次数；至少1 |
| `--research-results PATH` | 自动查找标准文件 | 导入批量外部研究JSON |

## 7. 逐股研究 `app.cli.research`

| 参数 | 默认值 | 含义 |
|---|---:|---|
| `--run-id ID` | 最近完整全市场运行 | 指定研究任务所属快照 |
| `--output-dir PATH` | 项目配置 | 运行输出目录 |
| `--config PATH` | 默认基本面TOML | Layer3权重和阈值 |
| `--code CODE...` | 当前任务全部股票 | 只处理指定候选 |
| `--import-results PATH` | `research/inbox` | 批量JSON或逐股JSON目录 |
| `--resume` | 关闭 | 跳过已有complete结果，补其他状态 |
| `--validate-only` | 关闭 | 只读校验已保存结果，不写入或重算 |

`scripts/openclaw_research.sh` 会把其后的安全参数交给项目Skill。建议首次使用
`--code` 验证一只，再使用 `--resume`。

## 8. 报告、完整流水线与评估

### 报告 `app.cli.report`

| 参数 | 默认值 | 含义 |
|---|---:|---|
| `--run-id ID` | 最近完整全市场运行 | 报告快照 |
| `--output-dir PATH` | 项目配置 | 输出目录 |
| `--top-n N` | 10 | Markdown最多展示的候选状态卡；至少1 |

### 完整流水线 `app.cli.pipeline`

| 参数 | 默认值 | 含义 |
|---|---:|---|
| `--resume` | 关闭 | 从非终态状态的最后失败阶段继续 |
| `--run-id ID` | 新运行 | 使用已有快照并跳过行情与技术层 |
| `--db PATH` | 项目配置 | 行情数据库 |
| `--output-dir PATH` | 项目配置 | 输出目录 |
| `--skip-research` | 关闭 | 不调用OpenClaw，生成部分报告 |
| `--report-top-n N` | 10 | 最终Markdown展示数量；至少1 |

### 历史评估 `app.cli.evaluate`

| 参数 | 默认值 | 含义 |
|---|---:|---|
| `--run-id ID` | 必填 | 需要评估的历史快照 |
| `--db PATH` | 项目配置 | 包含运行日后行情的数据库 |
| `--output-dir PATH` | 项目配置 | 快照目录 |
| `--horizons N...` | 20、60 | 向前交易日周期；均须为正整数 |

## 9. Layer1 TOML

文件：`config/analysis/layer1.toml`。

| 参数 | 默认值 | 含义与有效范围 |
|---|---:|---|
| `version` | `layer1-v1.2-baseline` | 配置标识；改参数时应同步改版本 |
| `min_history_days` | 120 | 基础过滤最低历史；至少80 |
| `structure_window` | 20 | 前后高低点比较窗口；至少1 |
| `volume_window` | 20 | 上涨/下跌日量能窗口；至少1 |
| `up_down_volume_ratio` | 1.15 | 上涨日均量/下跌日均量门槛；大于0，判断使用严格大于 |
| `breakout_lookback` | 60 | 突破前高回看期；至少1 |
| `breakout_search_days` | 20 | 最近突破事件搜索期；至少1 |
| `breakout_volume_multiple` | 1.30 | 突破量/此前20日均量门槛；严格大于 |
| `breakout_max_fall` | 0.03 | 突破后允许收盘最低跌破幅度；范围 `[0,1)` |
| `excess_return_60d` | 0.08 | 60日相对沪深300超额门槛；严格大于 |
| `market_percentile_cutoff` | 0.70 | 全市场60日收益百分位门槛；范围 `(0,1]` |
| `max_stale_calendar_days` | 10 | 最新行情距截面的最大自然日；不能为负 |
| `min_average_volume_lots` | 0 | 近20日日均成交量最低值；不能为负 |
| `exclude_st` | true | 是否排除名称含ST的股票 |

## 10. Layer2 TOML

文件：`config/analysis/layer2.toml`。15项正向权重之和必须为100；两个过热权重是
额外扣分上限，不计入这100分。

候选展示：

| 参数 | 默认值 | 含义 |
|---|---:|---|
| `confirmed_top_n` | 25 | 5/5池展示数量 |
| `watchlist_top_n` | 30 | 4/5池展示数量 |

正向权重：

| 分组 | 参数与默认权重 |
|---|---|
| 价格结构，共15 | `structure_high=7.5`，`structure_low=7.5` |
| 均线趋势，共20 | `ma20_slope=6`，`ma60_slope=5`，`ma_spread=4`，`price_position=5` |
| 量价，共20 | `up_down_volume=8`，`breakout_volume=7`，`retest_volume=5` |
| 突破质量，共25 | `breakout_recency=8`，`breakout_extension=10`，`breakout_support=7` |
| 相对强度，共20 | `market_percentile=10`，`excess_return_20d=4`，`excess_return_60d=6` |
| 过热扣分 | `overheat_ma20=10`，`overheat_breakout=10` |

阈值：

| 参数 | 默认值 | 解释 |
|---|---:|---|
| `structure_full_rise` | 0.10 | 高点/低点抬升10%得满分 |
| `ma20_slope_full` | 0.04 | MA20相对5日前上升4%得满分 |
| `ma60_slope_full` | 0.05 | MA60相对10日前上升5%得满分 |
| `ma_spread_full` | 0.12 | MA20高于MA60达到12%得满分 |
| `price_ma20_lower_zero` | -0.03 | 股价低于MA20超过3%为0分 |
| `price_ma20_ideal_high` | 0.08 | 股价位于MA20至其上8%为满分区 |
| `price_ma20_upper_zero` | 0.15 | 股价高于MA20达到15%回落至0分 |
| `volume_ratio_zero/full` | 1.00 / 2.00 | 上涨/下跌日量比的0分与满分点 |
| `breakout_volume_zero/full` | 1.00 / 2.00 | 突破量倍数的0分与满分点 |
| `retest_volume_full/zero` | 0.80 / 1.50 | 突破后量比越低越好 |
| `breakout_recency_full/zero_days` | 5 / 20 | 距突破越近越好 |
| `breakout_extension_lower_zero` | -0.10 | 低于突破位10%为0分 |
| `breakout_extension_ideal_low/high` | -0.03 / 0.08 | 距突破位甜蜜区 |
| `breakout_extension_upper_zero` | 0.30 | 高于突破位30%为0分 |
| `breakout_support_zero/full` | -0.10 / -0.03 | 突破后最低收盘支撑强度 |
| `market_percentile_zero/full` | 50 / 100 | 百分位0分与满分点，单位0至100 |
| `excess_return_20d_full` | 0.10 | 20日超额10%得满分 |
| `excess_return_60d_full` | 0.30 | 60日超额30%得满分 |
| `overheat_ma20_start/full` | 0.15 / 0.25 | 距MA20从15%开始扣，25%扣满 |
| `overheat_breakout_start/full` | 0.20 / 0.30 | 距突破位从20%开始扣，30%扣满 |

## 11. 基本面 TOML

文件：`config/analysis/fundamental.toml`。

收集参数：

| 参数 | 默认值 | 含义 |
|---|---:|---|
| `enabled` | true | 是否启用基本面流程 |
| `provider` | `akshare_ths` | 当前真实财务提供者 |
| `financial_top_n` | 30 | 从Layer2取多少只同步财务 |
| `research_top_n` | 10 | 从财务候选取多少只生成外部研究任务；不得大于前者 |
| `quarters` | 8 | 每只最多使用的已公开季度数 |
| `stale_after_days` | 7 | 缓存超过多少自然日视为陈旧；可设0 |

Layer3参数：

| 参数 | 默认值 | 含义 |
|---|---:|---|
| `earnings_momentum_weight` | 25 | 盈利动量正向权重 |
| `business_quality_weight` | 20 | 经营质量正向权重 |
| `industry_cycle_weight` | 15 | 行业景气正向权重 |
| `expectation_delta_weight` | 25 | 预期变化正向权重 |
| `risk_penalty_weight` | 15 | 风险最大扣分 |
| `red_risk_threshold` | 80 | 风险分达到该值自动否决 |
| `key_focus_threshold` | 75 | 重点关注最低最终分，且状态必须IMPROVING |
| `follow_up_threshold` | 60 | 跟踪池最低最终分；不能高于重点阈值 |
| `min_research_confidence` | 0.60 | 研究结果进入complete的最低可信度 |

五项权重合计必须为100，其中前四项正向权重当前合计85。公式见
[基本面分析公式](FUNDAMENTAL_FORMULAS.md)。

## 12. 安全调参方法

不要直接覆盖基准配置。复制后修改，并更换 `version`：

```bash
cp config/analysis/layer2.toml config/analysis/layer2-experiment.toml
python -m app.cli.screen --from-layer 2 \
  --run-id <运行编号> \
  --quality-config config/analysis/layer2-experiment.toml
```

每次只改变一组参数，保存运行编号、配置版本、候选数量和后续20/60日评估结果。
Layer1决定资格，Layer2只决定同层排序，Layer3只做基本面排序或否决；不要通过调高
后一层分数绕过前一层条件。

## 13. TOML完整键名索引

本节供自动检查和搜索使用。Layer1顶层与区段：`version`、`screen`。

Layer1 `[screen]`：`min_history_days`、`structure_window`、`volume_window`、
`up_down_volume_ratio`、`breakout_lookback`、`breakout_search_days`、
`breakout_volume_multiple`、`breakout_max_fall`、`excess_return_60d`、
`market_percentile_cutoff`、`max_stale_calendar_days`、
`min_average_volume_lots`、`exclude_st`。

Layer2顶层与区段：`version`、`confirmed_top_n`、`watchlist_top_n`、`weights`、
`thresholds`。

Layer2 `[weights]`：`structure_high`、`structure_low`、`ma20_slope`、
`ma60_slope`、`ma_spread`、`price_position`、`up_down_volume`、
`breakout_volume`、`retest_volume`、`breakout_recency`、`breakout_extension`、
`breakout_support`、`market_percentile`、`excess_return_20d`、
`excess_return_60d`、`overheat_ma20`、`overheat_breakout`。

Layer2 `[thresholds]`：`structure_full_rise`、`ma20_slope_full`、
`ma60_slope_full`、`ma_spread_full`、`price_ma20_lower_zero`、
`price_ma20_ideal_high`、`price_ma20_upper_zero`、`volume_ratio_zero`、
`volume_ratio_full`、`breakout_volume_zero`、`breakout_volume_full`、
`retest_volume_full`、`retest_volume_zero`、`breakout_recency_full_days`、
`breakout_recency_zero_days`、`breakout_extension_lower_zero`、
`breakout_extension_ideal_low`、`breakout_extension_ideal_high`、
`breakout_extension_upper_zero`、`breakout_support_zero`、
`breakout_support_full`、`market_percentile_zero`、`market_percentile_full`、
`excess_return_20d_full`、`excess_return_60d_full`、`overheat_ma20_start`、
`overheat_ma20_full`、`overheat_breakout_start`、`overheat_breakout_full`。

基本面顶层与区段：`version`、`enabled`、`provider`、`collection`、`scoring`。

基本面 `[collection]`：`financial_top_n`、`research_top_n`、`quarters`、
`stale_after_days`。

基本面 `[scoring]`：`earnings_momentum_weight`、`business_quality_weight`、
`industry_cycle_weight`、`expectation_delta_weight`、`risk_penalty_weight`、
`red_risk_threshold`、`key_focus_threshold`、`follow_up_threshold`、
`min_research_confidence`。
