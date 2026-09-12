"""行情库更新命令：python -m app.cli.update。"""

from __future__ import annotations

from ..services.market_update import main


if __name__ == "__main__":
    raise SystemExit(main())
