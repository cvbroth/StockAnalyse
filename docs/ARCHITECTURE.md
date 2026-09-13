# 项目架构

```text
app.cli
   │
   ▼
app.services
   ├──────────────┬────────────────┐
   ▼              ▼                ▼
app.providers   app.storage     app.analysis
腾讯/Tushare      SQLite          指标与输出
```

## 各层职责

- `app/cli/`：稳定命令入口，只负责参数和任务编排。
- `app/services/`：初始化、续传、日常更新和本地扫描流程。
- `app/providers/`：外部接口访问和统一字段转换。
- `app/storage/`：SQLite表结构、事务、状态和查询。
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
   └── FundamentalAnalyzer协议（默认关闭）
```

每个模块接收统一的 `StockInput` 和 `ScreenConfig`，返回 `ConditionResult`。
组合器返回 `Layer1Result`；兼容门面再把它转换为v1.2原有字典，因此旧命令和
输出结构继续可用。

第一层参数位于 `config/analysis/layer1.toml`。配置的 `version`、实际路径和完整
参数会写入输出元数据，为后续评分、回测和多版本对照提供依据。

第二层参数位于 `config/analysis/layer2.toml`。全市场成功运行还会原子保存运行
快照；第二层可以从快照单独重跑，历史评估命令则从SQLite读取运行日后的行情。

## 兼容入口

旧脚本仅转发到新模块，方便已有服务器命令继续运行：

| 旧命令 | 新实现 |
|---|---|
| `app/update_market.py` | `app.services.market_update` |
| `app/screener_v1_2.py` | `app.services.screening` |
| `app/run_daily.py` | `app.cli.daily` |
| `app/market_db.py` | `app.storage.sqlite` |

新功能不应继续写入兼容入口或 `legacy/`。
