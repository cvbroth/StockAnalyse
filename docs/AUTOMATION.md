# 每日自动流水线

每日流水线按固定边界依次执行：

```text
行情日常更新与全市场筛选
          ↓
按需财务同步与八季度量化
          ↓
OpenClaw Layer3逐股研究
          ↓
JSON与Markdown研究报告
```

每一步的状态都会原子保存。OpenClaw或网络中途失败后，重新运行 `--resume` 不会
重新执行已经成功的阶段。

OpenClaw官方说明中，Automations负责持久化定时任务，command任务直接运行主机
进程而不额外调用模型。本项目让command任务启动Python流水线，只有研究阶段才
调用 `openclaw agent exec`：

- [OpenClaw Automations](https://docs.openclaw.ai/automation/cron-jobs)
- [Automations CLI](https://docs.openclaw.ai/cli/cron)

## 手工运行一次

Ubuntu项目根目录执行：

```bash
source .venv/bin/activate
python -m app.cli.pipeline
```

也可以使用自动选择虚拟环境的包装脚本：

```bash
bash scripts/daily_pipeline.sh
```

流水线阶段：

1. `app.cli.daily`：更新当前数据库并执行完整全市场扫描。
2. `app.cli.fundamentals`：为最新运行同步Top 30财务数据并量化。
3. `a-share-fundamental`：逐股研究Top 10并写入经过验证的结果。
4. `app.cli.report`：生成最终日报、QQ短报并刷新当周周报。

## 断点续跑

```bash
python -m app.cli.pipeline --resume
```

`--resume`读取：

```text
output/pipeline_state.json
```

并从最后失败的阶段继续。例如前三步已成功但报告生成失败，只会重新生成报告。
如果上一次流水线已经完整结束，`--resume` 会开始新的每日运行，而不是永久停留在
旧快照。

每个运行快照也保存一份状态副本：

```text
output/runs/<运行编号>/fundamental/pipeline_state.json
```

## 处理已有运行快照

```bash
python -m app.cli.pipeline \
  --run-id 20260911-153000123456 \
  --resume
```

指定 `--run-id` 后，程序跳过行情更新和全市场筛选，只执行该快照的基本面、研究
和报告阶段。

## 单独生成报告

```bash
python -m app.cli.report
```

默认读取最近一次完整全市场运行。指定历史运行和状态卡数量：

```bash
python -m app.cli.report \
  --run-id 20260911-153000123456 \
  --top-n 10
```

输出：

```text
output/runs/<运行编号>/fundamental/
├── daily_report.json
└── daily_report.md
```

同时更新面向用户与频道发布的统一目录：

```text
output/reports/
├── daily/<YYYYMMDD>/
├── weekly/<YYYY-Www>/
└── latest/
```

只生成指定周报：

```bash
python -m app.cli.report_weekly --week 2026-W37
```

报告状态为 `partial` 时不会伪造缺失分数，会单独列出待研究、部分和失败股票。

## 流水线参数

| 参数 | 含义 |
|---|---|
| `--resume` | 从上一次非终态流水线的失败阶段继续；终态则开始新运行 |
| `--run-id` | 使用已有快照并跳过行情更新与技术筛选 |
| `--db` | 临时指定行情数据库；通常读取项目配置 |
| `--output-dir` | 临时指定结果目录；通常读取项目配置 |
| `--skip-research` | 跳过OpenClaw并生成部分报告，用于诊断其他阶段 |
| `--report-top-n` | Markdown报告最多显示多少张候选状态卡，默认10 |
| `--research-executor` | 本机、Docker或禁用研究执行器；默认兼容旧本机模式 |
| `--research-model` | 仅为Layer3研究指定OpenClaw `provider/model` |
| `--openclaw-compose-dir` | Docker OpenClaw的Compose目录 |
| `--openclaw-compose-service` | Docker Compose中的CLI服务名 |
| `--openclaw-compose-action` | `run`一次性容器或`exec`常驻容器 |
| `--research-exchange-dir` | 宿主机研究任务/inbox隔离交换目录 |

如果行情截止日期与上一份终态流水线相同，程序会记录
`market_date_unchanged`，跳过财务、研究和报告，复用上一份报告。这可避免周末、
法定休市日或同一天重复运行时浪费外部接口与模型调用。

包装脚本使用非阻塞文件锁（`flock --nonblock`）。如果systemd、旧OpenClaw任务或
人工命令同时触发，只有第一条流水线会运行，其余以退出码75停止。每次状态还保存
代码、分析配置、研究Skill和执行器配置的SHA-256版本指纹；指纹变化时，同一交易日
也不会错误复用旧报告。

研究模型属于执行器配置，也进入版本指纹。可在 `config/project.json` 中固定
`research_execution.research_model`，让OpenClaw日常聊天继续使用全局默认模型，
而Layer3研究始终使用单独的模型。模型标识必须来自 `openclaw models list`。

## 创建OpenClaw定时任务

OpenClaw通过Docker运行并作为个人服务器总控制器时，使用Managed安装器。它在
Gateway容器内部运行流水线，强制使用容器内Python和`local-openclaw`，默认工作日
18:01触发；任务完成后才输出当天QQ短报：

```bash
bash scripts/check_openclaw_managed.sh
bash scripts/install_openclaw_managed.sh
bash scripts/install_openclaw_managed.sh \
  --qq-target '<QQ接收目标>' \
  --apply
```

已存在同名任务时，安装器会原地更新任务定义，不重复创建。完整容器构建和挂载说明
见[部署模式](DEPLOYMENT_MODES.md)。

下面的旧安装器用于OpenClaw直接安装在宿主机的兼容模式。

安装脚本默认只预览，不修改OpenClaw：

```bash
bash scripts/install_openclaw_automation.sh
```

默认计划为：

```text
任务名：a-share-layer3-daily
时间：周一至周五 18:00
时区：Asia/Shanghai
最长运行：6小时
调度偏移：关闭，按设定时间精确触发
外部投递：关闭，输出保留在任务运行记录和项目文件中
```

确认预览中的项目绝对路径正确后创建：

```bash
bash scripts/install_openclaw_automation.sh --apply
```

更改时间，例如工作日18:30：

```bash
bash scripts/install_openclaw_automation.sh \
  --cron '30 18 * * 1-5' \
  --tz Asia/Shanghai \
  --apply
```

脚本创建前会检查同名任务；检测到同名任务时会停止，避免重复执行两份流水线。

查看任务：

```bash
openclaw automations list
```

查看某个任务定义和运行记录：

```bash
openclaw automations get <任务ID>
openclaw automations runs <任务ID> --limit 20
```

手工触发一次进行验收：

```bash
openclaw automations run <任务ID> --wait --wait-timeout 6h
```

## 流水线返回值

- `0`：所有命令执行成功；研究结果本身可能因证据不足而是部分状态。
- `2`：某个阶段失败或OpenClaw研究进程失败；可使用 `--resume`。
- 其他非零值：行情、筛选或下游命令返回的原始错误码。

判断研究是否完整应查看 `daily_report.json` 的 `metadata.status`，不能只看进程返回
值。流水线成功表示执行过程完成，不代表每只股票都有充分证据。

## Docker OpenClaw推送QQ

宿主机先用systemd定时运行完整流水线：

```bash
bash scripts/install_host_pipeline_timer.sh
bash scripts/install_host_pipeline_timer.sh --apply
```

要让研究阶段也安全调用Docker OpenClaw，请先按
[Docker OpenClaw边界部署](DOCKER_BOUNDARY.md)配置执行器和最小挂载。未配置时仍使用
升级前的本机OpenClaw调用，不会自动切换。

`install_openclaw_automation.sh` 创建的是完整研究流水线任务，而且使用
`--no-deliver`，不会向频道发送报告。Docker版OpenClaw的日报和周报推送使用独立
安装器，默认同样只预览：

```bash
bash scripts/install_report_automations.sh \
  --compose-dir /home/chen/openclaw \
  --qq-target '<QQ接收目标>'
```

确认只读挂载和目标后追加 `--apply`。完整说明见
[日报、周报与频道发布](REPORTING.md)。
