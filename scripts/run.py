#!/usr/bin/env python3
"""本地运行入口：自动加载 .env、设置 PYTHONPATH。

用法：
    python3 scripts/run.py --dry-run
    python3 scripts/run.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path) -> None:
    """极简 .env 加载器，避免引入 python-dotenv 依赖。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    load_dotenv(ROOT / ".env")
    sys.path.insert(0, str(ROOT / "src"))
    from paper_radar.__main__ import main as radar_main

    return radar_main()


if __name__ == "__main__":
    sys.exit(main())
