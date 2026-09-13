# 完整使用手册

v1.3把“下载行情”和“分层分析”分开：行情先写入SQLite，五项资格、技术质量
排名、状态变化和全市场60日收益百分位随后完全在本地计算。

新机器安装请先阅读 [部署教程](DEPLOYMENT.md)，逐项查参数使用
[参数手册](PARAMETERS.md)。调试评分时以
[技术分析公式](TECHNICAL_FORMULAS.md) 和
[基本面分析公式](FUNDAMENTAL_FORMULAS.md) 为准。

## 目录结构

```text
a_share_screener/
├── app/
│   ├── cli/                稳定命令入口
│   │   ├── update.py
│   │   ├── screen.py
│   │   ├── daily.py
│   │   ├── fundamentals.py   按需基本面同步与量化入口
│   │   ├── research.py       Layer3逐股研究工作区入口
│   │   ├── report.py         最终研究报告入口
│   │   └── pipeline.py       每日完整流水线入口
│   ├── providers/          可替换的数据源层
│   │   ├── base.py
│   │   ├── tencent.py
│   │   ├── tushare.py
│   │   └── fundamentals/   基本面提供者协议与AKShare实现
│   ├── services/           更新与筛选业务流程
│   │   ├── market_update.py
│   │   ├── screening.py
│   │   ├── fundamental_sync.py
│   │   ├── fundamental_analysis.py
│   │   ├── daily_report.py
│   │   └── daily_pipeline.py
│   ├── fundamentals/       基本面数据模型与配置
│   ├── analysis/           与数据源无关的分层分析核心
│   │   ├── contracts.py    层间标准输入和输出
│   │   ├── pipeline.py     AnalysisEngine统一入口
│   │   ├── layer1/         五项资格筛选模块
│   │   ├── layer2/         质量评分与过热惩罚
│   │   ├── history.py      运行快照
│   │   ├── transitions.py  跨日状态变化
│   │   ├── evaluation.py   历史效果评估
│   │   ├── fundamentals/   基本面分析结果协议与八季度量化
│   │   ├── engine.py       旧分析函数兼容门面
│   │   └── outputs.py
│   ├── storage/
│   │   ├── sqlite.py       全市场行情库
│   │   └── fundamentals_sqlite.py  稀疏基本面缓存库
│   ├── legacy/             v1.1直接联网兼容实现
│   ├── project_config.py   项目级数据库/输出目录配置
│   ├── update_market.py    旧命令兼容入口
│   ├── screener_v1_2.py    旧命令兼容入口
│   └── run_daily.py        旧命令兼容入口
├── data/                 行情库与独立基本面缓存库
├── config/               项目配置和版本化分析参数
├── output/               JSON、CSV 筛选结果
├── skills/               OpenClaw项目级研究Skill
├── scripts/              Ubuntu启动与自动化安装脚本
├── tests/                无网络自动化测试
├── README.md             使用说明
└── requirements.txt      Python 依赖
```

第二阶段以后，数据流固定为：

```text
命令入口 → 业务服务 → 数据提供者/SQLite存储 → 分析核心 → 输出文件
```

腾讯和Tushare都实现公共的数据提供者能力描述，并分别负责把自己的字段转换为
统一存储格式。分析核心只接收标准行情，不导入AKShare、Tushare或SQLite模块，
因此以后增加BaoStock等提供者时不需要修改技术指标和选股规则。

推荐使用不含版本号的新入口：

```bash
python -m app.cli.update --status
python -m app.cli.screen --all
python -m app.cli.daily
```

原有命令仍然兼容，行为与新入口相同：

```bash
python app/update_market.py --status
python app/screener_v1_2.py --all
python app/run_daily.py
```

初始化完成后，程序会自动生成本机专用的 `config/project.json`，统一记录当前
数据库和结果目录。更新、筛选、每日运行三个入口都会读取它；命令行明确传入的
`--db` 或 `--output-dir` 优先级更高。配置文件不含Token且已被Git忽略。

如果尚未生成项目配置，则兼容旧版本，默认使用 `data/market.db` 和 `output/`。

五项资格筛选参数位于 `config/analysis/layer1.toml`。文件中的默认值与重构前完全
一致，`version` 会随结果一起保存。需要试验另一套参数时，建议复制并修改配置，
再明确指定：

```bash
python -m app.cli.screen --all --analysis-config config/analysis/layer1.toml
```

命令行的 `--percentile-cutoff`、`--min-history-days`、
`--min-average-volume-lots`、`--max-stale-calendar-days` 和 `--include-st`
仍然可用，并且优先于配置文件。

## 1. 安装依赖

在项目虚拟环境中执行：

```powershell
python -m pip install -r requirements.txt
```

## 2. 选择数据源

初始化时必须选择一种个股数据源：

| 选择 | 行情方式 | 适合用户 |
|---|---|---|
| `--tx` | 腾讯直接提供沪深股票前复权日线 | 没有Tushare Token、复权因子只有试用低频权限，或者希望完全免费运行的用户 |
| `--tushare` | Tushare未复权日线＋复权因子，本地动态计算前复权 | 已具备 `daily` 和 `adj_factor` 正式权限、需要包含北交所，而且复权因子调用频率足以完成初始化的用户 |

之所以必须明确选择，是因为两个平台的复权算法、价格精度和更新时间可能存在
差异。一个数据库只能使用一种个股数据源，不能把腾讯和Tushare的价格按日期
拼接，否则均线和收益率可能在数据源切换处出现假跳空。

数据源选择会写入SQLite数据库。以后执行 `--daily` 时程序自动读取初始化选择，
用户不能临时切换数据源。如果需要换源，必须指定新的数据库文件重新初始化。

### 腾讯用户

腾讯模式不需要Token，可以直接跳到“第一次初始化”。腾讯按股票下载完整的
前复权窗口，网络请求数量较多，但支持并发、按股票保存和断点续传，适合放在
Ubuntu服务器后台运行。当前腾讯历史接口只可靠支持沪深股票，北交所股票会被
明确跳过，因此腾讯模式的“全市场百分位”实际指沪深市场。需要沪深京完整覆盖
时应选择Tushare模式。

### Tushare用户

可以复制项目提供的模板，再编辑 `.env`：

```bash
cp .env.example .env
```

文件内容为：

```dotenv
TUSHARE_TOKEN=你的Tushare Token
```

Linux服务器可以限制该文件只能由当前用户读取：

```bash
chmod 600 .env
```

程序读取顺序为：

1. 当前进程的 `TUSHARE_TOKEN` 环境变量。
2. 项目根目录的 `.env` 文件。

也可以不创建文件，直接在当前终端临时设置。Windows PowerShell：

```powershell
$env:TUSHARE_TOKEN="你的 Tushare Token"
```

Linux或macOS：

```bash
export TUSHARE_TOKEN="你的 Tushare Token"
```

`.env` 已被 `.gitignore` 排除，不会加入Git提交。程序不会把Token写入源码或
数据库。选择Tushare初始化前，请确认账号具有 `daily` 和 `adj_factor` 的正式
调用权限。若服务端提示 `adj_factor` 只有每小时1次，初始化250个交易日约需
10天，不建议选择Tushare，应改用腾讯模式。

## 3. 第一次初始化

腾讯前复权模式（没有Tushare高频复权因子权限时推荐）：

```powershell
python -m app.cli.update --init --tx --days 250
```

Tushare模式：

```powershell
python -m app.cli.update --init --tushare --days 250
```

腾讯模式按股票提交，Tushare模式按交易日提交。两种模式都支持断点续传，按
`Ctrl+C` 中断后重新执行原初始化命令即可继续。

初始化时会依次显示四个阶段：股票列表、沪深300交易日历、个股行情和数据库
质量检查。股票列表与沪深300接口默认单次最多等待30秒，可通过
`--metadata-timeout` 调整。成功选择数据源后，数据库会自动设为当前项目数据库。

腾讯默认同时下载6只股票，可以按服务器和网络情况调整：

```powershell
python -m app.cli.update --init --tx --days 250 --tx-workers 8
```

`--tx-workers` 表示腾讯并发请求数，不建议盲目调得很高，以免触发远端限制。

Tushare更新器默认按 `daily` 每分钟50次、`adj_factor` 每分钟1次分别限速。
如果账号具有更高的复权因子权限，例如每分钟200次，可以明确提高限制：

```powershell
python -m app.cli.update --init --tushare --days 250 --adj-factor-per-minute 200
```

`--adj-factor-per-minute` 必须与账号实际权限一致。程序如果收到“频率超限”错误，
会读取服务端返回的每分钟或每小时限制，自动降低速度并等待，不再进行几秒钟
内的无效重试。

查看进度和数据库状态：

```powershell
python -m app.cli.update --status
```

腾讯失败股票或Tushare失败日期都会记录在数据库中；重新执行原初始化命令会
继续补齐。

如果当前数据库已经使用Tushare初始化，但希望改用腾讯，请使用一个新的数据
库文件，避免混合两个来源：

```powershell
python -m app.cli.update --init --tx --days 250 --db data/market_tx.db
python -m app.cli.screen --all --db data/market_tx.db
python -m app.cli.daily --db data/market_tx.db
```

如果 `data/market_tx.db` 是旧版本已经初始化完成的腾讯数据库，不需要重新下载。
更新代码后只需执行一次：

```bash
python -m app.cli.update --status --db data/market_tx.db --set-current
```

以后可以省略数据库参数：

```bash
python -m app.cli.update --status
python -m app.cli.screen --all
python -m app.cli.daily
```

每个入口启动时都会明确打印数据库路径、选择来源和数据库中的实际数据源，便于
在长时间后台运行前确认没有选错数据库。

## 4. 本地扫描

全市场扫描：

```powershell
python -m app.cli.screen --all
```

小样本检查：

```powershell
python -m app.cli.screen --symbols 603505 600519 000858
```

小样本模式不会用三只股票之间的排名冒充全市场百分位。该字段为 `N/A`，也不
参与相对强度条件。

全市场扫描完成后，5/5和4/5股票会分别按第二层技术质量分排序。评分参数位于
`config/analysis/layer2.toml`，默认展示A池Top25和B池Top30。质量分只用于池内
排序，不会把4/5股票提升为5/5。

完整全市场运行会生成运行编号和历史快照。只修改第二层参数时，无需重新扫描
五千多只股票：

```bash
python -m app.cli.screen --from-layer 2 --run-id <运行编号>
```

第一次运行的股票标记为 `first_observation`。从第二次完整全市场运行开始，程序
才会识别 `newly_5of5` 等真实状态变化。

## 5. 每日运行

完成首次初始化后，每个交易日收盘数据更新完毕再执行：

```powershell
python -m app.cli.daily
```

每日入口会从数据库读取初始化数据源：腾讯数据库继续使用腾讯，Tushare数据库
继续使用Tushare。日常更新命令不接受 `--tx` 或 `--tushare`，防止误切数据源。

它等价于：

```powershell
python -m app.cli.update --daily
python -m app.cli.screen --all
```

如果行情更新不完整，一键入口会停止，不会覆盖上一份有效筛选结果。

筛选前会快速检查数据源、个股日线、沪深300历史、OHLC价格与复权因子，以及
具备最低历史长度的股票数量。严重问题会在扫描前直接停止，不再等扫描完五千只
股票才发现数据库不完整；新股历史较短等非致命情况只会显示警告。

## 数据与复权

Tushare模式保存未复权价格和每日复权因子，筛选时按每只股票最新因子动态生成
前复权OHLC：

```text
前复权价格 = 原始价格 × 当日复权因子 ÷ 最新复权因子
```

这样分红除权发生后不需要改写整段历史价格。成交量保持原始“手”数，不复权。

腾讯模式直接保存腾讯已经计算完成的前复权OHLC。因为前复权历史会在新的分红
除权发生后变化，腾讯的日常更新会重新获取并覆盖每只股票最近 `--days` 个交易
日，而不是只追加当天一行。

沪深300行情来自 AKShare 腾讯指数接口；股票名称来自
`stock_info_a_code_name()`。

## 输出

继续生成与 v1.1 相同的文件：

```text
output/
├── candidates.json
├── candidates.csv
├── technical_pass_5of5.json
├── watchlist_4of5.json
├── technical_ranked_5of5.json
├── technical_top.json
├── watchlist_ranked_4of5.json
├── transitions.json
└── errors.csv
```

每次完整全市场运行还会保存到 `output/runs/<run-id>/`。数据库积累到该运行日
之后至少20或60个交易日时，可以评价当时的评分表现：

```bash
python -m app.cli.evaluate --run-id <运行编号> --horizons 20 60
```

评估结果保存在对应运行目录的 `evaluation.json` 和 `evaluation.csv`。

## 按需同步与量化基本面

基本面使用独立的 `data/fundamentals.db`，不会写入全市场行情数据库。完成一次
全市场筛选后，可以从Layer2排名准备按需数据请求：

```bash
python -m app.cli.screen --all
python -m app.cli.fundamentals
```

这里的“运行编号”不是股票代码，也不是数据库名称，而是一次完整全市场筛选的快照
标识。例如：

```text
20260911-153000123456
```

前8位 `20260911` 是该次分析使用的行情截止日期，后半段是创建快照的时间和微秒，
用于保证编号唯一。对应文件夹为：

```text
output/runs/20260911-153000123456/
```

每次 `python -m app.cli.screen --all` 成功后都会在终端打印“运行快照”路径，并把
编号记录到 `output/runs/latest_full_market.json`。因此日常处理最新结果时直接运行
`python -m app.cli.fundamentals` 即可，程序会自动选择它。只有要重新分析某一次
历史筛选结果时才手工指定：

```bash
python -m app.cli.fundamentals --run-id 20260911-153000123456
```

默认选取Top 30并请求最近8个季度，参数位于
`config/analysis/fundamental.toml`。请求文件保存在：

```text
output/runs/<运行编号>/fundamental/request.json
```

需要临时改变范围时：

```bash
python -m app.cli.fundamentals --run-id <运行编号> --top-n 20 --quarters 8
```

参数含义：

| 参数 | 是否必需 | 含义 |
|---|---|---|
| `--run-id` | 否 | 指定历史全市场快照；省略时自动使用最近一次成功运行 |
| `--top-n` | 否 | 从Layer2候选排名中最多分析多少只；默认读取配置，目前为30 |
| `--quarters` | 否 | 每只股票最多使用多少个已公开季度；默认8 |
| `--prepare-only` | 否 | 只生成候选请求并检查范围，不访问外部财务接口 |
| `--timeout` | 否 | 公告日期辅助请求的超时秒数，默认15 |
| `--retries` | 否 | 每只股票接口失败后的总尝试次数，默认3 |
| `--research-results` | 否 | 导入外部结构化研究结果JSON；默认自动查找标准文件名 |
| `--output-dir` | 否 | 指定筛选快照所在结果目录；通常无需填写 |
| `--fundamental-db` | 否 | 指定独立基本面缓存库；通常无需填写 |
| `--config` | 否 | 指定另一份基本面TOML配置文件 |

例如，只先查看最新运行中排名前5只候选，不联网：

```bash
python -m app.cli.fundamentals --top-n 5 --prepare-only
```

确认范围无误后正式同步同一批候选：

```bash
python -m app.cli.fundamentals --top-n 5
```

默认命令会执行三步：登记候选、同步真实财务数据、计算八季度量化结果。数据源为
AKShare同花顺财务摘要；东方财富接口只用于补充精确公告日期。每只未命中缓存的
股票通常需要两次请求，已完成且未过期的数据会直接复用。

只想检查候选范围而不联网：

```bash
python -m app.cli.fundamentals --prepare-only
```

运行目录新增：

```text
fundamental/
├── request.json
├── sync_summary.json
├── financial_quant.json
├── research_request.json
├── research_results.template.json
├── research/
│   ├── work_items/
│   ├── inbox/
│   ├── results/
│   └── execution_summary.json
├── research_results.json
└── layer3.json
```

量化结果分别给出 `earnings_momentum`、`business_quality`、数据覆盖率、缺失指标和
初步状态。缺失项不会按0分处罚，而是降低覆盖率并标为 `partial` 或 `insufficient`。
公告日期按下一自然日开始可用；精确日期取不到时使用法定最晚披露日并留下
`conservative_deadline` 标记，防止历史截面误用未来财报。单只股票失败会记录并
继续，始终不会破坏Layer1/2结果。

其中 `research_request.json` 默认只选择Layer2前10只，包含固定研究问题和每只股票
的 `input_hash`。`research_results.template.json` 是下一阶段研究工具需要填写的
标准模板。当前尚未导入外部研究时，`layer3.json` 显示 `pending` 和空最终分是正常
状态，不是运行失败。

如果已经有符合契约的研究结果，可保存成运行目录下的
`fundamental/research_results.json`，再次运行命令后会自动读取；也可以明确指定：

```bash
python -m app.cli.fundamentals --research-results /path/to/research_results.json
```

程序会验证运行编号、截止日期、输入指纹、分值范围和证据发布日期。验证成功后，
`layer3.json` 才会出现最终分、风险惩罚、否决状态和排名。完整字段定义见
[Layer3研究结果契约](FUNDAMENTAL_RESEARCH.md)。

## Layer3逐股研究工作区

完成基本面同步后，运行：

```bash
python -m app.cli.research
```

省略运行编号时，它和基本面命令一样自动选择最近一次完整全市场快照。程序把
Top 10研究请求拆成互不影响的工作项：

```text
fundamental/research/
├── work_items/
│   └── 603505/
│       ├── request.json
│       └── result.template.json
├── inbox/
│   └── 603505.json
├── results/
│   └── 603505.json
└── execution_summary.json
```

`work_items` 是外部研究工具的输入，`inbox` 是待校验结果投递区，`results` 只保存
已通过运行编号、输入指纹、字段范围和证据日期校验的逐股结果。某只股票校验失败
只会记录在 `execution_summary.json`，其他股票仍会正常汇总。

当前阶段的默认提供者是本地文件工作区，不会自行搜索网页或生成结论。外部研究
工具需要读取某只股票的 `request.json`，以 `result.template.json` 为格式填写结果，
再保存为：

```text
fundamental/research/inbox/<股票代码>.json
```

投递完成后执行：

```bash
python -m app.cli.research --resume
```

程序会跳过已有 `complete` 结果，继续处理缺失、`partial` 或 `failed` 股票，然后
重新生成批量 `research_results.json` 和最终 `layer3.json`。

也可以直接导入外部工具生成的批量JSON文件，或包含逐股JSON的其他目录：

```bash
python -m app.cli.research --import-results /path/to/results.json
python -m app.cli.research --import-results /path/to/result-directory
```

只处理当前任务中的指定股票：

```bash
python -m app.cli.research --code 603505 600519
```

只读检查已经保存到 `research/results/` 的结果，不创建、覆盖或汇总文件：

```bash
python -m app.cli.research --validate-only
```

参数说明：

| 参数 | 是否必需 | 含义 |
|---|---|---|
| `--run-id` | 否 | 指定历史运行快照；省略时使用最近一次完整运行 |
| `--code` | 否 | 只处理列出的股票；股票必须属于当前Top 10研究任务 |
| `--import-results` | 否 | 指定批量结果JSON或逐股结果目录；省略时读取默认 `inbox` |
| `--resume` | 否 | 复用已有完整结果，只补未完成股票 |
| `--validate-only` | 否 | 对逐股结果做只读校验，不修改任何文件 |
| `--config` | 否 | 指定Layer3评分权重与阈值配置 |
| `--output-dir` | 否 | 指定运行快照所在输出目录；通常无需填写 |

研究入口不访问行情库和基本面数据库，也不能修改Layer1、Layer2、
`financial_quant.json` 或 `research_request.json`。

Ubuntu服务器已配置OpenClaw模型和网页搜索工具时，可调用仓库内置Skill：

```bash
bash scripts/openclaw_research.sh --code 603505
bash scripts/openclaw_research.sh --resume
```

第一条建议用于首次验证一只股票；第二条断点研究当前任务剩余股票。Skill会按
证据等级、截止日期、行业/预期/风险评分规则填写逐股JSON，并在每只完成后立即
调用Python校验。完整安装、参数和 `screen` 后台运行说明见
[OpenClaw Layer3研究接入](OPENCLAW.md)。

## 每日完整流水线与自动执行

需要把技术筛选、按需基本面、Layer3研究和报告连成一次运行时，执行：

```bash
bash scripts/daily_pipeline.sh --resume
```

`--resume`会读取 `output/pipeline_state.json`，已经成功的阶段不会重复执行。每个
运行目录也保存 `fundamental/pipeline_state.json`，便于审计该快照具体完成到了
哪一步。若OpenClaw失败，流水线仍会尽量生成部分报告；修复模型或网络后再次运行
同一命令即可继续。

最终报告保存为：

```text
output/runs/<运行编号>/fundamental/daily_report.json
output/runs/<运行编号>/fundamental/daily_report.md
```

同时归档到 `output/reports/daily/`，并刷新 `output/reports/latest/` 和当周周报。
单独生成指定周报：

```bash
python -m app.cli.report_weekly --week 2026-W37 --top-n 10
```

报告把 `complete`、`rejected`、`partial`、`failed` 和 `pending` 分开统计；缺失研究
不会被当成零分，也不会生成虚假结论。只重新生成某个历史快照的报告可以执行：

```bash
python -m app.cli.report --run-id <运行编号> --top-n 10
```

宿主机安装OpenClaw时，原定时任务安装脚本默认仅预览：

```bash
bash scripts/install_openclaw_automation.sh
bash scripts/install_openclaw_automation.sh --apply
```

默认在 `Asia/Shanghai` 时区的工作日18:00启动，最长运行6小时。同名任务存在时
脚本会停止，避免重复调度。完整命令参数、断点语义、休市日行为和验收方法见
[每日自动流水线](AUTOMATION.md)。

OpenClaw使用Docker时，应由systemd在宿主机生成报告，再由OpenClaw只读读取并推送：

```bash
bash scripts/install_host_pipeline_timer.sh
bash scripts/install_report_automations.sh \
  --compose-dir /home/chen/openclaw \
  --qq-target '<QQ接收目标>'
```

两条命令默认只预览。具体挂载、应用和验收见
[日报、周报与频道发布](REPORTING.md)。

## 常用维护命令

强制重取最近 5 个交易日：

```powershell
python -m app.cli.update --daily --repair-days 5
```

在腾讯模式中，前复权是完整动态序列，因此该命令会重新下载所有股票的完整
窗口；在Tushare模式中只强制重取最近5个交易日。

扫描过去某个历史截面：

```powershell
python -m app.cli.screen --all --end-date 20260911
```

数据库初始化不足 120 个交易日时，部分股票会因为历史长度不足进入
`errors.csv`；建议初始化 250 个交易日。
