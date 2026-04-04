#!/usr/bin/env python3
"""Resolve watchlist entities to stable OpenAlex IDs.

This helper script forwards to ``ppb resolve`` from the repository root so the
watchlist can be updated without installing the package globally first.
"""

from __future__ import annotations

import sys
from pathlib import Path

from openalex_paper_bot.cli import main

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

if __name__ == "__main__":
    raise SystemExit(main(["resolve", "--project-root", str(PROJECT_ROOT), *sys.argv[1:]]))
