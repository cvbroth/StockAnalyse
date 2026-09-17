# OpenClaw Managed 部署文件

这里的文件用于把 StockAnalyse 运行环境加入现有 OpenClaw Gateway 镜像。它们是
示例，不会自动修改服务器上的 OpenClaw Compose 项目。

1. 把 `managed.env.example` 中的值合并到 OpenClaw 部署使用的 `.env`；
2. 把 `docker-compose.override.example.yml` 的服务内容合并到实际 Gateway 服务；
3. 服务名不是 `openclaw-gateway` 时使用实际名称；
4. 重新构建并启动 Gateway；
5. 进入 Gateway 容器，执行 `bash /workspace/stockanalyse/scripts/check_openclaw_managed.sh`；
6. 通过后再预览和安装 Automation。

镜像内虚拟环境固定在 `/opt/stockanalyse-venv`，避免挂载宿主机 `.venv`。如果基础
镜像不是 Debian/Ubuntu 系列，需要把 Dockerfile 中的 `apt-get` 改成对应包管理器。

完整模式比较、切换和回滚见 `docs/DEPLOYMENT_MODES.md`。
