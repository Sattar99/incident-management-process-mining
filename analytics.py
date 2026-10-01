"""
analytics.py : build every reported metric from PostgreSQL.

PostgreSQL is the single source of truth. The CSVs this writes are exports for
Power BI and for quick inspection, not intermediate artifacts.

Run order:
    python etl_pipeline.py     # raw CSV -> incident_data + incidents_clean.csv
    python analytics.py        # incident_data -> sql/*.sql -> data/*.csv

Usage
-----
    python analytics.py                    # run all report queries
    python analytics.py --sql 03_bottlenecks.sql   # run one file
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import URL, create_engine, text

SQL_DIR = Path("sql")
DATA_DIR = Path("data")

STATEMENT_SPLIT = re.compile(r";\s*(?:\n|$)")


def get_engine():
    return create_engine(
        URL.create(
            drivername="postgresql+psycopg2",
            username=os.environ.get("PGUSER", "postgres"),
            password=os.environ.get("PGPASSWORD", "0000"),
            host=os.environ.get("PGHOST", "localhost"),
            port=int(os.environ.get("PGPORT", "5432")),
            database=os.environ.get("PGDATABASE", "Incident_Management"),
        )
    )


def split_statements(sql: str) -> list[str]:
    """Split a .sql file into executable statements, ignoring comments."""
    without_comments = re.sub(r"--[^\n]*", "", sql)
    return [s.strip() for s in STATEMENT_SPLIT.split(without_comments) if s.strip()]


def run_file(engine, path: Path) -> list[tuple[str, pd.DataFrame]]:
    """Execute a .sql file. DDL/DML run as-is; SELECTs return a DataFrame.

    SELECT results are labelled by the nearest preceding SQL comment line, so
    keep each query preceded by a `-- Title` comment.
    """
    raw = path.read_text(encoding="utf-8")

    # Map each statement to its label: the FIRST comment line of the block
    # immediately above it (later lines in the block are explanatory prose).
    labelled: list[tuple[str, str]] = []
    label = path.stem
    buf: list[str] = []
    pending: list[str] = []
    # A leading comment block (before any SQL) is the file header, not a label.
    saw_sql = False
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            if buf:
                labelled.append((label, "\n".join(buf)))
                buf = []
            if saw_sql:
                comment = stripped.lstrip("-").strip()
                if comment:
                    pending.append(comment)
            continue
        if stripped:
            saw_sql = True
            if not buf:
                label = pending[0] if pending else label
            pending = []
            buf.append(line)
    if buf:
        labelled.append((label, "\n".join(buf)))

    results: list[tuple[str, pd.DataFrame]] = []
    with engine.connect() as conn:
        for stmt_label, statement in labelled:
            for sql_stmt in split_statements(statement):
                if sql_stmt.upper().startswith(("SELECT", "WITH")):
                    results.append((stmt_label, pd.read_sql(sql_stmt, conn)))
                else:
                    conn.execute(text(sql_stmt))
                    conn.commit()
    return results


def slugify(label: str) -> str:
    keep = [c.lower() if c.isalnum() else "_" for c in label]
    slug = re.sub(r"_+", "_", "".join(keep)).strip("_")
    return slug[:70] or "report"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run reporting SQL and export CSVs")
    parser.add_argument("--sql", help="Run only this .sql file from sql/")
    args = parser.parse_args()

    engine = get_engine()
    DATA_DIR.mkdir(exist_ok=True)

    files = [SQL_DIR / args.sql] if args.sql else sorted(SQL_DIR.glob("*.sql"))
    if not files:
        print("No .sql files found in", SQL_DIR)
        return 1

    written: list[Path] = []
    for path in files:
        print(f"\n{'=' * 78}\n{path}\n{'=' * 78}")
        try:
            results = run_file(engine, path)
        except Exception as exc:
            print(f"  FAILED: {exc}")
            return 1

        used = set()
        for label, df in results:
            base = slugify(label)
            n = 1
            while base in used:          # dedupe repeated labels
                n += 1
                base = f"{slugify(label)}_{n}"
            used.add(base)
            out = DATA_DIR / f"{base}.csv"
            df.to_csv(out, index=False)
            written.append(out)
            print(f"\n--- {label}  ({len(df)} rows) -> {out.as_posix()}")
            print(df.head(12).to_string(index=False))

    print(f"\nWrote {len(written)} CSV exports to {DATA_DIR.as_posix()}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())