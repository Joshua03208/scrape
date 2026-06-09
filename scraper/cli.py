"""Command-line entry point.

Examples
--------
Scrape one site:
    python -m scraper.cli run config/sites/example.yaml

Scrape every site config in a folder:
    python -m scraper.cli run config/sites/

Export the collected data to CSV:
    python -m scraper.cli export --format csv --out output/prices.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import load_site_config
from .pipeline import run_site
from .storage import Storage

DEFAULT_DB = "output/prices.sqlite"


def _load_dotenv() -> None:
    """Minimal .env loader so login creds work without extra deps."""
    env = Path(".env")
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        import os
        os.environ.setdefault(key.strip(), value.strip())


def _site_files(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(p for p in path.glob("*.y*ml"))
    return [path]


def cmd_run(args: argparse.Namespace) -> int:
    _load_dotenv()
    files = _site_files(Path(args.config))
    if not files:
        print(f"No site configs found at {args.config}", file=sys.stderr)
        return 1

    grand_total = 0
    with Storage(args.db) as storage:
        for f in files:
            try:
                config = load_site_config(f)
            except Exception as exc:
                print(f"Skipping {f}: {exc}", file=sys.stderr)
                continue
            grand_total += run_site(config, storage)
    print(f"Done. {grand_total} record(s) saved to {args.db}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    with Storage(args.db) as storage:
        if args.format == "csv":
            n = storage.export_csv(args.out)
        else:
            n = storage.export_json(args.out)
    print(f"Exported {n} row(s) to {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scraper", description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite file path")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Crawl one site file or a folder of them")
    p_run.add_argument("config", help="Path to a site .yaml or a folder of them")
    p_run.set_defaults(func=cmd_run)

    p_exp = sub.add_parser("export", help="Export collected data")
    p_exp.add_argument("--format", choices=["csv", "json"], default="csv")
    p_exp.add_argument("--out", default="output/prices.csv")
    p_exp.set_defaults(func=cmd_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
