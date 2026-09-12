# 常见故障排查

## 筛选时全部股票失败或跳过

先看程序开头打印的数据库路径：

```bash
python -m app.cli.update --status
```

如果实际行情位于 `data/market_tx.db`，但当前配置指向别的文件：

```bash
python -m app.cli.update --status --db data/market_tx.db --set-current
```

质量检查会确认日线、沪深300和最低历史长度，不通过时不会继续全市场扫描。

## 初始化停在股票列表或沪深300

这通常是远端接口或网络代理响应慢。程序默认单次等待30秒并重试。可以调整：

```bash
python -m app.cli.update --daily --metadata-timeout 60
```

不要在任务仍然运行时反复启动多个更新进程。

## Tushare提示没有Token

程序依次读取当前进程环境变量和项目根目录 `.env`：

```bash
export TUSHARE_TOKEN='你的Token'
```

Windows PowerShell：

```powershell
$env:TUSHARE_TOKEN="你的Token"
```

`.env`内容应为 `TUSHARE_TOKEN=实际Token`，不要写PowerShell的 `$env:` 语法。

## adj_factor频率超限

这不是网络重试能解决的问题，而是Token权限限制。程序会识别每分钟或每小时
上限并等待。若只有每小时一次，建议停止任务并换用腾讯数据库。

## Git出现HTTP/2 framing layer错误

先确认代理连通，再临时让Git使用HTTP/1.1：

```bash
git -c http.version=HTTP/1.1 fetch origin
git pull --ff-only origin main
```

`fetch`只更新远端引用，`pull --ff-only`才会把远端提交快进到当前分支。

## Git提示LF将替换为CRLF

这是Windows与Linux换行符提示，不代表添加文件失败。只要 `git status` 显示文件
已暂存，就可以正常提交。不要因为该警告反复执行 `git add`。

## screen会话已经Attached

```bash
screen -d -r stock-daily
```

其中 `-d` 是detach，先从原终端分离；`-r` 是resume，在当前终端恢复。
