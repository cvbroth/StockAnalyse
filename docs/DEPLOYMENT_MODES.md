# 部署模式

项目把“谁负责定时”“Python 在哪里运行”“Layer3 如何调用 OpenClaw”分开配置。
分析引擎和数据库格式不随部署模式变化，因此可以切换调度方式而不重新初始化行情库。

## 模式总览

| 模式 | 调度器 | Python 位置 | 研究执行器 | 适用场景 |
|---|---|---|---|---|
| OpenClaw Managed | OpenClaw Automation | Gateway 容器 | `local-openclaw` | 个人内网服务器，默认推荐 |
| Host Managed | systemd 或人工 | Ubuntu 宿主机 | `local-openclaw` 或 `docker-openclaw` | 希望由宿主机统一运维 |
| Docker Boundary | systemd | Ubuntu 宿主机 | `docker-openclaw` | 多用户或高隔离要求 |
| Development | 人工 | 当前终端 | 任意或 `disabled` | 开发、测试、排错 |

`local-openclaw` 的“local”始终指 **Python 流水线所在的环境**。在 OpenClaw
Managed 模式下，它指 Gateway 容器，而不是 Ubuntu 宿主机。

## A. OpenClaw Managed（个人服务器推荐）

```text
OpenClaw Gateway 容器
├── Automation Scheduler
├── QQ Bot
├── OpenClaw Agent
├── /opt/stockanalyse-venv/bin/python
└── /workspace/stockanalyse（项目读写挂载）
       ↓
   每日流水线 → local-openclaw → agent exec → 报告 → QQ
```

此模式不需要 Docker-in-Docker，不挂载 Docker Socket，也不需要额外的 systemd
定时器。OpenClaw 是受信任的自动化管理员，可以读取项目状态、续跑任务和发布报告。

必须满足：

1. Gateway 镜像内有项目专用 Python 环境；
2. 项目目录挂载为 `/workspace/stockanalyse`；
3. 容器内 `openclaw agent exec` 可用；
4. `data/` 和 `output/` 对 Gateway 运行用户可写；
5. 不把宿主机 `.venv` 当作容器虚拟环境使用。

示例文件位于 `deploy/openclaw-managed/`。分层验收顺序：

```bash
bash scripts/check_openclaw_managed.sh
bash scripts/check_openclaw_managed.sh --smoke-agent
bash scripts/run_managed_daily.sh --resume
bash scripts/show_pipeline_status.sh
bash scripts/install_openclaw_managed.sh
bash scripts/install_openclaw_managed.sh --qq-target '<QQ目标>' --apply
```

安装器默认工作日 18:01 触发。它把下面三个运行参数保存进 Automation：

```text
PIPELINE_PYTHON=/opt/stockanalyse-venv/bin/python
A_SHARE_RESEARCH_EXECUTOR=local-openclaw
A_SHARE_RESEARCH_MODEL=<可选；省略则继承 OpenClaw 默认模型>
```

任务成功后，包装脚本调用报告目录中的 `print-latest.sh daily`。只有报告日期等于
容器当前日期时才输出 QQ 短报；休市日或旧报告输出 `NO_REPLY`。周五任务成功后还会
在同一次完成通知中附带当周周报；安装时添加 `--no-weekly` 可以关闭。

日常运维时，OpenClaw可以使用这些稳定入口：

```bash
# 查看四个阶段和最近运行编号
bash scripts/show_pipeline_status.sh

# 从未完成阶段继续；终态任务会开始新一天的流程
bash scripts/run_managed_daily.sh --resume

# 只续跑指定快照的财务、研究和报告，不重新扫描5000多只股票
bash scripts/run_managed_daily.sh --run-id <运行编号> --resume
```

## B. Host Managed

Python 和数据库仍位于 Ubuntu 宿主机，使用 `scripts/install_host_pipeline_timer.sh`
安装 systemd 用户定时器。OpenClaw 可以直接安装在宿主机并使用
`local-openclaw`，也可以通过 `docker-openclaw` 调用容器研究员。

此模式的优点是 Python 环境最传统，缺点是需要同时观察 systemd 和 OpenClaw。

## C. Docker Boundary

宿主机完成行情、筛选、财务量化和契约校验；容器只读 `work_items`、只写
`inbox`。它不能读取数据库或完整项目。详细步骤见 [Docker OpenClaw 边界部署](DOCKER_BOUNDARY.md)。

这是可选的高隔离模式，不再作为个人内网服务器的默认方式。

## 安全底线

即使使用 OpenClaw Managed，也不要挂载：

- `/var/run/docker.sock`；
- 宿主机根目录 `/`；
- 整个 `/home`；
- 与本项目无关的服务配置和数据库。

密钥通过 OpenClaw/Docker 环境或 secrets 提供，不提交 `.env`。项目数据库应定期
备份，Git 保留代码和配置变更历史。

## 切换与回滚

部署模式切换不修改行情库。Managed 模式验证失败时，停用对应 Automation，再恢复
Host Managed 定时器即可。切换执行器后运行指纹会变化，同一交易日也不会错误复用
另一种执行方式生成的研究报告。

从旧部署切换时不要先删除任务：

1. 保留旧任务，构建Gateway镜像并完成基础预检；
2. 使用 `--smoke-agent` 验证一次容器内研究调用；
3. 预览Managed安装器，确认它找到或准备创建 `a-share-daily-pipeline`；
4. `--apply` 后立即人工运行该Automation一次；
5. 确认流水线状态、研究结果和QQ投递都正确；
6. 最后才停用重复的旧完整流水线或systemd timer。

项目的非阻塞文件锁会阻止两条流水线同时写入，但它不能替代最终清理重复计划。
