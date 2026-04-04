"""Run the package CLI via ``python -m openalex_paper_bot``.

This module forwards directly to ``openalex_paper_bot.cli.main`` so the package
can be executed both as a module and through the installed ``ppb`` console
script.
"""

from __future__ import annotations

from openalex_paper_bot.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
