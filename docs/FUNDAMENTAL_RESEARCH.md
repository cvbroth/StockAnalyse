# Layer3研究结果契约

这一层负责连接Python财务量化与后续外部研究工具。它不会自行搜索新闻，也不会
允许外部研究修改Layer1、Layer2或 `financial_quant.json`。

## 文件流

```text
financial_quant.json
        ↓
research_request.json             Python生成，只读输入
        ↓
外部研究员或后续OpenClaw Skill
        ↓
research_results.json             外部工具新建
        ↓
Python严格校验和Layer3合并
        ↓
layer3.json
```

执行基本面命令后，运行目录会同时生成：

```text
output/runs/<运行编号>/fundamental/
├── research_request.json
├── research_results.template.json
└── layer3.json
```

`research_request.json` 默认包含Layer2前10只股票。模板最初是合法的 `partial`
结构，但不含研究结论。复制模板为 `research_results.json` 后，研究工具只填写结论
字段，不能改动 `run_id`、`code`、`as_of_date` 或 `input_hash`。

## 固定研究内容

每只股票必须回答：近期业绩与利润加速度、现金流质量、最近90天经营变化、行业
价格/需求/库存、新订单或产能等催化、盈利预期变化、主要风险及最终边际状态。

外部研究只负责三项0到100分：

- `industry_cycle`：行业景气，越高越好；
- `expectation_delta`：盈利预期向上变化程度，越高越好；
- `risk`：风险，越高越差。

盈利动量和经营质量由Python根据八季度数据计算，外部工具不得覆盖。

## 证据要求

每条证据必须包括判断、来源类型、来源名称、来源层级、发布日期、有效期间、可信度，
以及 `source_url` 或 `document_id` 至少一个。来源层级定义为：

| 层级 | 来源 |
|---:|---|
| 1 | 交易所公告、公司财报、业绩预告、官方投资者关系记录 |
| 2 | 公司官网、行业协会、政府数据 |
| 3 | 券商研报、专业财经媒体 |
| 4 | 普通媒体和网络讨论 |

任何证据的 `published_date` 晚于运行 `as_of_date`，整份研究结果都会被拒绝，避免
历史截面偷看未来信息。

## 完整结果示意

实际使用时应从自动生成的模板复制运行编号、输入指纹和股票信息：

```json
{
  "schema_version": "fundamental-research-v1",
  "run_id": "20260911-153000123456",
  "input_hash": "从模板原样复制的64位SHA-256",
  "code": "603505",
  "name": "金石资源",
  "as_of_date": "2026-09-11",
  "status": "complete",
  "fundamental_state": "IMPROVING",
  "scores": {
    "industry_cycle": 88,
    "expectation_delta": 84,
    "risk": 30
  },
  "risk_level": "MEDIUM",
  "confidence": 0.82,
  "signals": {
    "revenue_accelerating": true,
    "profit_accelerating": true,
    "margin_improving": true,
    "industry_improving": true,
    "expectation_revision": true
  },
  "catalysts": ["主要产品价格上涨"],
  "risks": ["产品价格回落"],
  "vetoes": [],
  "evidence": [
    {
      "claim": "主要产品价格上涨",
      "source_type": "filing",
      "source_name": "公司公告",
      "source_tier": 1,
      "published_date": "2026-09-05",
      "effective_period": "最近90天",
      "confidence": 0.9,
      "source_url": "https://example.com/notice",
      "document_id": null,
      "excerpt": "不超过25字的必要证据摘要"
    }
  ],
  "why_now": "行业景气和盈利趋势同步改善",
  "industry_summary": "价格上升、库存下降",
  "expectation_summary": "盈利预期存在上修可能",
  "risk_summary": "最大风险是价格回落"
}
```

`complete` 结果必须给出三项研究分、全部五个布尔信号、至少一项风险、至少一条
证据和四段摘要。资料不足时应保留 `partial`，不能猜测缺失字段。

## 合并与否决

正向分按以下权重计算后归一为100：

```text
盈利动量 25 + 经营质量 20 + 行业景气 15 + 预期变化 25
```

风险最多扣15分：

```text
最终分 = 正向归一分 - 风险分 × 15%
```

风险等级为 `RED`、风险分达到 `red_risk_threshold`，或研究结果明确提供 `vetoes`
时，股票状态为 `REJECTED` 且不参与排名。研究缺失、字段不全或可信度不足时，状态
保持 `pending/partial`，不会生成可排名的最终分。

导入标准文件名：

```bash
cp research_results.template.json research_results.json
python -m app.cli.fundamentals
```

也可以传入其他位置：

```bash
python -m app.cli.fundamentals --research-results /path/to/results.json
```
