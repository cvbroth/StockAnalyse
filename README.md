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

旧命令 `app/update_market.py`、`app/screener_v1_2.py` 和 `app/run_daily.py`
仍然可用，但新部署建议使用上面的模块化入口。

## 文档

- [完整使用手册](docs/USER_GUIDE.md)
- [Windows安装与运行](docs/WINDOWS.md)
- [Ubuntu服务器安装与后台运行](docs/UBUNTU.md)
- [数据源选择与复权方式](docs/DATA_SOURCES.md)
- [项目架构](docs/ARCHITECTURE.md)
- [分层分析引擎](docs/ANALYSIS_ENGINE.md)
- [Layer3研究结果契约](docs/FUNDAMENTAL_RESEARCH.md)
- [OpenClaw Layer3研究接入](docs/OPENCLAW.md)
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
```

本项目输出的是技术条件筛选结果，不构成投资建议。实盘使用前应自行回测并评估
停牌、涨跌停、交易成本、滑点和数据更新时间等因素。
