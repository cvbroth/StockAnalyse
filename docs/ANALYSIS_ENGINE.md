# 分层分析引擎

v1.3保留原有五项资格门槛，并在其后增加质量排名、跨日状态跟踪和历史验证。

```text
SQLite行情
   ↓
Layer 1 五项资格判断（0～5）
   ↓
Layer 2 技术质量排名（0～100）－过热惩罚
   ↓
运行快照与状态变化
   ↓
历史20/60日表现评估
   ↓
按需八季度财务量化（独立结果）
```

## 第一层

五个模块分别负责价格结构、均线趋势、量价、突破回踩和相对强度。参数位于
`config/analysis/layer1.toml`，默认值与v1.2完全一致。

第一层决定资格池：

- A池：5/5技术确认；
- B池：4/5观察；
- 其余股票仍保留在运行快照中，用于正确识别以后从低分进入观察池的变化。

## 第二层

参数位于 `config/analysis/layer2.toml`。正向权重之和固定为100：

| 组成 | 分值 |
|---|---:|
| 价格结构 | 15 |
| 均线趋势 | 20 |
| 量价质量 | 20 |
| 突破回踩 | 25 |
| 相对强度 | 20 |

距离MA20或突破位过远时，另外计算最多20分的 `overheat_penalty`。结果同时保存
五个组成分、原始分、扣分和最终 `technical_quality_score`，不会只给一个无法解释
的总分。

`--symbols` 模式没有全市场百分位，程序会按其余90分归一化，并把
`score_comparable_to_full_market` 标记为 `false`，避免把小样本得分当成全市场排名。

## 运行历史

完整全市场运行保存在：

```text
output/runs/<run-id>/
├── manifest.json
├── layer1.json
├── layer2.json
└── transitions.json
```

`manifest.json` 记录数据日期、数据源、参数版本和上一次运行。状态包括：

- `first_observation`：第一次见到该股票；
- `newly_5of5`：从不足5项升级为5/5；
- `still_5of5`：继续保持5/5；
- `downgraded_to_4of5`：从5/5退回4/5；
- `newly_4of5`：从低分进入4/5观察池；
- `left_watchlist`：离开4/5观察池。

只修改第二层评分参数时，可以复用已有第一层快照：

```bash
python -m app.cli.screen \
  --from-layer 2 \
  --run-id 20260911-153000000000 \
  --quality-config config/analysis/layer2.toml
```

研究重跑写入新的运行目录，但不会替换每日全市场最新运行指针。

## 历史效果评估

数据库积累到运行日之后至少20或60个交易日时执行：

```bash
python -m app.cli.evaluate --run-id <run-id> --horizons 20 60
```

结果写入该运行目录的 `evaluation.json` 和 `evaluation.csv`，包括收益均值、中位数、
胜率和平均最大回撤，并分别按A/B池和质量分区间汇总。未来行情不足时显示缺失，
不会虚构收益。

## 基本面接口

基本面数据采集与基本面分析已经分离：

- `app.fundamentals` 定义带报告期、发布日期、可用日期和来源的数据契约；
- `app.providers.fundamentals` 定义可替换数据提供者协议；
- `app.storage.fundamentals_sqlite` 管理独立的稀疏缓存库；
- `app.services.fundamental_sync` 从Layer2排名生成按需请求并支持逐股续传；
- `app.analysis.fundamentals` 接收标准观测值，纯计算盈利动量、经营质量和覆盖率。

准备一次运行的基本面请求：

```bash
python -m app.cli.fundamentals
```

省略 `--run-id` 时使用 `latest_full_market.json` 指向的最近一次完整全市场运行；
指定 `--run-id` 则可复现某个历史技术候选截面。

默认取Layer2 Top 30、最近8个季度。AKShare同花顺财务摘要提供标准财务指标，
东方财富业绩报表只补精确公告日期。结果包括：

- `request.json`：候选范围及技术上下文；
- `sync_summary.json`：获取、缓存、失败和写入数量；
- `financial_quant.json`：每只股票的盈利动量分、经营质量分、覆盖率、缺失指标和
  `IMPROVING/STABLE/DETERIORATING/UNCERTAIN` 初步状态。
- `research_request.json`：Top 10固定研究问题、技术上下文、财务量化和输入指纹；
- `research_results.template.json`：外部研究员必须遵循的结果模板；
- `layer3.json`：财务量化与结构化研究的合并、风险否决和最终基本面排名。

`python -m app.cli.research` 会把Top 10拆成逐股工作项。外部工具按股票把JSON
投递到 `research/inbox/`，执行器逐一校验后保存到 `research/results/`，所以一只
股票失败不会丢失已完成结果。`--resume` 只补未完成股票；`--validate-only` 对
已保存结果做只读检查。

已缓存且未过期的数据会复用；单只股票失败不会中断其他股票，也不会改写Layer1/2。
精确公告日期缺失时使用更晚的法定最晚披露日，并用 `availability_basis` 明确标记。
为了避免同日收盘前偷看盘后公告，公告数据从下一自然日才视为可用。基本面结果
仍不与技术分直接相加，后续组合阶段只把它用于排序、确认或否决。

没有导入研究结果时，`layer3.json` 的记录状态为 `pending`，最终分为 `null`。
程序不会用财务分、技术分或默认值冒充缺失的行业景气、预期变化和风险结论。
研究结果必须带证据、来源层级、发布日期、运行编号、截止日期和输入指纹；任一
边界不匹配都会拒绝整份导入。

Layer3正向部分由盈利动量25、经营质量20、行业景气15、预期变化25组成，先按
85分权重归一到100；风险分越高越差，最多再扣15分。风险等级为 `RED`、风险分
达到配置阈值或外部研究明确给出否决项时，不参与最终排名。
