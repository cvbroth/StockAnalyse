# 日报、周报与频道发布

报告层只读取不可变运行快照，不访问行情或财务接口，也不重新计算Layer1、Layer2或
Layer3分数。Python负责确定数字和事实，OpenClaw只负责定时读取已经生成的短报并
投递到频道。

## 1. 生成报告

完整每日流水线最后会调用：

```bash
python -m app.cli.report
```

这个命令生成指定运行的日报，并刷新该日报所在周的周汇总。单独处理历史快照：

```bash
python -m app.cli.report \
  --run-id 20260911-153000123456 \
  --top-n 10
```

只重新生成周报：

```bash
python -m app.cli.report_weekly
python -m app.cli.report_weekly --week 2026-W37 --top-n 10
```

`--week` 使用ISO周编号：四位年份、字母 `W` 和两位周数。省略时使用最近一份
日报所属周。同一交易日若存在多个运行快照，周报只采用最后生成的日报。

## 2. 报告目录

旧的运行快照路径继续保留：

```text
output/runs/<运行编号>/fundamental/
├── daily_report.json
└── daily_report.md
```

面向用户和发布系统的新报告中心：

```text
output/reports/
├── daily/<YYYYMMDD>/
│   ├── report.json
│   ├── report.md
│   ├── qq.txt
│   └── publication.json
├── weekly/<YYYY-Www>/
│   ├── report.json
│   ├── report.md
│   ├── qq.txt
│   └── publication.json
├── latest/
│   ├── daily.json
│   ├── daily.md
│   ├── daily-qq.txt
│   ├── daily-period.txt
│   ├── weekly.json
│   ├── weekly.md
│   ├── weekly-qq.txt
│   └── weekly-period.txt
└── print-latest.sh
```

用途：

- `report.json`：程序使用的权威结构化报告；
- `report.md`：详细人工阅读版本；
- `qq.txt`：适合频道消息的精简版本；
- `publication.json`：报告ID、内容SHA-256和文件清单；
- `latest/`：无需知道运行编号即可找到最新版；
- `print-latest.sh`：供Docker OpenClaw定时任务安全读取短报。

重新生成同一份报告时，若报告事实没有变化，发布内容SHA-256保持不变。实际频道
投递状态和失败原因以OpenClaw Automation运行记录为准。

## 3. 日报内容（V3）

日报包含：

- 30秒结论与“完整仅代表流程完整”的状态说明；
- 有效分析、5/5、4/5、Layer2、财务量化和Layer3的完整筛选漏斗；
- 重点关注、持续跟踪、观察、风险否决等中文关注分层；
- Layer2到Layer3的重排、与上一交易日相比的排名和最终分变化；
- 四项正向得分贡献、正向总分、风险扣分、最终分和下一等级距离；
- 财务覆盖季度数、结构化证据数量、一/二级证据数量和最新证据日期；
- 候选催化、主要风险、风险否决、未完成研究和可点击的证据索引。

跨日比较默认选择当前数据截止日前最近一份已生成日报。同一交易日重新生成报告时，
不会把旧的同日报告误当成上一交易日。评分拆解只有在运行快照记录的基本面配置版本
与当前配置版本一致时才显示权重贡献，避免用新参数错误解释旧快照。

报告为 `partial` 时不会伪造缺失分数，QQ短报会明确显示“部分完成”。
QQ短报默认只展示前三名、中文关注级别、升级距离和首要风险；完整证据继续保留在
`report.md` 和 `report.json` 中。

## 4. 周报内容

周报聚合当周已生成日报，包括：

- 每个交易日的有效分析、5/5、4/5、Layer2和Layer3数量；
- 周末较周初新进入和退出的候选；
- 每天持续存在的候选；
- 入选天数、周初排名、周末排名、最佳排名和排名变化；
- 周末重点候选短表。

当前周报只汇总已经存在的报告事实，不补算未来收益。历史20/60日效果仍使用
`app.cli.evaluate`，避免把事后数据混入当时的研究报告。

## 5. Docker OpenClaw只读接入

### 5.1 宿主机定时生成报告

股票数据库和Python环境位于Ubuntu宿主机，因此由systemd用户定时器运行完整流水线，
OpenClaw不直接操作数据库。安装器默认只预览：

```bash
bash scripts/install_host_pipeline_timer.sh
```

确认项目目录、时间和最长运行时间后：

```bash
bash scripts/install_host_pipeline_timer.sh --apply
```

默认工作日18:00运行，最长6小时。调整时间：

```bash
bash scripts/install_host_pipeline_timer.sh \
  --calendar 'Mon..Fri *-*-* 18:30:00 Asia/Shanghai' \
  --timeout-seconds 21600 \
  --apply
```

查看状态和日志：

```bash
systemctl --user status a-share-daily-pipeline.timer
journalctl --user -u a-share-daily-pipeline.service -n 200 --no-pager
```

服务器用户退出登录后仍需运行用户定时器时，可由管理员检查并启用该用户的linger。
这属于服务器级权限设置，项目安装器不会自动修改。

### 5.2 只读报告挂载

先至少生成一次报告：

```bash
cd /home/chen/stockAnalyse/StockAnalyse
source .venv/bin/activate
python -m app.cli.report
```

在OpenClaw部署目录的环境配置中增加只读挂载。宿主机路径按实际部署修改：

```dotenv
OPENCLAW_EXTRA_MOUNTS=/home/chen/stockAnalyse/StockAnalyse/output/reports:/reports:ro
OPENCLAW_TZ=Asia/Shanghai
```

重新执行OpenClaw官方Docker setup后，确认两个服务都使用同一组Compose文件和
挂载。不要把 `.env`、`data/`、数据库或Docker Socket暴露给报告发布任务。

容器内预检：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.extra.yml \
  run -T --rm --entrypoint sh openclaw-cli \
  -lc 'test -r /reports/print-latest.sh && sh /reports/print-latest.sh daily'
```

报告不是当天最新报告时，脚本输出 `NO_REPLY`，OpenClaw不会推送过期日报。周报按
容器当前的ISO周检查，因此容器时区必须为 `Asia/Shanghai`。

## 6. QQBot和定时推送

QQBot应先在OpenClaw中完成插件、账号和接收目标配置。项目不保存AppSecret、Token
或QQ目标。检查频道：

```bash
docker compose run -T --rm openclaw-cli channels status --probe
```

安装器默认只预览：

```bash
bash scripts/install_report_automations.sh \
  --compose-dir /home/chen/openclaw \
  --qq-target '<QQ接收目标>'
```

确认以下信息后再创建：

```bash
bash scripts/install_report_automations.sh \
  --compose-dir /home/chen/openclaw \
  --qq-target '<QQ接收目标>' \
  --apply
```

默认任务：

```text
a-share-daily-report   工作日19:00  读取当日QQ短报
a-share-weekly-report  周五20:00    读取当周QQ短报
```

修改时间：

```bash
bash scripts/install_report_automations.sh \
  --compose-dir /home/chen/openclaw \
  --qq-target '<QQ接收目标>' \
  --daily-cron '30 19 * * 1-5' \
  --weekly-cron '30 20 * * 5' \
  --tz Asia/Shanghai \
  --apply
```

安装器会先检查重名任务，存在任意重名时不会创建新任务。它使用命令型Automation
直接输出Python已经生成的 `qq.txt`，不额外调用模型，也不允许OpenClaw修改报告。

查看执行和投递状态：

```bash
docker compose run -T --rm openclaw-cli automations list
docker compose run -T --rm openclaw-cli automations runs <任务ID> --limit 20
```

OpenClaw官方参考：

- [Automations](https://docs.openclaw.ai/automation/cron-jobs)
- [Automations CLI](https://docs.openclaw.ai/cli/cron)
- [QQBot](https://docs.openclaw.ai/channels/qqbot)

## 7. 推荐时间顺序

```text
18:00  宿主机完整每日流水线开始
        行情 → 技术 → 财务 → Layer3 → 日报 → 周报截至今日

19:00  OpenClaw推送当日日报

周五20:00 OpenClaw推送当周周报
```

若完整流水线可能超过一小时，应把推送时间后移。推送脚本发现报告日期不匹配时会
保持静默，不会误发上一交易日或上一周报告。
