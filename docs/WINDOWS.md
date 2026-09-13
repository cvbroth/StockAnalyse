# Windows安装与运行

完整的跨平台部署、数据源选择和验收步骤见 [部署教程](DEPLOYMENT.md)。本文保留
Windows PowerShell常用命令速查。

以下命令使用PowerShell，并假设终端位于项目根目录。

## 创建独立Python环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

如果PowerShell禁止激活脚本，可以只为当前用户调整策略：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

也可以不激活，直接使用 `.\.venv\Scripts\python.exe` 执行后续命令。

## 初始化腾讯数据库

```powershell
python -m app.cli.update --init --tx --days 250 --db data\market_tx.db
```

初始化支持断点续传。中断后重新执行相同命令即可继续。

## 日常运行

```powershell
python -m app.cli.daily
```

只筛选、不联网更新：

```powershell
python -m app.cli.screen --all
```

查看当前数据库：

```powershell
python -m app.cli.update --status
```

## Tushare Token

临时环境变量：

```powershell
$env:TUSHARE_TOKEN="你的Token"
```

或者复制 `.env.example` 为 `.env`，再填写Token。`.env`已经被Git忽略。
