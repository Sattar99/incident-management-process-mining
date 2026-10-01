"""
Project 2 - Incident Management: ETL pipeline.

Raw event log (CSV, semicolon-delimited)
    -> normalize (snake_case columns, parsed timestamps, validated)
    -> PostgreSQL incident_data (full reload, COPY-based)
    -> incidents_clean.csv (one row per case)

Design notes
------------
* Uses psycopg2 COPY rather than DataFrame.to_sql. The original
  to_sql(chunksize=5000, method="multi") load died partway through and left a
  silently truncated table (55,000 of 242,901 rows). COPY is a single
  transactional statement, so a failure leaves the table empty instead of
  half-populated.
* Every load is validated against the source file BEFORE and AFTER the write.
* Column naming is snake_case everywhere, so PostgreSQL and the CSV exports
  share one schema and can be joined without aliasing.

Usage
-----
    python etl_pipeline.py                  # full reload
    python etl_pipeline.py --skip-load      # regenerate CSV only
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import URL, create_engine, text

RAW_FILE = "Incident_Management_CSV.csv"
RAW_DELIMITER = ";"
CLEAN_FILE = "incidents_clean.csv"
DB_SCHEMA = "public"
DB_TABLE = "incident_data"

TIMESTAMP_FORMAT = "%d/%m/%Y %H:%M"

# Source columns (as they appear in the raw file) -> normalized target columns.
COLUMN_MAP = {
    "Case ID": "case_id",
    "Variant": "variant",
    "Priority": "priority",
    "Reporter": "reporter",
    "Timestamp": "event_timestamp",
    "Event": "event",
    "Issue Type": "issue_type",
    "Resolver": "resolver",
    "Report Channel": "report_channel",
    "Short Description": "short_description",
    "Customer Satisfaction": "customer_satisfaction",
}

TARGET_COLUMNS = list(COLUMN_MAP.values())

CREATE_TABLE_SQL = f"""
CREATE TABLE {DB_SCHEMA}.{DB_TABLE} (
    event_id             bigserial PRIMARY KEY,
    case_id              text        NOT NULL,
    variant              text,
    priority             text,
    reporter             text,
    event_timestamp      timestamp   NOT NULL,
    event                text,
    issue_type           text,
    resolver             text,
    report_channel       text,
    short_description    text,
    customer_satisfaction integer
);
"""

CREATE_INDEX_SQL = [
    f"CREATE UNIQUE INDEX ux_{DB_TABLE}_event "
    f"ON {DB_SCHEMA}.{DB_TABLE} (case_id, event_timestamp, event);",
    f"CREATE INDEX ix_{DB_TABLE}_case "
    f"ON {DB_SCHEMA}.{DB_TABLE} (case_id, event_timestamp);",
    f"CREATE INDEX ix_{DB_TABLE}_variant "
    f"ON {DB_SCHEMA}.{DB_TABLE} (variant);",
    f"CREATE INDEX ix_{DB_TABLE}_issue_type "
    f"ON {DB_SCHEMA}.{DB_TABLE} (issue_type);",
]


def get_engine():
    """Build the SQLAlchemy engine from PG* environment variables."""
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


def load_raw(path: Path) -> pd.DataFrame:
    """Read and normalize the raw event log."""
    print(f"[1/5] Reading {path} (sep={RAW_DELIMITER!r}) ...")
    df = pd.read_csv(path, sep=RAW_DELIMITER, low_memory=False)

    missing = [c for c in COLUMN_MAP if c not in df.columns]
    if missing:
        raise ValueError(f"Raw file is missing expected columns: {missing}")

    df = df.rename(columns=COLUMN_MAP)[TARGET_COLUMNS].copy()

    # Timestamps: explicit format first, then dayfirst fallback. Never silent.
    parsed = pd.to_datetime(df["event_timestamp"], format=TIMESTAMP_FORMAT, errors="coerce")
    if parsed.isna().any():
        fallback = pd.to_datetime(df["event_timestamp"], dayfirst=True, errors="coerce")
        parsed = parsed.fillna(fallback)
    df["event_timestamp"] = parsed

    unparsed = int(df["event_timestamp"].isna().sum())
    if unparsed:
        raise ValueError(f"{unparsed} rows have unparseable timestamps; aborting.")

    df["customer_satisfaction"] = pd.to_numeric(df["customer_satisfaction"], errors="coerce")

    for col in ("variant", "priority", "reporter", "event", "issue_type",
                "resolver", "report_channel", "short_description"):
        df[col] = df[col].astype("string").str.strip()

    df = df.sort_values(["case_id", "event_timestamp"], kind="mergesort").reset_index(drop=True)
    print(f"      {len(df):,} events | {df['case_id'].nunique():,} cases | "
          f"{df['variant'].nunique()} variants")
    print(f"      range {df['event_timestamp'].min()} -> {df['event_timestamp'].max()}")
    return df


def validate_source(df: pd.DataFrame) -> None:
    """Fail loudly on data defects that would corrupt downstream metrics."""
    print("[2/5] Validating source data ...")

    dupes = int(df.duplicated(subset=["case_id", "event_timestamp", "event"]).sum())
    if dupes:
        raise ValueError(f"{dupes} duplicate (case_id, event_timestamp, event) rows.")

    # Attributes used as case-level dimensions must be constant within a case,
    # otherwise the "first row wins" logic in build_case_table is arbitrary.
    for col in ("variant", "issue_type", "priority", "report_channel"):
        n = df.groupby("case_id")[col].nunique(dropna=True).gt(1).sum()
        if n:
            raise ValueError(
                f"{int(n)} cases have more than one {col!r}; "
                f"case-level attribution would be ambiguous."
            )

    per_case = df.groupby("case_id").size()
    if per_case.min() < 2:
        raise ValueError(
            f"{int((per_case < 2).sum())} cases have fewer than 2 events; "
            f"cycle time is undefined for them."
        )

    print(f"      no duplicate events; all case dimensions constant; "
          f"min {per_case.min()} events/case")


def write_to_postgres(df: pd.DataFrame, engine) -> None:
    """Recreate and fully repopulate incident_data via COPY in one transaction."""
    print("[3/5] Loading PostgreSQL ...")
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{DB_TABLE} CASCADE;")
            cur.execute(CREATE_TABLE_SQL)
            for stmt in CREATE_INDEX_SQL:
                cur.execute(stmt)

            buf = io.StringIO()
            writer = csv.writer(buf, lineterminator="\n")
            for row in df.itertuples(index=False, name=None):
                writer.writerow(["" if pd.isna(v) else v for v in row])

            buf.seek(0)
            cur.copy_expert(
                f"COPY {DB_SCHEMA}.{DB_TABLE} "
                f"({', '.join(TARGET_COLUMNS)}) FROM STDIN WITH (FORMAT CSV)",
                buf,
            )
        raw.commit()
        print(f"      COPY committed: {len(df):,} rows")
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def verify_load(df: pd.DataFrame, engine) -> None:
    """Assert the database matches the source file exactly."""
    print("[4/5] Verifying load parity ...")
    with engine.connect() as conn:
        db = pd.read_sql(
            text(f"SELECT count(*) AS rows, count(DISTINCT case_id) AS cases "
                 f"FROM {DB_SCHEMA}.{DB_TABLE}"),
            conn,
        ).iloc[0]

    src_rows, src_cases = len(df), df["case_id"].nunique()
    if int(db["rows"]) != src_rows or int(db["cases"]) != src_cases:
        raise ValueError(
            f"Load mismatch: source has {src_rows:,} rows / {src_cases:,} cases, "
            f"database has {int(db['rows']):,} rows / {int(db['cases']):,} cases."
        )
    print(f"      parity OK: {int(db['rows']):,} rows, {int(db['cases']):,} cases")


def build_case_table(events: pd.DataFrame) -> pd.DataFrame:
    """Collapse the event log to one row per case."""
    print("[5/5] Building case-level table ...")
    ordered = events.sort_values(["case_id", "event_timestamp"], kind="mergesort")
    grouped = ordered.groupby("case_id", sort=True)

    cases = grouped.agg(
        variant=("variant", "first"),
        priority=("priority", "first"),
        reporter=("reporter", "first"),
        issue_type=("issue_type", "first"),
        report_channel=("report_channel", "first"),
        short_description=("short_description", "first"),
        customer_satisfaction=("customer_satisfaction", "first"),
        event_count=("event", "size"),
        unique_events=("event", "nunique"),
        unique_resolvers=("resolver", "nunique"),
        start_time=("event_timestamp", "min"),
        end_time=("event_timestamp", "max"),
    ).reset_index()

    cases["duration_hours"] = (
        (cases["end_time"] - cases["start_time"]).dt.total_seconds() / 3600.0
    )
    cases["escalated"] = (
        grouped["event"].apply(lambda s: int(s.str.contains("escalat", case=False, na=False).any()))
        .reindex(cases["case_id"]).to_numpy()
    )
    cases["reached_level_3"] = (
        grouped["event"].apply(lambda s: int(s.str.contains("level 3", case=False, na=False).any()))
        .reindex(cases["case_id"]).to_numpy()
    )
    cases["is_completed"] = (
        grouped["event"].apply(lambda s: int(s.str.contains("closed", case=False, na=False).any()))
        .reindex(cases["case_id"]).to_numpy()
    )

    cases.to_csv(CLEAN_FILE, index=False)
    print(f"      wrote {CLEAN_FILE}: {len(cases):,} cases")
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Incident Management ETL")
    parser.add_argument("--skip-load", action="store_true",
                        help="Regenerate the case-level CSV without touching PostgreSQL.")
    parser.add_argument("--raw", default=RAW_FILE)
    args = parser.parse_args()

    events = load_raw(Path(args.raw))
    validate_source(events)

    if not args.skip_load:
        engine = get_engine()
        write_to_postgres(events, engine)
        verify_load(events, engine)

    build_case_table(events)
    print("\nETL complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())