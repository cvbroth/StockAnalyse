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
基本面提供者接口（默认关闭）
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

`app.analysis.fundamentals` 定义了统一输入、结果和提供者协议。默认使用安全的
`DisabledFundamentalAnalyzer`，不生成虚假基本面分。未来接入外部研究服务时，
基本面负责排序或否决，不直接与技术分相加。
