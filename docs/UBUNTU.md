# Ubuntu服务器安装与后台运行

从空服务器开始的完整流程、分层验收、备份与定时任务见
[部署教程](DEPLOYMENT.md)。本文保留Ubuntu常用命令速查。

## 创建环境

```bash
cd ~/stockAnalyse/StockAnalyse
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

更新代码后，如果依赖文件发生变化，再执行一次最后一条安装命令。

## 关联已有腾讯数据库

如果 `data/market_tx.db` 已经初始化完成，无需重新下载：

```bash
python -m app.cli.update --status --db data/market_tx.db --set-current
```

以后直接使用项目配置中的数据库：

```bash
python -m app.cli.update --status
python -m app.cli.screen --all
python -m app.cli.daily
```

需要进一步执行基本面、OpenClaw研究并生成最终报告时，使用完整流水线：

```bash
bash scripts/daily_pipeline.sh --resume
```

创建工作日18:00自动运行任务前先预览，再应用：

```bash
bash scripts/install_openclaw_automation.sh
bash scripts/install_openclaw_automation.sh --apply
```

完整说明见 [每日自动流水线](AUTOMATION.md)。

## 使用screen后台运行

创建会话：

```bash
screen -S stock-daily
```

启动任务：

```bash
source .venv/bin/activate
python -m app.cli.daily
```

按 `Ctrl+A`，松开后按 `D`，即可离开会话但保持程序运行。

重新进入：

```bash
screen -r stock-daily
```

查看会话列表：

```bash
screen -ls
```

如果提示会话已经Attached，可强制从原终端分离并进入：

```bash
screen -d -r stock-daily
```

## 通过Windows代理访问网络

假设Windows代理地址是 `192.168.0.101:7897`，临时设置：

```bash
export HTTP_PROXY=http://192.168.0.101:7897
export HTTPS_PROXY=http://192.168.0.101:7897
```

先确认Ubuntu能访问Windows主机和该端口。代理软件还必须允许局域网连接。
不要把代理环境变量写进仓库中的公共配置文件。
