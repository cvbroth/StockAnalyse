# A股上升周期筛选器

将A股历史行情保存在本地SQLite数据库中，再计算趋势结构、均线、量价、突破回踩、
相对沪深300强度和全市场60日收益百分位。

v1.3在原有五项资格筛选后增加100分技术质量排名、过热惩罚、跨日状态变化和
历史20/60日效果评估。

支持两种初始化数据源：

- 腾讯前复权：免费、无需Token，覆盖沪深股票。
- Tushare原始日线加复权因子：需要相应接口权限，覆盖沪深京。

数据源在初始化时绑定到数据库，日常更新不能临时切换，避免不同复权口径混合。

## 快速开始

安装依赖：

```bash
python -m pip install -r requirements.txt
```

腾讯模式初始化：

```bash
python -m app.cli.update --init --tx --days 250 --db data/market_tx.db
```

初始化后，数据库会被保存为项目当前数据库。日常使用无需重复填写路径：

```bash
python -m app.cli.update --status
python -m app.cli.screen --all
python -m app.cli.daily
```

小样本检查不会强制全市场百分位：

```bash
python -m app.cli.screen --symbols 603505 600519 000858
```

五项筛选参数集中在 `config/analysis/layer1.toml`。配置带有版本号，运行结果会
记录实际使用的版本和路径。需要临时使用另一份配置时：

```bash
python -m app.cli.screen --all --analysis-config config/analysis/layer1.toml
```

命令行提供的单项参数优先于TOML配置。

查看A池、B池质量排名后，如果只调整第二层参数，可以复用已有运行快照：

```bash
python -m app.cli.screen --from-layer 2 --run-id <运行编号>
```

积累到足够的未来行情后评估评分有效性：

```bash
python -m app.cli.evaluate --run-id <运行编号> --horizons 20 60
```

为某次全市场运行准备按需基本面数据清单：

```bash
python -m app.cli.fundamentals
```

该命令从Layer2候选中选取配置的Top N，按需获取最近8个季度财务指标，写入独立的
`data/fundamentals.db`，并生成盈利动量、经营质量和数据覆盖率。首次只想检查请求
范围、不联网时可追加 `--prepare-only`。命令默认使用最近一次成功的全市场运行；
只有处理历史快照时才需要 `--run-id <运行编号>`。基本面同步不会修改已有Layer1/2
结果。

把Layer3研究请求拆成可恢复的逐股工作项：

```bash
python -m app.cli.research
```

该命令不会自行编造研究结论。它会为默认Top 10建立独立工作项和结果投递目录，
校验外部工具放入的逐股JSON，隔离单股错误，再汇总 `research_results.json` 并
重算 `layer3.json`。继续处理未完成股票时使用：

```bash
python -m app.cli.research --resume
```

Ubuntu服务器已经配置OpenClaw模型和搜索工具后，可以让项目Skill逐股查证并投递：

```bash
bash scripts/openclaw_research.sh --code 603505
bash scripts/openclaw_research.sh --resume
```

`config/project.json` 可为Layer3单独设置 `research_execution.research_model`。这样
OpenClaw日常聊天可以继续使用全局默认模型，而股票研究显式使用另一模型；模型切换
也会进入流水线版本指纹，避免错误复用旧报告。

执行包含行情、筛选、基本面、OpenClaw和报告的完整每日流水线：

```bash
bash scripts/daily_pipeline.sh --resume
```

完整流水线会同时生成可读日报、QQ短报和当周汇总。日报V3包含筛选漏斗、中文关注
分层、评分拆解、升级距离、跨日排名变化和结构化证据索引。也可以单独重建：

```bash
python -m app.cli.report
python -m app.cli.report_weekly --week 2026-W37
```

统一报告中心位于 `output/reports/`。Docker版OpenClaw定时推送QQ的只读挂载、
预览和安装步骤见[日报、周报与频道发布](docs/REPORTING.md)。

如果Python流水线运行在Ubuntu宿主机、OpenClaw运行在Docker中，推荐使用隔离研究
交换目录：容器只读研究任务、只写原始JSON，不能读取两个SQLite数据库。兼容切换、
最小挂载和回滚步骤见[Docker OpenClaw边界部署](docs/DOCKER_BOUNDARY.md)。

Ubuntu宿主机每日生成报告的systemd定时器也默认只预览：

```bash
bash scripts/install_host_pipeline_timer.sh
bash scripts/install_host_pipeline_timer.sh --apply
```

默认工作日18:00自动执行的OpenClaw任务可先预览、再创建：

```bash
bash scripts/install_openclaw_automation.sh
bash scripts/install_openclaw_automation.sh --apply
```

旧命令 `app/update_market.py`、`app/screener_v1_2.py` 和 `app/run_daily.py`
仍然可用，但新部署建议使用上面的模块化入口。

## 文档

- [完整部署教程](docs/DEPLOYMENT.md)
- [命令行与配置参数手册](docs/PARAMETERS.md)
- [完整使用手册](docs/USER_GUIDE.md)
- [Windows安装与运行](docs/WINDOWS.md)
- [Ubuntu服务器安装与后台运行](docs/UBUNTU.md)
- [数据源选择与复权方式](docs/DATA_SOURCES.md)
- [项目架构](docs/ARCHITECTURE.md)
- [分层分析引擎](docs/ANALYSIS_ENGINE.md)
- [技术分析公式汇总](docs/TECHNICAL_FORMULAS.md)
- [基本面分析公式汇总](docs/FUNDAMENTAL_FORMULAS.md)
- [Layer3研究结果契约](docs/FUNDAMENTAL_RESEARCH.md)
- [OpenClaw Layer3研究接入](docs/OPENCLAW.md)
- [每日自动流水线](docs/AUTOMATION.md)
- [日报、周报与频道发布](docs/REPORTING.md)
- [Docker OpenClaw边界部署](docs/DOCKER_BOUNDARY.md)
- [常见故障排查](docs/TROUBLESHOOTING.md)
- [开发与测试](docs/DEVELOPMENT.md)

## 输出

默认写入 `output/`：

```text
candidates.json
candidates.csv
technical_pass_5of5.json
watchlist_4of5.json
technical_ranked_5of5.json
technical_top.json
watchlist_ranked_4of5.json
transitions.json
errors.csv
runs/<运行编号>/fundamental/request.json
runs/<运行编号>/fundamental/sync_summary.json
runs/<运行编号>/fundamental/financial_quant.json
runs/<运行编号>/fundamental/research_request.json
runs/<运行编号>/fundamental/research_results.template.json
runs/<运行编号>/fundamental/research/work_items/<股票代码>/request.json
runs/<运行编号>/fundamental/research/work_items/<股票代码>/result.template.json
runs/<运行编号>/fundamental/research/inbox/<股票代码>.json
runs/<运行编号>/fundamental/research/results/<股票代码>.json
runs/<运行编号>/fundamental/research/execution_summary.json
runs/<运行编号>/fundamental/research_results.json
runs/<运行编号>/fundamental/layer3.json
runs/<运行编号>/fundamental/daily_report.json
runs/<运行编号>/fundamental/daily_report.md
runs/<运行编号>/fundamental/pipeline_state.json
reports/daily/<YYYYMMDD>/report.json
reports/daily/<YYYYMMDD>/report.md
reports/daily/<YYYYMMDD>/qq.txt
reports/weekly/<YYYY-Www>/report.json
reports/weekly/<YYYY-Www>/report.md
reports/weekly/<YYYY-Www>/qq.txt
reports/latest/daily-qq.txt
reports/latest/weekly-qq.txt
openclaw_exchange/work_items/<运行编号>/<股票代码>/
openclaw_exchange/inbox/<运行编号>/<股票代码>.json
pipeline_state.json
```

本项目输出的是技术条件筛选结果，不构成投资建议。实盘使用前应自行回测并评估
停牌、涨跌停、交易成本、滑点和数据更新时间等因素。
