"""
tests/test_pipeline.py : guard rails for the Incident Management pipeline.

The regression this suite exists to prevent: an ETL load that fails partway and
leaves a silently truncated table. That happened with to_sql(chunksize=5000,
method="multi"), which committed 55,000 of 242,901 rows and produced two days of
metrics computed on 22.6% of the data. Nothing errored.

Run with:
    python -m pytest tests/ -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import URL, create_engine, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from etl_pipeline import (  # noqa: E402
    DB_TABLE,
    RAW_DELIMITER,
    RAW_FILE,
    TIMESTAMP_FORMAT,
    get_engine,
    load_raw,
    validate_source,
)

RAW_PATH = ROOT / RAW_FILE


@pytest.fixture(scope="module")
def events() -> pd.DataFrame:
    if not RAW_PATH.exists():
        pytest.skip(f"{RAW_FILE} not found")
    return load_raw(RAW_PATH)


@pytest.fixture(scope="module")
def db():
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"PostgreSQL unavailable: {exc}")

    # etl_pipeline.py drops and recreates incident_data with CASCADE, which
    # also drops the reporting views. Recreate them so this suite is runnable
    # on a freshly loaded database regardless of whether analytics.py ran.
    ensure_views(engine)
    return engine


def ensure_views(engine) -> None:
    views_sql = ROOT / "sql" / "01_views.sql"
    if not views_sql.exists():
        return
    from analytics import run_file
    run_file(engine, views_sql)


# --- source file ------------------------------------------------------------

def test_raw_file_is_semicolon_delimited(events):
    """A mis-detected delimiter yields a single 'Unnamed: 0'-style column."""
    assert len(events.columns) == 11, f"expected 11 columns, got {len(events.columns)}"


def test_timestamps_all_parse(events):
    assert events["event_timestamp"].isna().sum() == 0
    assert str(events["event_timestamp"].dtype).startswith("datetime")


def test_expected_row_count(events):
    """Guards against a truncated read of the 28MB source file."""
    assert len(events) == 242_901
    assert events["case_id"].nunique() == 31_588


def test_source_validation_passes(events):
    validate_source(events)   # raises on duplicate/ambiguous/invalid data


def test_no_duplicate_events(events):
    dupes = events.duplicated(subset=["case_id", "event_timestamp", "event"]).sum()
    assert dupes == 0


def test_case_dimensions_are_constant(events):
    for col in ("variant", "issue_type", "priority", "report_channel"):
        varying = events.groupby("case_id")[col].nunique().gt(1).sum()
        assert varying == 0, f"{varying} cases have multiple {col} values"


def test_no_negative_cycle_times(events):
    span = events.groupby("case_id")["event_timestamp"].agg(lambda s: (s.max() - s.min()).total_seconds())
    assert span.min() >= 0


# --- database parity (the regression that motivated this suite) ------------

def test_db_row_count_matches_source(db, events):
    with db.connect() as conn:
        n = conn.execute(text(f"SELECT count(*) FROM {DB_TABLE}")).scalar()
    assert n == len(events), (
        f"database has {n:,} rows, source has {len(events):,} - the load is truncated"
    )


def test_db_case_count_matches_source(db, events):
    with db.connect() as conn:
        n = conn.execute(text(f"SELECT count(DISTINCT case_id) FROM {DB_TABLE}")).scalar()
    assert n == events["case_id"].nunique()


def test_db_timestamp_range_matches_source(db, events):
    with db.connect() as conn:
        lo, hi = conn.execute(
            text(f"SELECT min(event_timestamp), max(event_timestamp) FROM {DB_TABLE}")
        ).one()
    assert lo == events["event_timestamp"].min()
    assert hi == events["event_timestamp"].max()


def test_db_variant_count_matches_source(db, events):
    with db.connect() as conn:
        n = conn.execute(text(f"SELECT count(DISTINCT variant) FROM {DB_TABLE}")).scalar()
    assert n == events["variant"].nunique() == 13


def test_no_case_is_partially_loaded(db, events):
    """Every case must have its full event count, not a truncated prefix."""
    expected = events.groupby("case_id").size()
    with db.connect() as conn:
        actual = pd.read_sql(
            text(f"SELECT case_id, count(*) AS n FROM {DB_TABLE} GROUP BY case_id"), conn
        ).set_index("case_id")["n"]
    pd.testing.assert_series_equal(
        actual.sort_index().rename("n"),
        expected.sort_index().rename("n"),
        check_names=False,
    )


# --- metric correctness -----------------------------------------------------

def test_views_agree_with_source_kpis(db, events):
    """v_case_metrics mean cycle time must equal the pandas computation."""
    with db.connect() as conn:
        mean_hours, n_cases = conn.execute(
            text("""
                SELECT round(avg(cycle_time_hours)::numeric, 2), count(*)
                FROM v_case_metrics""")
        ).one()

    # One row per case, then average across cases. Averaging the row-level
    # spans would weight each case by its event count instead.
    per_case = events.groupby("case_id")["event_timestamp"].agg(
        lambda s: (s.max() - s.min()).total_seconds() / 3600
    )
    expected = per_case.mean()

    assert n_cases == events["case_id"].nunique()
    assert abs(float(mean_hours) - expected) < 0.01


def test_transition_view_has_no_negative_durations(db):
    with db.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM v_transition_metrics WHERE duration_hours < 0")
        ).scalar()
    assert n == 0


def test_transition_view_excludes_null_events(db):
    with db.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM v_transition_metrics WHERE from_event IS NULL")
        ).scalar()
    assert n == 0


def test_known_null_event_is_accounted_for(db):
    """INC0305 has one NULL event name; it must be documented, not silently dropped."""
    with db.connect() as conn:
        nulls = conn.execute(
            text("SELECT count(*) FROM incident_data WHERE event IS NULL")
        ).scalar()
    assert nulls == 1


def test_resolver_nulls_are_structural(db):
    """NULL resolver is normal for system transitions, so it is excluded from
    COUNT(DISTINCT resolver) rather than filled with a literal."""
    with db.connect() as conn:
        total, non_null = conn.execute(
            text("SELECT count(*), count(resolver) FROM incident_data")
        ).one()
    assert non_null < total   # NULLs exist and are intentional


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))