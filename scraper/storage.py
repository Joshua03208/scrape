"""Persist results to a single-file SQLite database, plus CSV/JSON export.

SQLite is a "file database": the entire store is one ``.sqlite`` file on disk
with no server to run. That keeps the tool self-contained and easy to back up
-- just copy the file. CSV/JSON exports are there for opening in Excel/Sheets.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .extractor import Record

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    site         TEXT    NOT NULL,
    part_number  TEXT    NOT NULL,
    price        REAL    NOT NULL,
    currency     TEXT    NOT NULL DEFAULT 'USD',
    raw_price    TEXT,
    description  TEXT,
    url          TEXT    NOT NULL,
    scraped_at   TEXT    NOT NULL,
    -- One row per part: re-scraping the same part updates it in place.
    UNIQUE(site, part_number)
);
CREATE INDEX IF NOT EXISTS idx_prices_part ON prices(part_number);
CREATE INDEX IF NOT EXISTS idx_prices_site ON prices(site);
"""


class Storage:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def save(self, site: str, records: Iterable[Record]) -> int:
        """Upsert records; returns how many rows were written/updated."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = [
            (site, r.part_number, r.price, r.currency, r.raw_price,
             r.description, r.url, now)
            for r in records
        ]
        if not rows:
            return 0
        # Latest scrape wins for a given (site, part_number).
        self.conn.executemany(
            """
            INSERT INTO prices
                (site, part_number, price, currency, raw_price,
                 description, url, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(site, part_number) DO UPDATE SET
                price=excluded.price,
                currency=excluded.currency,
                raw_price=excluded.raw_price,
                description=excluded.description,
                url=excluded.url,
                scraped_at=excluded.scraped_at
            """,
            rows,
        )
        self.conn.commit()
        return len(rows)

    def all_rows(self) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT site, part_number, price, currency, raw_price, "
            "description, url, scraped_at "
            "FROM prices ORDER BY site, part_number"
        )
        return cur.fetchall()

    def export_csv(self, path: str | Path) -> int:
        rows = self.all_rows()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                ["site", "part_number", "price", "currency", "raw_price",
                 "description", "url", "scraped_at"]
            )
            for r in rows:
                writer.writerow([r[k] for k in r.keys()])
        return len(rows)

    def export_json(self, path: str | Path) -> int:
        rows = [dict(r) for r in self.all_rows()]
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        return len(rows)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
