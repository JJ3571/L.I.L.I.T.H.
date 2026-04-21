#!/usr/bin/env python3
"""
Thin wrappers around pg_dump / pg_restore for this project.

Prerequisites:
  - libpq client tools on PATH (e.g. brew install libpq && brew link --force libpq)
  - DATABASE_URL in the environment

Examples:
  uv run python scripts/postgres_dump_and_restore_helpers.py dump --output /tmp/bot.dump
  uv run python scripts/postgres_dump_and_restore_helpers.py restore --input /tmp/bot.dump --clean

Uses custom format (-Fc) so pg_restore can select objects. For plain SQL, use pg_dump -Fp.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys


def _pg_dump_cmd(dsn: str, output: str, *, plain: bool) -> list[str]:
    fmt = ["-Fp", "--no-owner", "--no-acl"] if plain else ["-Fc", "--no-owner", "--no-acl"]
    return ["pg_dump", *fmt, "-f", output, dsn]


def _pg_restore_cmd(dsn: str, input_path: str, *, clean: bool, if_exists: bool) -> list[str]:
    cmd = ["pg_restore", "--no-owner", "--no-acl", "-d", dsn]
    if clean:
        cmd.append("--clean")
    if if_exists:
        cmd.append("--if-exists")
    cmd.append(input_path)
    return cmd


def main() -> int:
    p = argparse.ArgumentParser(description="pg_dump / pg_restore helpers")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("dump", help="Run pg_dump to a file")
    d.add_argument("--output", "-o", required=True, help="Output file path")
    d.add_argument(
        "--plain-sql",
        action="store_true",
        help="Use plain SQL (-Fp) instead of custom format (-Fc)",
    )

    r = sub.add_parser("restore", help="Run pg_restore from a custom-format dump")
    r.add_argument("--input", "-i", required=True)
    r.add_argument("--clean", action="store_true", help="Pass --clean to pg_restore")
    r.add_argument("--if-exists", action="store_true", help="Pass --if-exists (with --clean)")

    args = p.parse_args()
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        print("DATABASE_URL is required.", file=sys.stderr)
        return 1

    if args.cmd == "dump":
        cmd = _pg_dump_cmd(dsn, args.output, plain=args.plain_sql)
    else:
        cmd = _pg_restore_cmd(dsn, args.input, clean=args.clean, if_exists=args.if_exists)

    print("Running:", " ".join(shlex.quote(c) for c in cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
