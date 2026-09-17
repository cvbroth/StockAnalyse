# Docker OpenClaw边界部署

本页描述可选的高隔离部署模式。个人内网服务器的默认推荐方案是
[OpenClaw Managed](DEPLOYMENT_MODES.md)，各种模式可以在不重建行情库的情况下切换。

本模式把可信的数据处理留在Ubuntu宿主机，只让Docker中的OpenClaw完成需要模型和
网页访问的逐股研究：

```text
Ubuntu宿主机（可信）                    OpenClaw容器（受限）
行情库 → 技术筛选 → 财务量化
             ↓
  work_items/<运行编号>/  ──只读挂载──→ 读取研究任务
                                             ↓
  inbox/<运行编号>/       ←─只写投递─── 生成逐股JSON
             ↓
Python契约校验 → Layer3 → 日报/周报
```

容器不需要挂载 `data/`、行情数据库、基本面数据库、Python应用目录或整个
`output/`。它只能读取研究Skill和任务文件，只能向inbox投递未经信任的原始JSON。
所有JSON回到宿主机后仍要经过现有Python契约校验，不能直接进入Layer3。

## 1. 保持旧部署不变

升级代码后，如果 `config/project.json` 没有 `research_execution`，程序仍使用
`local-openclaw`，命令和升级前相同。可先运行：

```bash
bash scripts/daily_pipeline.sh --run-id <已有运行编号> --resume
```

确认旧模式正常，再决定是否切换Docker边界。不要同时启用旧的OpenClaw完整流水线
自动化和新的宿主机systemd流水线；即使误触发，包装脚本中的 `flock --nonblock`
也会阻止两条流水线同时写入。

## 2. 准备隔离挂载

从 `deploy/openclaw/boundary.env.example` 复制实际路径到OpenClaw Compose目录的
`.env`，再把 `docker-compose.boundary.example.yml` 中三个挂载合并到实际Compose
配置。先创建宿主机目录：

```bash
mkdir -p output/openclaw_exchange/work_items
mkdir -p output/openclaw_exchange/inbox
```

挂载权限必须是：

| 宿主机目录 | 容器目录 | 权限 |
|---|---|---|
| `skills/a-share-fundamental` | `/workspace/stockanalyse/skills/a-share-fundamental` | 只读 |
| `output/openclaw_exchange/work_items` | `/research-exchange/work_items` | 只读 |
| `output/openclaw_exchange/inbox` | `/research-exchange/inbox` | 读写 |

不要把 `data/` 或项目根目录挂进容器。若当前Compose已经挂载整个项目，应先保留旧
模式完成验收，然后在切换窗口替换为上面的最小挂载。

容器必须加载本次升级后的Skill，因为旧Skill不认识 `--boundary-mode`。在实际
OpenClaw Compose目录中先检查；若版本仍旧，再从只读挂载路径重新安装：

```bash
docker compose run -T --rm openclaw-cli skills info a-share-fundamental
docker compose run -T --rm openclaw-cli skills install \
  /workspace/stockanalyse/skills/a-share-fundamental \
  --as a-share-fundamental
```

若实际CLI服务不是 `openclaw-cli`，把命令中的服务名替换为
`docker compose config --services` 显示的名称。

## 3. 配置执行器

参考 `deploy/openclaw/project.docker.example.json`，把 `research_execution` 合并到
本机不入Git的 `config/project.json`。主要字段：

| 字段 | 含义 |
|---|---|
| `executor` | `local-openclaw`、`docker-openclaw`或`disabled` |
| `research_model` | Layer3显式使用的OpenClaw `provider/model`；省略则继承全局默认 |
| `compose_directory` | OpenClaw的Docker Compose目录 |
| `compose_service` | 提供OpenClaw命令行入口的服务名 |
| `compose_action` | `run`创建一次性容器；`exec`进入已运行容器 |
| `exchange_directory` | 宿主机交换目录，默认`output/openclaw_exchange` |
| `container_exchange_directory` | 容器内交换根目录，默认`/research-exchange` |

当前OpenClaw Compose采用CLI一次性服务时用 `run`。如果命令必须在常驻服务内执行，
改用 `exec`，并把 `container_openclaw_binary` 设为容器内的 `openclaw` 可执行文件。
可用以下命令确认服务名：

```bash
cd /home/chen/openclaw
docker compose config --services
docker compose run -T --rm openclaw-cli models list --json
```

先从模型列表复制准确标识，再写入 `research_model`。不要根据产品显示名称猜测
provider前缀；模型变化会进入流水线版本指纹，防止复用另一模型生成的同日报告。

## 4. 分层验收

先只验证参数和Docker命令，不替换定时任务：

```bash
python -m app.cli.pipeline --help
python -m app.cli.pipeline \
  --run-id <已有运行编号> \
  --research-executor docker-openclaw \
  --research-model deepseek/actual-model-id \
  --openclaw-compose-dir /home/chen/openclaw \
  --resume
```

检查：

1. `work_items/<运行编号>`已生成，容器无法修改它；
2. 容器只在`inbox/<运行编号>`产生逐股JSON；
3. 宿主机生成`fundamental/research/results`、`research_results.json`和`layer3.json`；
4. `output/pipeline_state.json`的research阶段包含prepare、agent、validate三个步骤；
5. 状态中保存`runtime_fingerprint`，可追溯当次代码、配置、Skill和执行器版本。

## 5. 切换与回滚

验收后用 `scripts/install_host_pipeline_timer.sh --apply` 让宿主机负责完整流水线，
停用旧的OpenClaw完整流水线自动化，只保留日报和周报推送任务。

回滚不需要还原数据库：把 `config/project.json` 中执行器改回
`local-openclaw`，或临时运行：

```bash
bash scripts/daily_pipeline.sh --research-executor local-openclaw --resume
```

项目配置发生变化后，即使行情日期相同，版本指纹也会阻止错误复用旧报告。
