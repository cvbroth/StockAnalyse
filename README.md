# A股上升周期筛选器

将A股历史行情保存在本地SQLite数据库中，再计算趋势结构、均线、量价、突破回踩、
相对沪深300强度和全市场60日收益百分位。

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

旧命令 `app/update_market.py`、`app/screener_v1_2.py` 和 `app/run_daily.py`
仍然可用，但新部署建议使用上面的模块化入口。

## 文档

- [完整使用手册](docs/USER_GUIDE.md)
- [Windows安装与运行](docs/WINDOWS.md)
- [Ubuntu服务器安装与后台运行](docs/UBUNTU.md)
- [数据源选择与复权方式](docs/DATA_SOURCES.md)
- [项目架构](docs/ARCHITECTURE.md)
- [常见故障排查](docs/TROUBLESHOOTING.md)
- [开发与测试](docs/DEVELOPMENT.md)

## 输出

默认写入 `output/`：

```text
candidates.json
candidates.csv
technical_pass_5of5.json
watchlist_4of5.json
errors.csv
```

本项目输出的是技术条件筛选结果，不构成投资建议。实盘使用前应自行回测并评估
停牌、涨跌停、交易成本、滑点和数据更新时间等因素。
