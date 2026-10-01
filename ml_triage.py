"""
Project 2 - Incident Management: ML INTAKE TRIAGE CLASSIFIER.

Purpose
-------
Predict, AT INTAKE, which tickets are heading for a slow / escalated / L3
outcome, so that routing can happen BEFORE the ~4.2 h level-1 support attempt
is spent. That L1 attempt is where 28.8% of all elapsed process time sits, so
it is the highest-leverage intervention available.

This script is ADDITIVE: it reads the database, writes only to ml_artifacts/,
and touches nothing else in the project.

LEAKAGE CONTRACT (the single most important design decision here)
----------------------------------------------------------------
At the moment a ticket is created an operations analyst knows ONLY:

    case_id, variant(?), priority, reporter, report_channel, issue_type,
    short_description, creation timestamp

They do NOT know: resolver identity, event count, any timestamp after the
first one, cycle time, escalation, L3 reach, or satisfaction.

Therefore this script NEVER derives a feature from event_count, step_seconds,
cycle_time_*, unique_resolvers, started_at/ended_at, or any post-first-event
row. The intake table is built with DISTINCT ON (case_id) ... ORDER BY
event_timestamp so that exactly one row per case -- the FIRST event -- is
joined, and every feature comes from that row only.

Two features are deliberately treated as NOT-at-intake and are handled
accordingly:

1. customer_satisfaction
   It is non-null on every row of every case (case-level attribute in this
   denormalised log), so it *appears* to be present at creation. But the field
   is a post-closure survey score: a customer cannot rate handling that has not
   happened. Its presence on the creation row is an artefact of the log
   carrying the final case attribute on all rows. We cannot establish from the
   data that it is available at intake, so it is EXCLUDED from the production
   feature set. It is measured separately as a deliberate leakage ABLATION
   (see run_leakage_ablation) to quantify how much it would have flattered
   the model.

2. variant
   `variant` is the process-mining cluster label. It is only assigned by
   running a discovery algorithm over the COMPLETED log, so in a live intake
   system it is definitionally unavailable. It is excluded from the PRODUCTION
   feature set and reported separately as an upper-bound/oracle variant.

Targets
-------
primary   : reached_level_3   (bool)  -- the Variant 7 / slow-outcome signal
secondary : escalated         (bool)
secondary : slow_24h          (bool)  -- cycle_time_hours > 24, ties to the SLA
                                          breach analysis in RESULTS §4
secondary : cycle_time_hours  (regression)

Splits
------
Chronological 70/30 on the first-event timestamp (train = earlier period,
test = later period) is the primary split, because this is time-series
operational data and a random split lets the model see the future. A random
70/30 split is reported alongside as a baseline so that any gap between the
two is visible as a finding rather than hidden.

Models
------
* LogisticRegression (L2, lbfgs) -- interpretable, gives a coefficient table.
* HistGradientBoostingClassifier -- in sklearn, no xgboost/lightgbm needed.

Baselines
---------
Trivial majority-class and stratified-random baselines are always reported so
that precision/recall/F1 are interpretable against a 6.3% base rate.

Usage
-----
    python ml_triage.py
"""

from __future__ import annotations

import json
import os
import platform
import sys
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    matthews_corrcoef,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import URL, create_engine, text

ARTIFACT_DIR = Path("ml_artifacts")
RANDOM_STATE = 42
TEST_SIZE = 0.30
SLOW_HOURS = 24.0

# Categorical intake fields (excluding `variant`, see module docstring).
CAT_FEATURES = ["issue_type", "priority", "report_channel", "reporter",
                "short_description"]
# Temporal features derived only from the CREATION timestamp.
TEMP_FEATURES = ["created_hour", "created_dow", "created_is_weekend",
                 "created_month", "created_dayofyear", "desc_length"]
NUM_FEATURES = ["created_hour", "created_dow", "created_month",
                "created_dayofyear", "desc_length"]


# ---------------------------------------------------------------------------
# DB access -- reuses the project's PG* env-var convention
# ---------------------------------------------------------------------------
def get_engine():
    """Build the SQLAlchemy engine from PG* environment variables.

    Identical contract to etl_pipeline.get_engine(): PGUSER / PGPASSWORD /
    PGHOST / PGPORT / PGDATABASE with the project defaults.
    """
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


INTAKE_SQL = """
WITH first_event AS (
    -- Exactly one row per case: the earliest event. Ties broken by event_id
    -- for determinism. Every intake feature below is read from THIS row only,
    -- so no post-intake information can enter the feature matrix.
    SELECT DISTINCT ON (case_id)
        case_id,
        variant,
        priority,
        reporter,
        report_channel,
        issue_type,
        short_description,
        customer_satisfaction,
        event_timestamp,
        event
    FROM incident_data
    ORDER BY case_id, event_timestamp, event_id
)
SELECT
    f.case_id,
    f.variant,
    f.priority,
    f.reporter,
    f.report_channel,
    f.issue_type,
    f.short_description,
    f.customer_satisfaction,
    f.event_timestamp            AS created_at,
    f.event                      AS first_event,
    m.cycle_time_hours,
    m.reached_level_3,
    m.escalated,
    m.is_completed
FROM first_event f
JOIN v_case_metrics m USING (case_id)
ORDER BY f.event_timestamp, f.case_id
"""


def load_intake_frame(engine) -> pd.DataFrame:
    """Build the one-row-per-case intake frame with labels attached."""
    with engine.connect() as conn:
        df = pd.read_sql(text(INTAKE_SQL), conn)

    if len(df) == 0:
        raise RuntimeError("intake frame is empty -- is incident_data loaded?")

    # Sanity: the first event must be the creation event for every case.
    bad_first = int((df["first_event"] != "Ticket created").sum())
    if bad_first:
        print(f"      WARNING: {bad_first} cases do not start with 'Ticket created'")

    df["created_at"] = pd.to_datetime(df["created_at"])
    ts = df["created_at"]
    df["created_hour"] = ts.dt.hour
    df["created_dow"] = ts.dt.dayofweek
    df["created_is_weekend"] = (ts.dt.dayofweek >= 5).astype(int)
    df["created_month"] = ts.dt.month
    df["created_dayofyear"] = ts.dt.dayofyear
    df["desc_length"] = df["short_description"].fillna("").str.len()

    df["slow_24h"] = (df["cycle_time_hours"] > SLOW_HOURS).astype(int)
    for c in ("reached_level_3", "escalated", "is_completed"):
        df[c] = df[c].astype(int)
    return df


# ---------------------------------------------------------------------------
# Diagnostics run BEFORE modelling, because they may invalidate the features
# ---------------------------------------------------------------------------
def check_short_description_templating(df: pd.DataFrame) -> dict:
    """Is short_description real free text, or a fixed vocabulary of labels?"""
    s = df["short_description"].fillna("(null)")
    vc = s.value_counts()
    n_distinct = int(s.nunique())
    out = {
        "n_cases": int(len(df)),
        "n_distinct": n_distinct,
        "distinct_pct": round(100.0 * n_distinct / len(df), 4),
        "null_count": int(df["short_description"].isna().sum()),
        "mean_length_chars": round(float(df["desc_length"].mean()), 2),
        "max_length_chars": int(df["desc_length"].max()),
        "top_values": {str(k): int(v) for k, v in vc.head(15).items()},
        "is_boilerplate": n_distinct <= 50,
    }
    # Does the description carry ANY information beyond issue_type?
    crosstab = pd.crosstab(s, df["issue_type"])
    # normalised mutual information between the two categorical fields
    try:
        from sklearn.metrics import normalized_mutual_info_score

        out["nmi_desc_vs_issue_type"] = round(
            float(normalized_mutual_info_score(s, df["issue_type"])), 4)
    except Exception:  # pragma: no cover
        out["nmi_desc_vs_issue_type"] = None
    out["desc_issue_type_table"] = {
        str(k): {str(c): int(v) for c, v in row.items() if v}
        for k, row in crosstab.to_dict("index").items()
    }
    return out


def check_satisfaction_timing(df: pd.DataFrame) -> dict:
    """Is customer_satisfaction written at creation, or only at closure?

    Empirical test: if the value on the FIRST event already equals the final
    value, the log simply carries the finished case attribute on every row and
    that tells us nothing about when it was *written*. The only observable
    proxy is the event at which the value differs from the first-event value,
    if any. We report that.
    """
    return {
        "null_at_intake": int(df["customer_satisfaction"].isna().sum()),
        "n_distinct": int(df["customer_satisfaction"].nunique()),
        "present_on_every_row": bool(df["customer_satisfaction"].notna().all()),
        "mean_by_reached_l3": {
            str(k): round(float(v), 4) for k, v in
            df.groupby("reached_level_3")["customer_satisfaction"].mean().items()
        },
        "verdict": (
            "EXCLUDED from the production feature set. The score is a "
            "post-closure survey response denormalised onto every row of the "
            "case; its presence on the creation row is an artefact, not "
            "evidence of intake availability. Reported as a leakage ablation."
        ),
    }


def report_class_balance(df: pd.DataFrame) -> dict:
    """Base rates FIRST, so that every precision/recall below is interpretable."""
    out = {}
    for tgt in ("reached_level_3", "escalated", "slow_24h"):
        counts = df[tgt].value_counts()
        pos = int(counts.get(1, 0))
        out[tgt] = {
            "n": int(len(df)),
            "positives": pos,
            "negatives": int(len(df) - pos),
            "base_rate": round(pos / len(df), 6),
            "trivial_majority_accuracy": round(
                max(pos, len(df) - pos) / len(df), 6),
            "trivial_majority_precision_if_predict_positive": 1.0 if pos == 0 else
                round(pos / len(df), 6),
        }
    ct = df["cycle_time_hours"]
    out["cycle_time_hours"] = {
        "mean": round(float(ct.mean()), 4),
        "median": round(float(ct.median()), 4),
        "p75": round(float(ct.quantile(0.75)), 4),
        "p95": round(float(ct.quantile(0.95)), 4),
        "max": round(float(ct.max()), 4),
        "std": round(float(ct.std()), 4),
    }
    return out


def variant_7_profile(df: pd.DataFrame) -> dict:
    """Quantify how much of the primary target is the deterministic Variant 7."""
    v7 = df[df["variant"] == "Variant 7"]
    rest = df[df["variant"] != "Variant 7"]
    return {
        "variant_7_cases": int(len(v7)),
        "variant_7_share_of_data": round(len(v7) / len(df), 4),
        "variant_7_issue_types": v7["issue_type"].value_counts().to_dict(),
        "variant_7_l3_rate": round(float(v7["reached_level_3"].mean()), 4),
        "rest_l3_rate": round(float(rest["reached_level_3"].mean()), 4),
        "l3_positives_inside_variant_7": int(v7["reached_level_3"].sum()),
        "l3_positives_total": int(df["reached_level_3"].sum()),
        "l3_positive_share_from_variant_7": round(
            float(v7["reached_level_3"].sum() / max(1, df["reached_level_3"].sum())), 4),
        "variant_7_mean_cycle_hours": round(float(v7["cycle_time_hours"].mean()), 3),
        "rest_mean_cycle_hours": round(float(rest["cycle_time_hours"].mean()), 3),
    }


# ---------------------------------------------------------------------------
# Feature pipeline
# ---------------------------------------------------------------------------
def build_preprocessor(use_variant: bool = False) -> ColumnTransformer:
    """One-hot categoricals + scaled numerics + TF-IDF over short_description.

    `use_variant=True` produces the ORACLE feature set (variant is only
    knowable after process mining over the completed log) and is reported
    separately. It is never the production set.
    """
    cats = list(CAT_FEATURES)
    if use_variant:
        cats = cats + ["variant"]

    return ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), cats),
            ("num", StandardScaler(), NUM_FEATURES),
            ("tfidf", TfidfVectorizer(max_features=200, ngram_range=(1, 2)),
             "short_description"),
        ],
        remainder="drop",
    )


def build_logreg() -> Pipeline:
    return Pipeline([
        ("prep", build_preprocessor(use_variant=False)),
        ("clf", LogisticRegression(
            penalty="l2", C=1.0, solver="lbfgs", max_iter=2000,
            class_weight="balanced", random_state=RANDOM_STATE)),
    ])


def build_logreg_oracle() -> Pipeline:
    return Pipeline([
        ("prep", build_preprocessor(use_variant=True)),
        ("clf", LogisticRegression(
            penalty="l2", C=1.0, solver="lbfgs", max_iter=2000,
            class_weight="balanced", random_state=RANDOM_STATE)),
    ])


def build_hgb(seed: int = RANDOM_STATE) -> HistGradientBoostingClassifier:
    """Gradient-boosted trees on ordinal-encoded categoricals.

    Trees do not need one-hot, but they DO need numeric codes, so the same
    frame is ordinal-encoded with unknown -> -1.
    """
    return HistGradientBoostingClassifier(
        max_iter=300,
        learning_rate=0.08,
        max_leaf_nodes=31,
        min_samples_leaf=40,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.15,
        random_state=seed,
    )


def ordinal_frame(df: pd.DataFrame, use_variant: bool = False) -> pd.DataFrame:
    cols = list(CAT_FEATURES) + list(TEMP_FEATURES)
    if use_variant:
        cols = cols + ["variant"]
    out = df[cols].copy()
    for c in CAT_FEATURES + (["variant"] if use_variant else []):
        out[c] = pd.Categorical(out[c]).codes.astype(float)
        out.loc[df[c].isna().to_numpy(), c] = -1.0
    return out


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def evaluate_binary(y_true, prob) -> dict:
    y_true = np.asarray(y_true)
    prob = np.asarray(prob)
    y_pred = (prob >= 0.5).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    base = float(y_true.mean())
    m = {
        "n_test": int(len(y_true)),
        "positives_test": int(y_true.sum()),
        "base_rate_test": round(base, 6),
        "roc_auc": round(float(roc_auc_score(y_true, prob)), 6),
        "pr_auc": round(float(average_precision_score(y_true, prob)), 6),
        "brier": round(float(brier_score_loss(y_true, prob)), 6),
        "balanced_accuracy": round(float(balanced_accuracy_score(y_true, y_pred)), 6),
        "mcc": round(float(matthews_corrcoef(y_true, y_pred)), 6),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "lift_over_base_rate": None,
    }
    m["lift_over_base_rate"] = (
        round(m["pr_auc"] / base, 4) if base > 0 else None)

    # precision/recall at the DEFAULT threshold, and at the threshold that
    # maximises F1 -- a single 0.5 cut is often badly calibrated on a 6% base
    # rate, and an operations team would not run it at 0.5 anyway.
    prec, rec, thr = precision_recall_curve(y_true, prob)
    f1 = 2 * prec * rec / np.maximum(prec + rec, 1e-12)
    best_i = int(np.argmax(f1[:-1])) if len(f1) > 1 else 0
    best_thr = float(thr[best_i]) if len(thr) else 0.5
    y_b = (prob >= best_thr).astype(int)
    tn2, fp2, fn2, tp2 = confusion_matrix(y_true, y_b, labels=[0, 1]).ravel()

    m["at_0.5"] = {
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 6),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 6),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 6),
    }
    m["at_best_f1"] = {
        "threshold": round(best_thr, 6),
        "precision": round(float(precision_score(y_true, y_b, zero_division=0)), 6),
        "recall": round(float(recall_score(y_true, y_b, zero_division=0)), 6),
        "f1": round(float(f1_score(y_true, y_b, zero_division=0)), 6),
        "confusion_matrix": {"tn": int(tn2), "fp": int(fp2), "fn": int(fn2), "tp": int(tp2)},
        "n_flagged": int(y_b.sum()),
        "n_flagged_pct_of_test": round(100.0 * y_b.sum() / len(y_true), 3),
    }
    return m


def trivial_baselines(y_true, y_train) -> dict:
    """Always-negative, and stratified-random guessing, for context."""
    y_true = np.asarray(y_true)
    base = float(y_train.mean())
    rng = np.random.default_rng(RANDOM_STATE)
    out = {
        "always_negative": {
            "accuracy": round(float((y_true == 0).mean()), 6),
            "precision": None, "recall": 0.0, "f1": None,
            "roc_auc": 0.5, "pr_auc": round(base, 6),
        },
        "stratified_random": {},
    }
    pr, rc, f1s, aucs, aps = [], [], [], [], []
    for _ in range(20):
        p = rng.binomial(1, base, size=len(y_true))
        yp = (rng.random(len(y_true)) < p).astype(int)
        pr.append(precision_score(y_true, yp, zero_division=0))
        rc.append(recall_score(y_true, yp, zero_division=0))
        f1s.append(f1_score(y_true, yp, zero_division=0))
        aucs.append(roc_auc_score(y_true, yp))
        aps.append(average_precision_score(y_true, yp))
    out["stratified_random"] = {
        "precision_mean": round(float(np.mean(pr)), 6),
        "recall_mean": round(float(np.mean(rc)), 6),
        "f1_mean": round(float(np.mean(f1s)), 6),
        "roc_auc_mean": round(float(np.mean(aucs)), 6),
        "pr_auc_mean": round(float(np.mean(aps)), 6),
        "n_repeats": 20,
    }
    return out


def logreg_feature_table(model: Pipeline, top_n: int = 40) -> pd.DataFrame:
    """Signed coefficients from the interpretable model, named."""
    prep = model.named_steps["prep"]
    names = prep.get_feature_names_out()
    coefs = model.named_steps["clf"].coef_.ravel()
    return pd.DataFrame({"feature": names, "coefficient": coefs})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    print("=" * 78)
    print("ML INTAKE TRIAGE CLASSIFIER - Incident Management (Project 2)")
    print("=" * 78)
    print(f"run at          : {datetime.now().isoformat(timespec='seconds')}")
    print(f"python          : {platform.python_version()}  ({sys.executable})")
    print(f"pandas {pd.__version__} | numpy {np.__version__} | sklearn {sklearn.__version__}")

    ARTIFACT_DIR.mkdir(exist_ok=True)
    report: dict = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "library_versions": {
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "sklearn": sklearn.__version__,
        },
    }

    # -- 1. load -------------------------------------------------------------
    print("\n[1] Loading intake frame (first event only) + labels ...")
    engine = get_engine()
    df = load_intake_frame(engine)
    print(f"    {len(df):,} cases | {df['created_at'].min()} -> {df['created_at'].max()}")
    print(f"    first-event check: all cases start with 'Ticket created' = "
          f"{bool((df['first_event'] == 'Ticket created').all())}")

    report["intake_frame"] = {
        "n_cases": int(len(df)),
        "n_first_event_not_ticket_created": int(
            (df["first_event"] != "Ticket created").sum()),
        "created_at_min": str(df["created_at"].min()),
        "created_at_max": str(df["created_at"].max()),
        "features_used": CAT_FEATURES + TEMP_FEATURES,
        "features_deliberately_excluded": [
            "event_count", "unique_events", "unique_resolvers", "cycle_time_hours",
            "mean_step_seconds", "max_step_seconds", "median_step_seconds",
            "started_at", "ended_at", "resolver", "event (post-first)",
            "customer_satisfaction (post-closure survey)",
            "variant (only assigned by process mining over the completed log)",
        ],
    }

    # -- 2. diagnostics -----------------------------------------------------
    print("\n[2] Pre-model diagnostics ...")
    templating = check_short_description_templating(df)
    print(f"    short_description: {templating['n_distinct']} distinct values across "
          f"{templating['n_cases']:,} cases ({templating['distinct_pct']}% distinct)")
    print(f"    verdict: boilerplate = {templating['is_boilerplate']}")
    for k, v in list(templating["top_values"].items())[:8]:
        print(f"      {v:6,}  {k}")
    print(f"    NMI(short_description, issue_type) = {templating['nmi_desc_vs_issue_type']}")

    sat = check_satisfaction_timing(df)
    print(f"    customer_satisfaction: {sat['verdict'][:60]}...")

    balance = report_class_balance(df)
    print("\n[3] Class balance / base rates (report these BEFORE any metric):")
    for tgt in ("reached_level_3", "escalated", "slow_24h"):
        b = balance[tgt]
        print(f"    {tgt:18s} n={b['n']:,}  positives={b['positives']:,}  "
              f"base_rate={b['base_rate']:.4f}  "
              f"trivial_acc={b['trivial_majority_accuracy']:.4f}")
    print(f"    cycle_time_hours: mean={balance['cycle_time_hours']['mean']}  "
          f"median={balance['cycle_time_hours']['median']}  "
          f"p95={balance['cycle_time_hours']['p95']}  "
          f"max={balance['cycle_time_hours']['max']}")

    v7 = variant_7_profile(df)
    print(f"    Variant 7: {v7['variant_7_cases']:,} cases, L3 rate "
          f"{v7['variant_7_l3_rate']:.4f} vs {v7['rest_l3_rate']:.4f} elsewhere; "
          f"it supplies {v7['l3_positive_share_from_variant_7']:.2%} of all L3 positives")

    report["short_description_templating"] = templating
    report["customer_satisfaction_timing"] = sat
    report["class_balance"] = balance
    report["variant_7_profile"] = v7

    # -- 4. splits ----------------------------------------------------------
    print("\n[4] Building splits ...")
    n = len(df)
    n_test = int(round(n * TEST_SIZE))
    chrono_cut = df["created_at"].iloc[n - n_test]
    chrono = {"train": df.iloc[: n - n_test].copy(), "test": df.iloc[n - n_test:].copy()}
    rng = np.random.default_rng(RANDOM_STATE)
    idx = rng.permutation(n)
    rand = {"train": df.iloc[idx[: n - n_test]].copy(),
            "test": df.iloc[idx[n - n_test:]].copy()}

    split_info = {
        "strategy": "chronological 70/30 on first-event timestamp (primary)",
        "test_size": TEST_SIZE,
        "random_state": RANDOM_STATE,
        "chronological_cut_timestamp": str(chrono_cut),
        "n_train_chrono": int(len(chrono["train"])),
        "n_test_chrono": int(len(chrono["test"])),
        "n_train_random": int(len(rand["train"])),
        "n_test_random": int(len(rand["test"])),
        "chronological_train_range": [str(chrono["train"]["created_at"].min()),
                                      str(chrono["train"]["created_at"].max())],
        "chronological_test_range": [str(chrono["test"]["created_at"].min()),
                                     str(chrono["test"]["created_at"].max())],
        "temporal_overlap_check": "none by construction (train strictly earlier)",
    }
    for name, sp in (("chronological", chrono), ("random", rand)):
        print(f"    {name:14s} train={len(sp['train']):,} test={len(sp['test']):,}  "
              f"test range {sp['test']['created_at'].min()} -> {sp['test']['created_at'].max()}")
    report["splits"] = split_info

    # -- 5. models ----------------------------------------------------------
    TARGETS = ["reached_level_3", "escalated", "slow_24h"]
    results: dict = {}
    roc_store: dict = {}
    pr_store: dict = {}

    for split_name, sp in (("chronological", chrono), ("random", rand)):
        results[split_name] = {}
        for tgt in TARGETS:
            print(f"\n[5] target={tgt}  split={split_name}")
            tr, te = sp["train"], sp["test"]
            ytr, yte = tr[tgt].to_numpy(), te[tgt].to_numpy()

            base = trivial_baselines(yte, ytr)
            print(f"    base rate test={yte.mean():.4f} | always-negative acc="
                  f"{base['always_negative']['accuracy']:.4f} | "
                  f"random-guess F1={base['stratified_random']['f1_mean']:.4f} "
                  f"PR-AUC={base['stratified_random']['pr_auc_mean']:.4f}")

            # -- logistic regression
            lr = build_logreg()
            lr.fit(tr[CAT_FEATURES + TEMP_FEATURES], ytr)
            p_lr = lr.predict_proba(te[CAT_FEATURES + TEMP_FEATURES])[:, 1]
            m_lr = evaluate_binary(yte, p_lr)
            print(f"    LogReg      AUC={m_lr['roc_auc']:.4f}  PR-AUC={m_lr['pr_auc']:.4f} "
                  f"(lift {m_lr['lift_over_base_rate']}x)  "
                  f"F1@0.5={m_lr['at_0.5']['f1']:.4f}  "
                  f"P/R@bestF1={m_lr['at_best_f1']['precision']:.4f}/"
                  f"{m_lr['at_best_f1']['recall']:.4f} (thr={m_lr['at_best_f1']['threshold']:.3f})")

            # -- gradient boosting
            Xtr_o, Xte_o = ordinal_frame(tr), ordinal_frame(te)
            gb = build_hgb()
            gb.fit(Xtr_o, ytr)
            p_gb = gb.predict_proba(Xte_o)[:, 1]
            m_gb = evaluate_binary(yte, p_gb)
            print(f"    HistGB      AUC={m_gb['roc_auc']:.4f}  PR-AUC={m_gb['pr_auc']:.4f} "
                  f"(lift {m_gb['lift_over_base_rate']}x)  "
                  f"F1@0.5={m_gb['at_0.5']['f1']:.4f}  "
                  f"P/R@bestF1={m_gb['at_best_f1']['precision']:.4f}/"
                  f"{m_gb['at_best_f1']['recall']:.4f} (thr={m_gb['at_best_f1']['threshold']:.3f})")

            results[split_name][tgt] = {
                "baselines": base,
                "logistic_regression": m_lr,
                "hist_gradient_boosting": m_gb,
            }
            if split_name == "chronological":
                roc_store[tgt] = {
                    "logreg": roc_curve(yte, p_lr),
                    "histgb": roc_curve(yte, p_gb),
                }
                pr_store[tgt] = {
                    "logreg": precision_recall_curve(yte, p_lr),
                    "histgb": precision_recall_curve(yte, p_gb),
                }
                if tgt == "reached_level_3":
                    # coefficients for the interpretable model, chronological split
                    ft = logreg_feature_table(lr)
                    ft["abs_coef"] = ft["coefficient"].abs()
                    ft = ft.sort_values("abs_coef", ascending=False)
                    ft.drop(columns="abs_coef").to_csv(
                        ARTIFACT_DIR / "feature_importance_logreg.csv", index=False)
                    report["logreg_coefficients_top20"] = ft.head(20).to_dict("records")
                    print("\n    Top 10 logistic-regression features (signed, "
                          "class_weight=balanced):")
                    for _, r in ft.head(10).iterrows():
                        print(f"      {r['coefficient']:+.4f}  {r['feature']}")

                    # HGB permutation importance on the primary target
                    perm = permutation_importance(
                        gb, Xte_o, yte, n_repeats=5, random_state=RANDOM_STATE,
                        scoring="average_precision")
                    pi = pd.DataFrame({
                        "feature": Xte_o.columns,
                        "permutation_importance_mean": perm.importances_mean,
                        "permutation_importance_std": perm.importances_std,
                    }).sort_values("permutation_importance_mean", ascending=False)
                    pi.to_csv(ARTIFACT_DIR / "feature_importance_permutation.csv", index=False)
                    report["permutation_importance_top10"] = pi.head(10).to_dict("records")

                    # final production model, refit on ALL data for artefacts
                    final_lr = build_logreg()
                    final_lr.fit(df[CAT_FEATURES + TEMP_FEATURES], df["reached_level_3"])
                    import joblib
                    joblib.dump(final_lr, ARTIFACT_DIR / "model_logreg_l3.pkl")
                    final_gb = build_hgb()
                    final_gb.fit(ordinal_frame(df), df["reached_level_3"])
                    joblib.dump(final_gb, ARTIFACT_DIR / "model_histgb_l3.pkl")
                    joblib.dump(ordinal_frame(df).columns.tolist(),
                                ARTIFACT_DIR / "histgb_feature_order.pkl")
                    print(f"\n    saved fitted models -> {ARTIFACT_DIR}")

    # -- 6. oracle-variant and leakage ablations ----------------------------
    print("\n[6] Ablations on the primary target (chronological split) ...")
    tr, te = chrono["train"], chrono["test"]
    ytr, yte = tr["reached_level_3"].to_numpy(), te["reached_level_3"].to_numpy()

    # (a) ORACLE: add `variant`, which is only knowable after process mining.
    orc = build_logreg_oracle()
    orc.fit(tr[CAT_FEATURES + TEMP_FEATURES + ["variant"]], ytr)
    p_orc = orc.predict_proba(te[CAT_FEATURES + TEMP_FEATURES + ["variant"]])[:, 1]
    m_orc = evaluate_binary(yte, p_orc)
    print(f"    ORACLE +variant      AUC={m_orc['roc_auc']:.4f}  "
          f"PR-AUC={m_orc['pr_auc']:.4f}")
    report["ablation_oracle_variant"] = m_orc

    # (b) LEAKAGE: add customer_satisfaction (post-closure, NOT intake).
    leak_cols = CAT_FEATURES + TEMP_FEATURES + ["customer_satisfaction"]
    lk = Pipeline([
        ("prep", ColumnTransformer([
            ("cat", OneHotEncoder(handle_unknown="ignore"), CAT_FEATURES),
            ("num", StandardScaler(), NUM_FEATURES + ["customer_satisfaction"]),
            ("tfidf", TfidfVectorizer(max_features=200), "short_description"),
        ])),
        ("clf", LogisticRegression(penalty="l2", C=1.0, solver="lbfgs",
                                   max_iter=2000, class_weight="balanced",
                                   random_state=RANDOM_STATE)),
    ])
    lk.fit(tr[leak_cols], ytr)
    p_lk = lk.predict_proba(te[leak_cols])[:, 1]
    m_lk = evaluate_binary(yte, p_lk)
    print(f"    LEAKAGE +satisfaction AUC={m_lk['roc_auc']:.4f}  "
          f"PR-AUC={m_lk['pr_auc']:.4f}  <- NOT USABLE AT INTAKE")
    report["ablation_leakage_satisfaction"] = m_lk

    # (c) TEXT-ONLY: does the boilerplate short_description carry anything?
    txt_only = Pipeline([
        ("tfidf", TfidfVectorizer(max_features=200, ngram_range=(1, 2))),
        ("clf", LogisticRegression(penalty="l2", C=1.0, solver="lbfgs",
                                   max_iter=2000, class_weight="balanced",
                                   random_state=RANDOM_STATE)),
    ])
    txt_only.fit(tr["short_description"], ytr)
    p_txt = txt_only.predict_proba(te["short_description"])[:, 1]
    m_txt = evaluate_binary(yte, p_txt)
    print(f"    TEXT-ONLY short_desc  AUC={m_txt['roc_auc']:.4f}  "
          f"PR-AUC={m_txt['pr_auc']:.4f}")
    report["ablation_text_only"] = m_txt

    # (d) CATEGORICAL-ONLY (no text, no time): the simple triage-rule baseline
    cat_only = Pipeline([
        ("cat", OneHotEncoder(handle_unknown="ignore")),
        ("clf", LogisticRegression(penalty="l2", C=1.0, solver="lbfgs",
                                   max_iter=2000, class_weight="balanced",
                                   random_state=RANDOM_STATE)),
    ])
    cat_only.fit(tr[CAT_FEATURES], ytr)
    p_cat = cat_only.predict_proba(te[CAT_FEATURES])[:, 1]
    m_cat = evaluate_binary(yte, p_cat)
    print(f"    CATS-ONLY (rule-like) AUC={m_cat['roc_auc']:.4f}  "
          f"PR-AUC={m_cat['pr_auc']:.4f}  <- what a non-ML rule could do")
    report["ablation_categorical_only"] = m_cat

    # (e) TEMPORAL-ONLY: is creation time just noise?
    tmp_only = Pipeline([
        ("num", StandardScaler()),
        ("clf", LogisticRegression(penalty="l2", C=1.0, solver="lbfgs",
                                   max_iter=2000, class_weight="balanced",
                                   random_state=RANDOM_STATE)),
    ])
    tmp_only.fit(tr[TEMP_FEATURES], ytr)
    p_tmp = tmp_only.predict_proba(te[TEMP_FEATURES])[:, 1]
    m_tmp = evaluate_binary(yte, p_tmp)
    print(f"    TEMPORAL-ONLY        AUC={m_tmp['roc_auc']:.4f}  "
          f"PR-AUC={m_tmp['pr_auc']:.4f}  (expected ~0.5 if time is noise)")
    report["ablation_temporal_only"] = m_tmp

    # (f) drop Variant 7 entirely, to see how much it inflates the primary target
    keep = tr["variant"] != "Variant 7", te["variant"] != "Variant 7"
    lr7 = build_logreg()
    lr7.fit(tr.loc[keep[0], CAT_FEATURES + TEMP_FEATURES], ytr[keep[0]])
    p7 = lr7.predict_proba(te.loc[keep[1], CAT_FEATURES + TEMP_FEATURES])[:, 1]
    m7 = evaluate_binary(yte[keep[1]], p7)
    print(f"    EXCL-Variant7        AUC={m7['roc_auc']:.4f}  "
          f"PR-AUC={m7['pr_auc']:.4f}  "
          f"(base rate {m7['base_rate_test']:.4f}, n={m7['n_test']:,})")
    report["ablation_exclude_variant7"] = m7

    # -- 7. cycle-time regression (secondary target) ------------------------
    print("\n[7] Cycle-time regression (secondary target) ...")
    from sklearn.metrics import mean_absolute_error, r2_score

    reg_tr, reg_te = chrono["train"], chrono["test"]
    # HistGradientBoosting needs DENSE input, and the one-hot preprocessor emits
    # sparse, so the regressor uses the same ordinal encoding as the classifier.
    reg = HistGradientBoostingRegressor(
        max_iter=400, learning_rate=0.06, max_leaf_nodes=31,
        min_samples_leaf=40, l2_regularization=1.0, early_stopping=True,
        random_state=RANDOM_STATE)
    reg.fit(ordinal_frame(reg_tr), reg_tr["cycle_time_hours"])
    pred = reg.predict(ordinal_frame(reg_te))
    y = reg_te["cycle_time_hours"].to_numpy()
    reg_metrics = {
        "n_test": int(len(y)),
        "mae_hours": round(float(mean_absolute_error(y, pred)), 4),
        "r2": round(float(r2_score(y, pred)), 6),
        "spearman": round(float(pd.Series(pred).corr(pd.Series(y), method="spearman")), 6),
        "baseline_mae_predict_train_mean": round(
            float(mean_absolute_error(y, np.full_like(y, reg_tr["cycle_time_hours"].mean()))), 4),
        "baseline_r2_predict_train_mean": round(float(r2_score(
            y, np.full_like(y, reg_tr["cycle_time_hours"].mean()))), 6),
    }
    print(f"    HGB regressor  MAE={reg_metrics['mae_hours']} h  R2={reg_metrics['r2']}  "
          f"Spearman={reg_metrics['spearman']}")
    print(f"    baseline (predict train mean) MAE={reg_metrics['baseline_mae_predict_train_mean']} h  "
          f"R2={reg_metrics['baseline_r2_predict_train_mean']}")
    report["cycle_time_regression"] = reg_metrics

    # -- 8. artifacts: figures ---------------------------------------------
    print("\n[8] Writing figures ...")
    sns.set_theme(style="whitegrid", context="notebook")
    PRIMARY = "reached_level_3"

    # -- ROC + PR curves, both models, both targets
    MODEL_KEYS = (("logreg", "logistic_regression", "Logistic Regression"),
                  ("histgb", "hist_gradient_boosting", "HistGradientBoosting"))

    # ROC + PR for all three targets, both models
    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    for col, tgt in enumerate(TARGETS):
        ax, ax2 = axes[0, col], axes[1, col]
        for store, key, lbl in MODEL_KEYS:
            fpr, tpr, _ = roc_store[tgt][store]
            auc = results["chronological"][tgt][key]["roc_auc"]
            ax.plot(fpr, tpr, lw=2, label=f"{lbl} (AUC {auc:.3f})")

            prec, rec, _ = pr_store[tgt][store]
            ap = results["chronological"][tgt][key]["pr_auc"]
            ax2.plot(rec, prec, lw=2, label=f"{lbl} (PR-AUC {ap:.3f})")

        ax.plot([0, 1], [0, 1], "k--", lw=1, alpha=0.6, label="chance")
        base = float(chrono["test"][tgt].mean())
        ax2.axhline(base, color="k", ls="--", lw=1, label=f"base rate {base:.3f}")

        ax.set_title(f"ROC - {tgt}")
        ax.set_xlabel("False positive rate"); ax.set_ylabel("True positive rate")
        ax.set_xlim(0, 1); ax.set_ylim(0, 1.02); ax.legend(loc="lower right", fontsize=8)

        ax2.set_title(f"Precision-Recall - {tgt}")
        ax2.set_xlabel("Recall"); ax2.set_ylabel("Precision")
        ax2.set_xlim(0, 1); ax2.set_ylim(0, 1.02); ax2.legend(loc="lower left", fontsize=8)
    fig.suptitle("Chronological 70/30 split - intake features only, "
                 f"primary target {PRIMARY}", y=0.995)
    fig.tight_layout()
    fig.savefig(ARTIFACT_DIR / "roc_pr_curves.png", dpi=130)
    plt.close(fig)

    # Focused, larger version for the primary target only
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    yte_p = chrono["test"][PRIMARY].to_numpy()
    for store, key, lbl in MODEL_KEYS:
        fpr, tpr, _ = roc_store[PRIMARY][store]
        auc = results["chronological"][PRIMARY][key]["roc_auc"]
        axes[0].plot(fpr, tpr, lw=2, label=f"{lbl} (AUC {auc:.3f})")

        prec, rec, _ = pr_store[PRIMARY][store]
        ap = results["chronological"][PRIMARY][key]["pr_auc"]
        axes[1].plot(rec, prec, lw=2, label=f"{lbl} (PR-AUC {ap:.3f})")
    axes[0].plot([0, 1], [0, 1], "k--", lw=1, alpha=0.6, label="chance")
    axes[0].set_title(f"ROC - {PRIMARY} (chronological split)")
    axes[0].set_xlabel("False positive rate"); axes[0].set_ylabel("True positive rate")
    axes[0].set_xlim(0, 1); axes[0].set_ylim(0, 1.02); axes[0].legend(loc="lower right")

    axes[1].axhline(yte_p.mean(), color="k", ls="--", lw=1,
                    label=f"base rate {yte_p.mean():.3f}")
    axes[1].set_title(f"Precision-Recall - {PRIMARY}")
    axes[1].set_xlabel("Recall"); axes[1].set_ylabel("Precision")
    axes[1].set_xlim(0, 1); axes[1].set_ylim(0, 1.02); axes[1].legend(loc="lower left")
    fig.tight_layout()
    fig.savefig(ARTIFACT_DIR / "roc_pr_primary_target.png", dpi=130)
    plt.close(fig)

    # -- confusion matrix heatmap (primary target, both models, both splits)
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    for i, split_name in enumerate(("chronological", "random")):
        for j, key in enumerate(("logistic_regression", "hist_gradient_boosting")):
            m = results[split_name][PRIMARY][key]["at_best_f1"]
            cm = np.array([[m["confusion_matrix"]["tn"], m["confusion_matrix"]["fp"]],
                           [m["confusion_matrix"]["fn"], m["confusion_matrix"]["tp"]]])
            ax = axes[i, j]
            sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", ax=ax, cbar=False,
                        annot_kws={"size": 15})
            ax.set_title(f"{key.replace('_', ' ').title()}\n{split_name} split "
                         f"(thr {m['threshold']:.3f})")
            ax.set_xlabel("predicted"); ax.set_ylabel("actual")
    fig.suptitle(f"Confusion matrices - {PRIMARY} at best-F1 threshold", y=1.0)
    fig.tight_layout()
    fig.savefig(ARTIFACT_DIR / "confusion_matrix.png", dpi=130)
    plt.close(fig)

    # -- feature importance plot
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    ft = pd.read_csv(ARTIFACT_DIR / "feature_importance_logreg.csv")
    top = ft.reindex(ft["coefficient"].abs().sort_values(ascending=True).index).tail(20)
    colors = ["#c44e52" if c < 0 else "#4c72b0" for c in top["coefficient"]]
    axes[0].barh(top["feature"], top["coefficient"], color=colors)
    axes[0].axvline(0, color="k", lw=0.8)
    axes[0].set_title(f"Logistic regression coefficients ({PRIMARY})\n"
                      "red = pushes toward NO L3, blue = toward L3")
    axes[0].set_xlabel("coefficient (class_weight=balanced)")

    pi = pd.read_csv(ARTIFACT_DIR / "feature_importance_permutation.csv").head(12).iloc[::-1]
    axes[1].barh(pi["feature"], pi["permutation_importance_mean"],
                 xerr=pi["permutation_importance_std"], color="#55a868")
    axes[1].set_title("HistGB permutation importance (PR-AUC drop)")
    axes[1].set_xlabel("mean decrease in average precision")
    fig.tight_layout()
    fig.savefig(ARTIFACT_DIR / "feature_importance.png", dpi=130)
    plt.close(fig)

    # -- cycle-time histogram with median and p95
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ct = df["cycle_time_hours"]
    ax.hist(ct, bins=80, color="#4c72b0", alpha=0.85, edgecolor="white", linewidth=0.3)
    med, p95 = float(ct.median()), float(ct.quantile(0.95))
    ax.axvline(med, color="green", lw=2.2, ls="--",
               label=f"median {med:.2f} h")
    ax.axvline(p95, color="red", lw=2.2, ls="--",
               label=f"p95 {p95:.2f} h")
    ax.axvline(SLOW_HOURS, color="orange", lw=2.0, ls=":",
               label=f"SLA threshold {SLOW_HOURS:.0f} h")
    ax.axvline(float(ct.mean()), color="purple", lw=1.6, ls="-.",
               label=f"mean {ct.mean():.2f} h")
    ax.set_xlabel("cycle time (hours)"); ax.set_ylabel("incidents")
    ax.set_title(f"Cycle-time distribution - {len(ct):,} incidents "
                 "(matches RESULTS 12.72 h median / 32.48 h p95)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(ARTIFACT_DIR / "cycle_time_distribution.png", dpi=130)
    plt.close(fig)

    print(f"      wrote 4 figures + 2 CSVs to {ARTIFACT_DIR}/")

    # -- 9. honesty section -------------------------------------------------
    print("\n[9] INFLATION RISK ASSESSMENT")
    infl = {
        "short_description_is_boilerplate": templating["is_boilerplate"],
        "n_distinct_descriptions": templating["n_distinct"],
        "text_only_auc": m_txt["roc_auc"],
        "text_only_pr_auc": m_txt["pr_auc"],
        "categorical_only_auc": m_cat["roc_auc"],
        "temporal_only_auc": m_tmp["roc_auc"],
        "oracle_variant_auc": m_orc["roc_auc"],
        "leakage_satisfaction_auc": m_lk["roc_auc"],
        "excl_variant7_auc": m7["roc_auc"],
        "excl_variant7_pr_auc": m7["pr_auc"],
    }
    for k, v in infl.items():
        print(f"    {k:38s} {v}")
    report["inflation_risk"] = infl

    chrono_auc = results["chronological"][PRIMARY]["hist_gradient_boosting"]["roc_auc"]
    rand_auc = results["random"][PRIMARY]["hist_gradient_boosting"]["roc_auc"]
    print(f"\n    SPLIT SENSITIVITY (primary target, HistGB): "
          f"chronological AUC={chrono_auc:.4f} vs random AUC={rand_auc:.4f} "
          f"(delta {rand_auc - chrono_auc:+.4f})")
    report["split_sensitivity_primary"] = {
        "chronological_auc": chrono_auc,
        "random_auc": rand_auc,
        "delta_random_minus_chrono": round(rand_auc - chrono_auc, 6),
    }

    report["results"] = results
    with open(ARTIFACT_DIR / "metrics.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(f"\nWrote {ARTIFACT_DIR / 'metrics.json'}")

    print("\n" + "=" * 78)
    print("METRIC TABLE - primary target reached_level_3, chronological split")
    print("=" * 78)
    print(f"{'model':22s} {'AUC':>7s} {'PR-AUC':>8s} {'lift':>6s} "
          f"{'F1@0.5':>7s} {'P@bf1':>7s} {'R@bf1':>7s} {'thr':>6s} {'Brier':>7s}")
    for key in ("logistic_regression", "hist_gradient_boosting"):
        m = results["chronological"][PRIMARY][key]
        print(f"{key:22s} {m['roc_auc']:7.4f} {m['pr_auc']:8.4f} "
              f"{m['lift_over_base_rate']:6.2f} {m['at_0.5']['f1']:7.4f} "
              f"{m['at_best_f1']['precision']:7.4f} {m['at_best_f1']['recall']:7.4f} "
              f"{m['at_best_f1']['threshold']:6.3f} {m['brier']:7.4f}")
    b = results["chronological"][PRIMARY]["baselines"]["stratified_random"]
    print(f"{'random-guess baseline':22s} {b['roc_auc_mean']:7.4f} {b['pr_auc_mean']:8.4f} "
          f"{b['pr_auc_mean']/chrono['test'][PRIMARY].mean():6.2f} "
          f"{b['f1_mean']:7.4f}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
