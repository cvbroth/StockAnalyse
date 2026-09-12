"""本地筛选命令：python -m app.cli.screen。"""

from __future__ import annotations

from ..services.screening import main


if __name__ == "__main__":
    raise SystemExit(main())
