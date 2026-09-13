# 部署教程

本文从一台空机器开始，完成代码、Python环境、行情库、基本面库、OpenClaw和每日
自动任务的部署。项目要求 Python 3.11 或更高版本，所有命令都应在项目根目录执行。

## 1. 部署前选择

先决定个股行情来源。一个行情数据库初始化后会永久绑定一种来源，不能日常切换。

| 场景 | 建议 |
|---|---|
| 没有Tushare Token、复权因子权限低、只需要沪深股票 | 腾讯 `--tx` |
| 需要沪深京、Token具有 `daily` 与 `adj_factor` 正式权限 | Tushare `--tushare` |

建议普通用户使用腾讯模式。基本面数据与这里的选择无关，它使用独立数据库，且只
拉取技术筛选后的少量候选。

部署至少需要：

- Git；
- Python 3.11+；
- 可访问所选行情接口的网络；
- 约数GB可用磁盘空间；
- 可选：OpenClaw、可用模型和网页搜索能力，用于Layer3研究。

## 2. Ubuntu服务器部署

### 2.1 获取代码

首次部署：

```bash
mkdir -p ~/stockAnalyse
cd ~/stockAnalyse
git clone https://github.com/cvbroth/StockAnalyse.git StockAnalyse
cd StockAnalyse
```

如果服务器已经存在仓库：

```bash
cd ~/stockAnalyse/StockAnalyse
git status
git pull --ff-only origin main
```

`--ff-only`只允许快进更新；服务器有未提交修改或分支已经分叉时会停止，避免自动
生成难以察觉的合并提交。

### 2.2 创建Python环境

```bash
sudo apt update
sudo apt install -y git python3 python3-venv screen
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

验证模块入口：

```bash
python -m app.cli.update --help
python -m app.cli.screen --help
python -m app.cli.pipeline --help
```

### 2.3 网络代理（可选）

如果Ubuntu通过Windows代理联网，且Windows地址为 `192.168.0.101:7897`：

```bash
export HTTP_PROXY=http://192.168.0.101:7897
export HTTPS_PROXY=http://192.168.0.101:7897
```

代理软件必须允许局域网访问。先验证端口和Git：

```bash
curl -I https://github.com
git -c http.version=HTTP/1.1 fetch origin
```

不要把含账号密码的代理地址提交到仓库。

## 3. Windows部署

使用PowerShell：

```powershell
git clone https://github.com/cvbroth/StockAnalyse.git
Set-Location StockAnalyse
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

如果PowerShell禁止激活脚本，可以设置当前用户策略：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

也可以不激活，始终使用：

```powershell
.\.venv\Scripts\python.exe -m app.cli.update --help
```

## 4. 初始化行情数据库

### 4.1 腾讯模式

```bash
python -m app.cli.update \
  --init \
  --tx \
  --days 250 \
  --db data/market_tx.db
```

腾讯按股票下载前复权历史，默认并发6只。网络稳定时可以谨慎提高：

```bash
python -m app.cli.update --init --tx --days 250 \
  --db data/market_tx.db --tx-workers 8 --tx-timeout 30
```

### 4.2 Tushare模式

```bash
cp .env.example .env
nano .env
chmod 600 .env
```

`.env`只写：

```dotenv
TUSHARE_TOKEN=实际Token
```

然后初始化：

```bash
python -m app.cli.update \
  --init \
  --tushare \
  --days 250 \
  --db data/market_tushare.db
```

如果 `adj_factor` 只有每小时一次权限，不适合完成全量初始化，应改用腾讯。

### 4.3 断点续传与当前数据库

初始化可以用 `Ctrl+C` 中断。重新执行完全相同的初始化命令会继续未完成部分。
成功初始化会生成本机专用的 `config/project.json`，以后可以省略 `--db`。

如果数据库从其他机器复制而来，把它设为当前数据库：

```bash
python -m app.cli.update --status \
  --db data/market_tx.db \
  --set-current
```

检查状态：

```bash
python -m app.cli.update --status
```

应确认数据源、股票数量、日线日期范围、完整交易日和失败日期均符合预期。

## 5. 分层验收

部署时不要一开始就运行数小时的完整流水线，按层验收更容易定位问题。

### 5.1 技术层

小样本只验证读取和公式，不计算全市场百分位：

```bash
python -m app.cli.screen --symbols 603505 600519 000858
```

随后运行全市场：

```bash
python -m app.cli.screen --all
```

成功后会产生 `output/runs/<运行编号>/` 和
`output/runs/latest_full_market.json`。

### 5.2 基本面层

先只准备候选，不访问财务接口：

```bash
python -m app.cli.fundamentals --top-n 3 --prepare-only
```

确认候选后小规模联网：

```bash
python -m app.cli.fundamentals --top-n 3 --quarters 8
```

正常情况下会生成独立的 `data/fundamentals.db`，不会修改行情库。

### 5.3 Layer3研究

没有OpenClaw时，`layer3.json` 中显示 `pending` 是正常状态。已配置OpenClaw时先
只验收一只候选：

```bash
openclaw --version
openclaw skills check
bash scripts/openclaw_research.sh --code 603505
python -m app.cli.research --validate-only
```

股票代码必须属于本次Top 10研究任务。单股成功后再续跑其余候选：

```bash
bash scripts/openclaw_research.sh --resume
```

## 6. 每日运行

只更新行情并做技术筛选：

```bash
python -m app.cli.daily
```

完整流水线：

```bash
bash scripts/daily_pipeline.sh --resume
```

完整流水线依次执行：

```text
行情更新与全市场筛选 → 基本面同步 → OpenClaw研究 → JSON/Markdown报告
```

状态保存在 `output/pipeline_state.json`。网络或模型失败后再次执行 `--resume`，
已经成功的阶段不会重复运行。

最终报告：

```text
output/runs/<运行编号>/fundamental/daily_report.json
output/runs/<运行编号>/fundamental/daily_report.md
```

## 7. 后台运行

首次验收可以使用screen：

```bash
screen -S stock-pipeline
cd ~/stockAnalyse/StockAnalyse
source .venv/bin/activate
bash scripts/daily_pipeline.sh --resume
```

按 `Ctrl+A`，松开后按 `D` 离开。重新进入：

```bash
screen -d -r stock-pipeline
```

查看会话：

```bash
screen -ls
```

## 8. OpenClaw定时任务

确认手工完整流水线成功后，先预览任务：

```bash
bash scripts/install_openclaw_automation.sh
```

核对绝对项目路径、时区和时间后再创建：

```bash
bash scripts/install_openclaw_automation.sh --apply
```

默认工作日18:00按 `Asia/Shanghai` 精确触发，最长运行6小时，不向聊天频道投递，
运行记录仍保存在OpenClaw和项目输出中。同名任务已存在时脚本会停止。

检查和手工触发：

```bash
openclaw automations list
openclaw automations get <任务ID>
openclaw automations run <任务ID> --wait --wait-timeout 6h
openclaw automations runs <任务ID> --limit 20
```

## 9. 更新部署

```bash
cd ~/stockAnalyse/StockAnalyse
git status
git pull --ff-only origin main
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -q
python -m app.cli.update --status
```

仓库更新不会删除 `data/*.db`、`.env`、`config/project.json` 或 `output/runs/`，这些
运行数据均被Git忽略。升级前仍建议备份两个SQLite数据库。

## 10. 备份与恢复

任务停止后备份：

```bash
mkdir -p ~/stock-backup
cp data/market_tx.db ~/stock-backup/
cp data/fundamentals.db ~/stock-backup/
cp config/project.json ~/stock-backup/
```

SQLite正在写入时不要直接复制主文件。先停止更新任务，或使用SQLite在线备份工具。
恢复后用 `--status --set-current` 重新确认数据库路径。

## 11. 部署验收清单

- `python -m app.cli.update --status` 能读取正确数据库；
- `config/project.json` 指向预期行情库、基本面库和输出目录；
- 小样本扫描成功；
- 全市场扫描生成新的运行编号；
- 基本面 `--prepare-only` 能生成请求文件；
- 联网基本面同步能写入 `fundamentals.db`；
- OpenClaw单股研究通过Python校验；
- 完整流水线生成JSON和Markdown报告；
- 定时任务只存在一份，时区与运行时间正确；
- `.env`、数据库和输出文件没有进入Git暂存区。

常见错误处理见 [故障排查](TROUBLESHOOTING.md)，所有命令参数见
[参数手册](PARAMETERS.md)。
