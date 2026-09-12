#!/usr/bin/env python3
"""v1.1直接联网筛选器兼容入口。"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from app.legacy.screener_direct_tx import main


if __name__ == "__main__":
    raise SystemExit(main())
