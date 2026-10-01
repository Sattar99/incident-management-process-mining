# Irish Economy Data Platform — Project 2: Incident Process Optimization

Automated pipeline that turns a raw incident event log into a tested, queryable
process-mining model and a set of evidence-backed recommendations.

**Status:** Analysis complete, pipeline tested and reproducible.
**Scope:** 242,901 events · 31,588 incidents · 13 process variants · 2023-01-01 → 2024-01-02
**Stack:** Python 3.11 · pandas · PostgreSQL 18 · SQL · Power BI (target)

---

## Architecture

```
Incident_Management_CSV.csv   (28 MB raw event log, semicolon-delimited)
        │
        │  etl_pipeline.py — parse, validate, load
        ▼
PostgreSQL  Incident_Management.incident_data   (242,901 rows, verified)
        │
        │  sql/01_views.sql — metric contract
        ▼
   v_case_metrics          one row per incident
   v_transition_metrics    one row per state transition
        │
        │  analytics.py — execute sql/*.sql, export CSV
        ▼
   data/*.csv  (17 exports)  ──►  Power BI dashboards
        │
        │  tests/test_pipeline.py — 18 assertions
        ▼
   Regression guard rails
        │
        │  ml_triage.py — intake-triage classifier (investigation)
        ▼
   ml_artifacts/  (metrics, ablations, plots, models)
        ▼
   ML_FINDINGS.md — negative result + Variant 6 discovery
```

The ML layer is a separate, downstream investigation. It reads the same verified
database, it is not part of the reporting path, and **no model in `ml_artifacts/` is
deployable** — see [`ML_FINDINGS.md`](ML_FINDINGS.md).

PostgreSQL is the single source of truth. The CSVs in `data/` are exports for
BI and inspection, not intermediate artifacts.

---

## Layout

| Path | Purpose |
|---|---|
| `etl_pipeline.py` | Raw CSV → PostgreSQL + `incidents_clean.csv`. Validates and verifies load parity. |
| `analytics.py` | Executes `sql/*.sql`, writes `data/*.csv`. |
| `ml_triage.py` | ML intake-triage investigation. Chronological + random splits, two model families, 6 ablations. **Built and rejected on the evidence** — no deployable model. |
| `ML_FINDINGS.md` | Write-up of the ML investigation: the negative result, the Variant 6 discovery, limitations. |
| `sql/01_views.sql` | `v_case_metrics`, `v_transition_metrics` — the metric contract. |
| `sql/02_kpis.sql` | Headline KPIs, breakdowns, escalation impact, priority/SLA. |
| `sql/03_bottlenecks.sql` | Transition bottlenecks, Variant 7 deep-dive, rework loops. |
| `sql/04_data_quality.sql` | Quantified source-data defects. |
| `sql/05_provenance.sql` | Structural determinism checks. Quantifies the unresolved real-vs-generated question (`RESULTS_AND_SUGGESTIONS.md` §7a). |
| `tests/test_pipeline.py` | 18 assertions: load parity, metric correctness, known defects. |
| `tests/make_fixture.py` | Generates the small CI dataset (real source is git-ignored). |
| `.github/workflows/ci.yml` | ETL → SQL → tests on every push/PR. |
| `requirements.txt` | Pinned runtime + test dependencies. |
| `incidents_clean.csv` | Case-level export (31,588 rows). Generated. |
| `data/` | Report exports. Generated, git-ignored. |
| `ml_artifacts/metrics.json` | Every metric from the ML run, including all six ablations. |
| `ml_artifacts/run_log.txt` | Full console output of the training run. |
| `ml_artifacts/INTERPRETATION.md` | First-pass interpretation of the ML results. |
| `ml_artifacts/REVIEW.md` | Self-review: read-only re-derivation of every figure in that interpretation, and the corrections it forced. |
| `ml_artifacts/*.png`, `*.csv` | ROC/PR curves, confusion matrices, feature importance, permutation importance. |
| `ml_artifacts/*.pkl` | Fitted models. Reproduction artifacts only — **not deployable**, fitted on a label that is a function of `variant`. |
| `archive/` | Superseded notebooks and `.pgsql` files, kept for provenance. |

---

## How to run

**Prerequisites:** PostgreSQL running locally, reachable on `localhost:5432`.

```bash
pip install pandas sqlalchemy psycopg2-binary pytest
```

Connection settings come from standard `PG*` environment variables
(`PGUSER`, `PGPASSWORD`, `PGHOST`, `PGPORT`, `PGDATABASE`). Defaults:
`postgres` / `0000` / `localhost` / `5432` / `Incident_Management`.

```bash
python etl_pipeline.py     # 1. load 242,901 rows + write incidents_clean.csv
python analytics.py        # 2. build views, run all SQL, write data/*.csv
python -m pytest tests/ -v # 3. verify (18 tests)

python ml_triage.py        # 4. optional: re-run the ML investigation (~4 min)
```

Step 4 is optional and read-only against the loaded database. It reproduces
`ml_artifacts/` and is not required by CI — the finding it produced is a
falsification, so there is nothing downstream that depends on it.

Each stage is independent. `analytics.py --sql 03_bottlenecks.sql` runs a single
report. `etl_pipeline.py --skip-load` regenerates the CSV without touching the
database.

> **Ordering note:** `etl_pipeline.py` drops and recreates `incident_data` with
> `CASCADE`, which also drops the reporting views. Always run `analytics.py`
> (or `sql/01_views.sql`) after a reload. The test suite recreates the views
> itself, so tests pass either way.

---

## Data model

`incident_data` — one row per event.

| Column | Type | Notes |
|---|---|---|
| `event_id` | bigserial | Surrogate key |
| `case_id` | text | 31,588 distinct |
| `variant` | text | Process path, 13 distinct |
| `priority` | text | High / Medium / Low |
| `reporter` | text | |
| `event_timestamp` | timestamp | Source format `DD/MM/YYYY HH:MM` |
| `event` | text | 18 distinct; 1 NULL (see Known data defects) |
| `issue_type` | text | 7 distinct |
| `resolver` | text | NULL on 96,496 rows — structural, not missing |
| `report_channel` | text | App / Email / Website / Phone |
| `short_description` | text | Free text |
| `customer_satisfaction` | integer | 1–5, capped at 3 for some variants |

**Views**

- `v_case_metrics` — one row per incident: cycle time, event/resolver counts,
  step-duration percentiles, escalation and completion flags.
- `v_transition_metrics` — one row per observed transition `A -> B`, with the
  time spent in `A`.

---

## Timing methodology

This is the one methodological decision that matters, and it was wrong in the
earlier version of this project.

The original `Bottleneck_Identification.pgsql` used `LAG(timestamp)` and then
labelled the resulting interval with the event that came **after** the wait. So
"Ticket escalated to level 2 support — 4.36 hrs" was really reporting time
spent in **WIP - level 1 support** before the escalation.

Process mining measures time in a state as the interval from that state to the
**next** event, so attribution must be forward-looking:

```
step_seconds       = next_timestamp - timestamp     (time spent in the current state)
cycle_time_seconds = last_event    - first_event    (per incident)
```

Both views implement this. Consequence: the real bottlenecks are **WIP states
and intake**, not escalation events.

---

## Findings

Full detail and evidence in [`RESULTS_AND_SUGGESTIONS.md`](RESULTS_AND_SUGGESTIONS.md).

| Metric | Value |
|---|---|
| Incidents | 31,588 |
| Mean cycle time | 15.03 h |
| Median cycle time | 12.72 h |
| p95 cycle time | 32.48 h |
| Mean events per incident | 7.69 |

Headlines:

1. **72.8% of all elapsed time sits in three states** — `WIP - level 1 support`
   (28.8%), `Ticket created` (25.9%), `WIP - level 2 support` (18.2%).
2. **Escalation is the dominant driver** — escalated incidents average 17.40 h
   vs 11.53 h for those that never escalate (+51%), and 59.7% escalate.
3. **Priority is inverted** — `Low` priority averages 25.76 h vs `High` at
   6.23 h. Holds within every issue type and every variant, so it is not
   confounding.
4. **Variant 7 is a distinct failure mode** — 1,261 incidents, 100% Bugs, 100%
   reach L3, mean 26.64 h (1.8× the rest), satisfaction capped at 3.
5. **Variant 6 is a second 100%-L3 variant** — 718 incidents, every one reaches L3,
   mean 18.74 h. Missed by the original analysis, caught in the ML layer; see below.

---

## ML investigation — negative result, and the Variant 6 finding

> Added after the process analysis. Full write-up: [`ML_FINDINGS.md`](ML_FINDINGS.md).
> Read this before quoting any AUC figure from this project.

I built a classifier to test the proposal in `RESULTS_AND_SUGGESTIONS.md` §6: an
intake-time model over the free-text `short_description` field that would flag
likely L3 escalations before the ~4 h L1 attempt is spent. **The hypothesis was
falsified.** The value of the layer is the clean negative, the methodology that made
it conclusive, and a structural discovery the process analysis had missed.

### The headline: `reached_level_3` is a lookup, not a prediction

Predicting `reached_level_3` at intake reached **ROC-AUC 0.84**. That number must not
be read as escalation foresight, and the reason is the most important finding in the
project:

| Group | Cases | Reach L3 | Rate | Mean cycle h |
|---|---:|---:|---:|---:|
| **Variant 7** | 1,261 | 1,261 | **100%** | 26.64 |
| **Variant 6** | **718** | **718** | **100%** | **18.74** |
| All 11 other variants | 29,609 | 0 | **0%** | 14.45 |

`reached_level_3` is an **exact deterministic function of variant membership** —
1,979 of 1,979 L3 cases are Variant 6 or Variant 7, and *no variant has a mixed L3
outcome*. Excluding both leaves **29,609 cases with zero positives**, a base rate of
exactly 0.0000. An ablation that adds `variant` as a feature scores **AUC 1.0000**,
which confirms the label was defined by clustering the thing being predicted.

So the 0.84 measures cluster recovery from a generator's fingerprint, not prediction.
The useful consequence is better than the model would have been: **L3 escalation is
fully enumerable by variant membership, today, with SQL.**

### Variant 6 was missing from the project

The original analysis documented Variant 7 as *the* L3 failure mode. Variant 6 has
the same 100%-L3 structure and was absent from every document. It is not a Bug loop —
it spans all 7 issue types and all 8 description strings. Its signature is structural: a
fixed nine-transition path with 718/718 occurrences of each step, and a **single-pass**
L3 route with **no** rework loop, unlike Variant 7's mandatory double-pass.

That distinction is operationally useful: Variant 7 needs rework-loop remediation,
Variant 6 is a clean one-pass path that always terminates in L3. They should not share
a fix. `RESULTS_AND_SUGGESTIONS.md` §5, §6 and §7 need Variant 6 added.

### Why the text classifier cannot be built

`short_description` has **8 distinct values across 31,588 cases** (longest 21 chars) —
`New feature request`, `Application crash`, `Data loss issue`, and five more. It is
boilerplate, and largely a re-encoding of `issue_type` (normalised mutual information
0.6055). A text-only model reaches PR-AUC 0.1819. **The §6 proposal should be struck,
not softened.**

Two further results, both negative and both useful:

- **Gradient boosting bought nothing.** A categorical-only logistic regression
  (AUC 0.8408) matched the full pipeline (AUC 0.8400) — ~0.004 AUC for all the added
  complexity.
- **The best-looking model was redundant.** `slow_24h` at AUC 0.9326 is reproduced by
  `WHERE priority = 'Low'` (precision 0.5503, recall 0.9847). The model wins best-F1 by
  1.1 points; the rule wins at matched recall by 8.3. And `priority` was a model input,
  so the "independent rediscovery" was partly circular.

### What was done right

Leakage was actively controlled and the cost was reported rather than hidden:
`customer_satisfaction` (a post-closure survey denormalised onto every row) was excluded,
which cost 0.09 PR-AUC — 0.4029 instead of 0.4934. `variant` was quarantined as an
oracle instead of published as performance. Chronological and random splits differ by
only 0.0056 AUC, so there is no temporal drift. Base rates were reported before every
metric.

### What it did not establish

The ML layer **did not test the headline strategic recommendation** in
`RESULTS_AND_SUGGESTIONS.md` §6 (shorter L1 attempts, faster intake). That rests on the
process analysis alone and **remains unvalidated**. If anything two findings weaken its
premise: temporal features carry no duration signal (AUC 0.5280), and intake wait scales
with priority at the same rate as L1 work (×1.88 and ×1.88 for Medium; ×3.95 and ×3.83
for Low) — which is not what a congested queue looks like.

### The unresolved question that gates all of it

**Whether this dataset is real operational data or generated with `priority` and
`variant` as deterministic parameters is not established, and it cannot be settled from
the log.** Evidence pointing toward generated: all 13 variants have exactly one event
sequence each; event count has zero variance within Variant 6 (10 for all 718) and
Variant 7 (15 for all 1,261); two variants are 100% L3 and eleven are 0%; and
`priority` multiplies intake and work dwell times by nearly identical factors. Evidence
against over-claiming: this is consistent with a generator, not proof of one, and only
the data owner can answer it.

If the data is generated, the priority inversion is a generator parameter and every
operational recommendation in §6 describes the generator rather than a process. **Until
that is answered, the defensible scope of this project is its data engineering, its
method, and the two findings above.**

---

## Known data defects

Quantified in `sql/04_data_quality.sql`. These are properties of the source
data, documented so the metrics are read correctly:

| Defect | Extent | Handling |
|---|---|---|
| NULL `event` name | 1 row (`INC0305`) | Excluded from `v_transition_metrics`; test asserts exactly 1 |
| NULL `resolver` | 96,496 rows (39.8%) | Structural — system transitions have no owner. **Not** filled with a placeholder |
| Satisfaction capped at 3 | 4 variants (5,035 incidents) | Cross-variant satisfaction comparisons are not valid |
| Out-of-order timestamps | 0 | Asserted |
| Zero event-sequence variance | All 13 variants have exactly one event sequence | Structural determinism; see `ML_FINDINGS.md` §6.1 |
| `reached_level_3` fully determined by `variant` | 1,979 of 1,979 L3 cases are Variant 6 or 7 | Not a modelling target; enumerate by variant |

On the `resolver` point specifically: an earlier notebook filled NULLs with the
literal `"Unknown"`, which inflated `COUNT(DISTINCT resolver)` by one per
affected case — Variant 7 read **7.53** resolvers instead of the correct
**6.53**. The current pipeline leaves NULLs as NULL.

---

## CI

`.github/workflows/ci.yml` runs on every push and pull request to `main`:
installs dependencies → waits for a PostgreSQL 16 service container → generates
a fixture dataset → runs the ETL → runs all SQL reports → runs the tests. Report
exports are attached as a build artifact.

The real 28 MB source is git-ignored, so CI uses a **generated fixture**
(`tests/make_fixture.py`) with the identical schema and delimiter. It reproduces
the awkward cases on purpose — a NULL event name, NULL resolvers on system
transitions, an L3 rework loop, capped satisfaction scores — so the edge-case
handling is genuinely exercised.

The tests that matter most are the **parity** assertions, which compare the
database against whatever file was loaded rather than against hardcoded totals.
That is what makes CI meaningful here: a truncated `COPY` fails the build in the
same way it silently corrupted production metrics. Absolute-scale assertions
(242,901 rows / 31,588 cases) only run against the real dataset and skip on CI.

```bash
# Reproduce the CI sequence locally
python tests/make_fixture.py --out /tmp/fixture.csv
INCIDENT_RAW_FILE=/tmp/fixture.csv python etl_pipeline.py --raw /tmp/fixture.csv
INCIDENT_RAW_FILE=/tmp/fixture.csv python analytics.py
INCIDENT_RAW_FILE=/tmp/fixture.csv python -m pytest tests/ -v
```

---

## Testing

```bash
python -m pytest tests/ -v
```

18 assertions covering source parsing, load parity, per-case completeness, and
metric correctness (the SQL views are cross-checked against an independent
pandas computation).

These exist because of a specific failure. An earlier
`to_sql(chunksize=5000, method="multi")` load died partway and committed
**55,000 of 242,901 rows** without raising. Every KPI in the project was then
computed on 22.6% of the data for two days. `test_db_row_count_matches_source`
and `test_no_case_is_partially_loaded` exist specifically to make that failure
loud; both were confirmed to fail against a deliberately truncated table.

The load itself now uses a single transactional `COPY`, so a failure leaves the
table empty rather than half-populated, and parity is verified before and after.

---

## Power BI

Connect to `Incident_Management` → `v_case_metrics` (incident grain) and
`v_transition_metrics` (transition grain). Suggested visuals:

- Median cycle time by variant (bar) — exposes the Variant 7 outlier
- Cycle time distribution by priority (histogram with a 24 h SLA line)
- Total hours by state (bar) — the 72.8% concentration
- Escalation rate by issue type (bar) — Bug diverges at 43.8% escalation / 21.9% L3
- Variant 7 transition heat map — the 11-step loop with a double L3 pass

Use import mode; the views are small (31,588 and 211,311 rows).

---

## License

MIT