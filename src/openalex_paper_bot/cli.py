"""Expose the ``ppb`` command-line interface for the paper bot.

The CLI is intentionally small and maps directly to the main operational tasks:
running the daily digest, resolving watchlist IDs, sending a test message, and
resetting local state.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from openalex_paper_bot.config import find_project_root
from openalex_paper_bot.openalex import field_key, openalex_key
from openalex_paper_bot.runner import resolve_watchlist, run, send_test_message
from openalex_paper_bot.storage import reset_state

COMMAND_NAMES = {"run", "resolve", "test-message", "reset-state"}
HELP_FLAGS = {"-h", "--help"}

_PACKAGE_PREFIX = "openalex_paper_bot."


class _LogFormatter(logging.Formatter):
    """Strip the package prefix from logger names for compact output."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record with a shortened module name.

        Args:
            record: Log record to format.

        Returns:
            The formatted log line with the package prefix removed.

        """
        if record.name.startswith(_PACKAGE_PREFIX):
            record.name = record.name[len(_PACKAGE_PREFIX) :]
        return super().format(record)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser.

    Returns:
        The configured argument parser for the ``ppb`` command.

    """
    parser = argparse.ArgumentParser(
        description="Daily OpenAlex paper alerts via Telegram. With no subcommand, `ppb` defaults to `run`."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Fetch papers and send a Telegram digest.")
    run_parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Path to the repo root. Defaults to the nearest directory with watchlist.yaml.",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the digest to stdout instead of sending to Telegram. Does not update state.",
    )

    resolve_parser = subparsers.add_parser(
        "resolve",
        help="Resolve watchlist names, ORCIDs, RORs, and field names to stable OpenAlex IDs.",
    )
    resolve_parser.add_argument("--project-root", type=Path, default=None)
    resolve_parser.add_argument(
        "--write",
        action="store_true",
        help="Write resolved OpenAlex IDs back into watchlist.yaml.",
    )

    test_parser = subparsers.add_parser(
        "test-message",
        help="Send a Telegram test message with the configured bot.",
    )
    test_parser.add_argument("--project-root", type=Path, default=None)
    test_parser.add_argument("--text", default=None, help="Optional custom Telegram message.")

    reset_parser = subparsers.add_parser(
        "reset-state",
        help="Reset data/state.json so the bot behaves like a fresh first run.",
    )
    reset_parser.add_argument("--project-root", type=Path, default=None)
    reset_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Reset without interactive confirmation.",
    )
    return parser


def normalize_argv(argv: Sequence[str] | None = None) -> list[str]:
    """Normalize argv so bare ``ppb`` behaves like ``ppb run``.

    Args:
        argv: Optional argument vector. When omitted, arguments are read from
            ``sys.argv``.

    Returns:
        An argument vector with the default command applied when appropriate.

    """
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if not raw_args:
        return ["run"]
    if raw_args[0] in COMMAND_NAMES or raw_args[0] in HELP_FLAGS:
        return raw_args
    return ["run", *raw_args]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Optional argument vector. When omitted, arguments are read from
            ``sys.argv``.

    Returns:
        A process exit code.

    """
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        _LogFormatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logging.root.addHandler(handler)
    logging.root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    parser = build_parser()
    args = parser.parse_args(normalize_argv(argv))

    try:
        if args.command == "run":
            run(project_root=args.project_root, dry_run=args.dry_run)
            return 0

        if args.command == "resolve":
            config, resolved_targets, resolved_topic_fields = resolve_watchlist(
                project_root=args.project_root,
                write=args.write,
            )
            for target in resolved_targets:
                print(f"{target.type}: {target.name} -> {openalex_key(target.openalex_id)} ({target.resolved_name})")
            for field in resolved_topic_fields:
                print(f"field: {field.name} -> {field_key(field.openalex_id)} ({field.resolved_name})")
            if args.write:
                print(f"Updated {config.watchlist_path}")
            return 0

        if args.command == "test-message":
            send_test_message(project_root=args.project_root, text=args.text)
            print("Sent Telegram test message.")
            return 0

        if args.command == "reset-state":
            project_root = find_project_root(args.project_root)
            state_path = project_root / "data" / "state.json"
            if not args.yes:
                prompt = f"Reset state at {state_path}? This can resend old papers. [y/N]: "
                confirmation = input(prompt).strip().casefold()
                if confirmation not in {"y", "yes"}:
                    print("Aborted.")
                    return 0
            reset_state(state_path)
            print(f"Reset state: {state_path}")
            return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1
