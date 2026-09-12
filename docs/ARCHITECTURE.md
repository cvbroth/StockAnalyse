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
SQLite → 统一前复权窗口 → 五项技术条件 → 市场百分位 → JSON/CSV
```

## 兼容入口

旧脚本仅转发到新模块，方便已有服务器命令继续运行：

| 旧命令 | 新实现 |
|---|---|
| `app/update_market.py` | `app.services.market_update` |
| `app/screener_v1_2.py` | `app.services.screening` |
| `app/run_daily.py` | `app.cli.daily` |
| `app/market_db.py` | `app.storage.sqlite` |

新功能不应继续写入兼容入口或 `legacy/`。
