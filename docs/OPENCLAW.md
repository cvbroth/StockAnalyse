# OpenClaw Layer3研究接入

本项目把OpenClaw限制为Layer3外部研究员。Python继续负责技术筛选、财务量化、
结果契约校验、风险否决和排名；OpenClaw只查资料、整理证据并填写逐股JSON。

当前研究契约为v2：每个评分、摘要、催化、风险和否决都必须映射到具体证据，
并记录模型、Skill、评分规则、研究时间和数据质量异常。旧运行中的v1结果仍可继续
读取，但新v2任务不接受把结果版本改回v1。

官方参考：

- [创建OpenClaw Skill](https://docs.openclaw.ai/tools/creating-skills)
- [OpenClaw Skills](https://docs.openclaw.ai/skills)
- [openclaw agent exec](https://docs.openclaw.ai/cli/agent)

## 前置条件

1. Ubuntu项目已更新到包含 `skills/a-share-fundamental/` 的版本。
2. 项目虚拟环境和依赖已经安装。
3. OpenClaw已经安装，并配置可用模型。
4. OpenClaw运行环境具有浏览器或搜索工具；没有搜索能力时Skill会保持任务
   `pending`，不会伪造资料。
5. 已依次完成全市场筛选和基本面准备：

```bash
python -m app.cli.screen --all
python -m app.cli.fundamentals
```

Skill位于项目工作区的：

```text
skills/a-share-fundamental/
├── SKILL.md
└── references/
    ├── scoring-rubric.md
    └── output-contract.md
```

OpenClaw会从执行工作区的 `skills/` 读取它，因此使用启动脚本时无需复制到用户
主目录。需要检查OpenClaw自身状态时可运行：

```bash
openclaw skills check
openclaw skills info a-share-fundamental
```

如果当前OpenClaw配置没有把项目作为工作区，上述 `info` 可能看不到项目Skill；
这不影响下面的 `agent exec --cwd <项目>` 加载执行工作区Skill。也可以明确安装到
当前Agent工作区：

```bash
openclaw skills install ./skills/a-share-fundamental --as a-share-fundamental
```

本项目不自动执行安装，避免覆盖同名Skill。

如果之前把Skill安装到了OpenClaw自己的工作区，项目更新后应按你的OpenClaw版本
支持的更新/重装方式同步一次；优先让 `agent exec --cwd <项目>` 直接读取项目内Skill，
可以避免服务器长期使用旧副本。

## 第一次建议只研究一只

从项目根目录执行：

```bash
bash scripts/openclaw_research.sh --code 603505
```

若OpenClaw全局默认是日常使用的模型，可以只为这次研究显式覆盖：

```bash
A_SHARE_RESEARCH_MODEL=deepseek/actual-model-id \
bash scripts/openclaw_research.sh --code 603505
```

参数含义：

- `bash`：用Bash解释脚本，不依赖脚本是否具有可执行位。
- `scripts/openclaw_research.sh`：项目提供的OpenClaw启动器。
- `--code 603505`：只处理当前Top 10研究任务中的这一只股票。

启动器会执行等价命令：

```bash
openclaw agent exec "/a-share-fundamental --code 603505" \
  --cwd <当前项目根目录> \
  --model <可选的A_SHARE_RESEARCH_MODEL> \
  --timeout 0
```

其中：

- `agent exec`：运行一次适合服务器和脚本调用的独立Agent任务。
- `/a-share-fundamental`：明确调用本项目Skill。
- `--cwd`：把项目根目录同时设为OpenClaw执行工作区和工具工作目录。
- `--model`：仅当设置 `A_SHARE_RESEARCH_MODEL` 时加入，不修改OpenClaw全局默认。
- `--timeout 0`：关闭 `agent exec` 默认的600秒总时限。多只股票研究可能超过
  10分钟，所以由 `screen` 或人工决定何时中断。

## 研究全部Top 10

```bash
bash scripts/openclaw_research.sh --resume
```

`--resume` 会让Python执行器跳过已经校验成功的 `complete` 股票，只补缺失、
`partial` 或 `failed` 项目。即使SSH断开，已进入 `research/results/` 的逐股结果
也不会丢失。

指定历史运行：

```bash
bash scripts/openclaw_research.sh \
  --run-id 20260911-153000123456 \
  --resume
```

这里的 `--run-id` 是筛选运行快照编号，不是股票代码。

## 放在screen后台运行

创建会话：

```bash
screen -S layer3-research
```

进入会话后运行：

```bash
cd ~/stockAnalyse/StockAnalyse
source .venv/bin/activate
bash scripts/openclaw_research.sh --resume
```

按 `Ctrl+A`，松开后按 `D`，即可退出画面但保留后台任务。重新进入：

```bash
screen -d -r layer3-research
```

查看是否仍在运行：

```bash
screen -ls
```

## 实际文件流

每一只股票按以下顺序处理：

```text
work_items/<代码>/request.json
             ↓ OpenClaw查资料
inbox/<代码>.json
             ↓ Python逐股校验
results/<代码>.json
             ↓ Python汇总
research_results.json
             ↓ Layer3组合器
layer3.json
```

OpenClaw不能直接写 `results/`。只有通过以下条件的结果才能进入该目录：

- 运行编号一致；
- 股票代码和名称一致；
- `input_hash` 一致；
- 分数和状态字段合法；
- `complete` 字段完整；
- 证据日期不晚于运行截止日期。

## 查看结果

只读检查逐股结果：

```bash
python -m app.cli.research --validate-only
```

查看执行摘要：

```bash
python -m json.tool \
  output/runs/<运行编号>/fundamental/research/execution_summary.json
```

最终排名位于：

```text
output/runs/<运行编号>/fundamental/layer3.json
```

`complete` 或 `rejected` 表示已形成Layer3结论；`partial`、`failed` 和 `pending`
都不参与最终排名。

## 当前安全边界

Python能验证字段、日期和输入指纹，但不能自动证明网页内容真实，也不能判断链接
是否后来被修改。因此第一版仍需人工抽查关键证据，尤其是RED风险、否决项和高分
催化。Skill不得输出买卖指令，结果只用于候选研究和后续策略验证。
