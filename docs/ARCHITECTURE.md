# 项目架构

```text
app.cli
   │
   ▼
app.services
   ├──────────────┬────────────────┬────────────────┐
   ▼              ▼                ▼                ▼
app.providers   app.storage   app.fundamentals   app.analysis
外部数据适配器     双SQLite库      数据域契约         纯分析与输出
```

## 各层职责

- `app/cli/`：稳定命令入口，只负责参数和任务编排。
- `app/services/`：初始化、续传、日常更新和本地扫描流程。
- `app/providers/`：外部接口访问和统一字段转换。
- `app/storage/`：行情库和基本面缓存库的SQLite表结构、事务、状态和查询。
- `app/fundamentals/`：提供者、存储和分析共同使用的基本面数据契约与配置。
- `app/analysis/`：不访问网络和数据库的纯分析逻辑。
- `app/legacy/`：只为旧版直接联网命令保留。

## 数据流

腾讯：

```text
腾讯前复权日线 → TencentProvider → 标准日线 → SQLite
```

Tushare：

```text
daily + adj_factor → TushareProvider → 标准日线 → SQLite
```

筛选：

```text
SQLite → 统一前复权窗口 → AnalysisEngine → Layer1 → 市场百分位 → JSON/CSV
```

基本面数据准备：

```text
market.db → Layer1/Layer2 → Top N候选请求
                              │
                              ▼
AKShare同花顺财务摘要 ─┐
                       ├→ 标准观测值 → fundamentals.db → 八季度纯量化 → 独立结果
东方财富精确公告日期 ──┘
```

`market.db`覆盖全市场且主要按日更新；`fundamentals.db`仅缓存曾经进入候选范围的
股票，主要按财报或公告节奏更新。分析引擎不会直接联网，也不会在分析过程中写库。
候选退出后历史基本面数据继续保留，以便复现旧运行。

## 分层分析引擎

分层引擎依次负责资格、排名和运行状态：

```text
AnalysisEngine
   ├── Layer1Analyzer
       ├── PriceStructureModule
       ├── MATrendModule
       ├── VolumePriceModule
       ├── BreakoutRetestModule
   │   └── RelativeStrengthModule
   ├── Layer2Analyzer
   │   ├── 五部分质量评分
   │   └── 过热惩罚
   └── 基本面数据域
       ├── 八季度财务量化（已启用）
       └── FundamentalAnalyzer组合协议（后续阶段）
```

每个模块接收统一的 `StockInput` 和 `ScreenConfig`，返回 `ConditionResult`。
组合器返回 `Layer1Result`；兼容门面再把它转换为v1.2原有字典，因此旧命令和
输出结构继续可用。

第一层参数位于 `config/analysis/layer1.toml`。配置的 `version`、实际路径和完整
参数会写入输出元数据，为后续评分、回测和多版本对照提供依据。

第二层参数位于 `config/analysis/layer2.toml`。全市场成功运行还会原子保存运行
快照；第二层可以从快照单独重跑，历史评估命令则从SQLite读取运行日后的行情。

基本面收集参数位于 `config/analysis/fundamental.toml`。默认选取Layer2 Top 30、
请求最近8个季度。真实提供者把标准观测值写入独立稀疏缓存，再由不访问网络和
数据库的纯分析模块计算盈利动量、经营质量及数据覆盖率。技术层与基本面层之间
只共享不可变运行编号、截止日期和候选上下文。

## 兼容入口

旧脚本仅转发到新模块，方便已有服务器命令继续运行：

| 旧命令 | 新实现 |
|---|---|
| `app/update_market.py` | `app.services.market_update` |
| `app/screener_v1_2.py` | `app.services.screening` |
| `app/run_daily.py` | `app.cli.daily` |
| `app/market_db.py` | `app.storage.sqlite` |

新功能不应继续写入兼容入口或 `legacy/`。
