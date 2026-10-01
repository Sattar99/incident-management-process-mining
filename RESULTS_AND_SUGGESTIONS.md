# Data-Driven Process Insights & Recommendations

**Project:** Incident Management Process Optimization (Project #2)
**Source:** `Incident_Management_CSV.csv` → PostgreSQL `Incident_Management.incident_data`
**Volume:** 242,901 events · 31,588 incidents · 13 variants · 2023-01-01 → 2024-01-02
**Reproduce:** `python etl_pipeline.py && python analytics.py`

> **All figures below are computed from the complete, verified 242,901-row load.**
> The previous version of this document reported figures derived from a
> truncated 55,000-row table (22.6% of the data). Those numbers were wrong and
> have been superseded. See *Corrections to the previous analysis* at the end.

---

## 1. Performance summary

| Metric | Value | Notes |
|---|---:|---|
| Incidents | 31,588 | One row per `case_id`, no duplicates |
| **Mean cycle time** | **15.03 h** | Creation → closure |
| **Median cycle time** | **12.72 h** | Better SLA target than the mean |
| p75 cycle time | 19.73 h | |
| p95 cycle time | 32.48 h | Tail is long |
| Max cycle time | 56.32 h | Outlier |
| Mean events per incident | 7.69 | Average path length |
| Mean distinct resolvers | 2.90 | Excludes NULL (system transitions) |
| Mean satisfaction | 3.26 | See caveat in §7 |

The mean exceeds the median by 2.3 h, so the distribution is right-skewed: a
minority of very slow incidents pulls the average up. **Use the median (12.72 h)
as the operational target.**

---

## 2. Where the time actually goes

Total elapsed process time: **474,822 hours** across 211,311 transitions.
This is the decision-relevant view — mean-per-transition understates states that
affect nearly every incident.

| State | Total hours | Share | Cases touched |
|---|---:|---:|---:|
| `WIP - level 1 support` | 136,570 | **28.8%** | 32,223 |
| `Ticket created` | 122,783 | **25.9%** | 31,588 |
| `WIP - level 2 support` | 86,502 | **18.2%** | 21,955 |
| `Ticket assigned to level 1 support` | 32,076 | 6.8% | 31,250 |
| `Customer feedback received` | 31,075 | 6.5% | 30,338 |

**Three states hold 72.8% of all process time.** Two of them are *work-in-progress
queues* and the third is *intake* — the wait between a ticket being created and
someone picking it up. Nothing in the top five is an escalation event.

Mean dwell time per transition:

| Transition | Mean h | Median h | p95 h | Cases |
|---|---:|---:|---:|---:|
| `WIP - level 1 support → Ticket escalated to level 2 support` | 4.36 | 3.88 | 9.28 | 625 |
| `WIP - level 1 support → Level 1 escalates to level 2 support` | 4.23 | 3.82 | 8.93 | 18,215 |
| `WIP - level 1 support → Ticket solved by level 1 support` | 4.23 | 3.82 | 9.01 | 11,475 |
| `WIP - level 2 support → Level 2 escalates to level 3 support` | 3.98 | 3.62 | 8.67 | 1,979 |
| `Ticket created → Ticket assigned to level 1 support` | 3.88 | 3.43 | 8.60 | 30,625 |

The pattern is unambiguous: **~4 hours of L1 work per attempt**, then ~1 hour per
subsequent hand-off. The cost is in attempt duration, not in hand-offs.

---

## 3. Escalation is the dominant driver

| Escalated | Incidents | Share | Mean cycle h | Median h | Satisfaction |
|---|---:|---:|---:|---:|---:|
| No | 12,747 | 40.35% | 11.53 | 9.50 | 3.41 |
| **Yes** | **18,841** | **59.65%** | **17.40** | **14.17** | **3.16** |

Escalated incidents take **51% longer** and score 0.25 points lower.

Escalation rate by issue type — Bug behaves completely differently:

| Issue type | Incidents | Escalation rate | Reaches L3 | Mean h (no esc.) | Mean h (esc.) |
|---|---:|---:|---:|---:|---:|
| Performance Issue | 8,128 | **76.4%** | 1.3% | 11.49 | 16.35 |
| Incident | 4,463 | 58.8% | 2.5% | 11.54 | 16.75 |
| Technical Issue | 1,515 | 58.5% | 2.8% | 12.15 | 16.50 |
| Maintenance | 1,558 | 57.8% | 2.8% | 11.30 | 17.13 |
| Feature Request | 6,118 | 57.8% | 2.0% | 11.45 | 16.96 |
| Service Request | 3,002 | 56.9% | 2.0% | 11.35 | 16.48 |
| **Bug** | **6,804** | **43.8%** | **21.9%** | 11.59 | **21.59** |

Two distinct regimes:

- **Performance Issues escalate most (76.4%) but resolve quickly when they do** (16.35 h). They escalate and come back.
- **Bugs escalate least (43.8%) but go to L3 far more (21.9%) and take 21.59 h.** When a Bug escalates it tends to stay escalated.

A single "escalation" metric hides this. **Bug escalation should be tracked as a separate SLA.**

---

## 4. Priority is inverted — lower priority, longer resolution

| Priority | Incidents | Mean h | Median h | Over 24 h | Satisfaction |
|---|---:|---:|---:|---:|---:|
| **Low** | 9,348 | **25.76** | 25.07 | **55.0%** | 3.25 |
| Medium | 15,774 | 12.28 | 11.93 | 0.5% | 3.26 |
| High | 6,466 | **6.23** | 6.05 | **0.0%** | 3.26 |

Low-priority incidents take **4.1× longer** than High, and **55% of them breach
24 hours while no High-priority incident ever does.**

I checked whether this was an artefact of Bug concentration. It is not:

- Priority mix is near-identical across all 7 issue types (~30% Low, ~20% High).
- Within **Bugs alone**: Low 27.28 h · Medium 12.96 h · High 6.56 h.
- Within **Variant 7 alone**: Low 45.03 h · Medium 21.63 h · High 10.54 h.
- The ordering is identical in every variant tested.

**Interpretation:** priority in this dataset is not tracking urgency. Either it
is assigned *after* the fact (when an incident is already known to be hard), or
Low is a holding bucket that never gets worked. Satisfaction is flat across
priority (3.25–3.26), which is what you would expect if the customer never
perceives the priority label — only the wait.

This is the highest-leverage question in the dataset and it cannot be resolved
from event logs alone. It needs a process owner to confirm how `priority` is
set.

---

## 5. Variant 7 is a distinct failure mode

| | Variant 7 | All others |
|---|---:|---:|
| Incidents | 1,261 | 30,327 |
| Mean cycle h | **26.64** | 14.55 |
| Median cycle h | **22.25** | 12.50 |
| Mean events | **15.0** | 7.39 |
| Mean resolvers | 6.53 | — |
| Reaches L3 | **100%** | 2.37% |
| Issue type | **100% Bug** | Mixed |
| Mean satisfaction | 1.90 | 3.26 |

Variant 7 is not a normal path with a longer tail — it is a **closed loop
specific to Bugs**. All 1,261 incidents are Bugs, and all of them reach L3.

Its 11-step sequence, with dwell times (present in 100% of cases):

| # | Transition | Mean h | Occurrences |
|---:|---|---:|---:|
| 1 | `WIP - level 1 support → Level 1 escalates to level 2 support` | **4.28** | 1,261 |
| 2 | `WIP - level 2 support → Level 2 escalates to level 3 support` | **3.98** | **2,522** |
| 3 | `Ticket created → Ticket assigned to level 1 support` | **3.95** | 1,261 |
| 4 | `Customer feedback received → Ticket closed` | 1.06 | 1,261 |
| 5–11 | All remaining hand-offs | 1.03–1.05 | 1,261–2,522 |

Four events occur **exactly twice** in every single case (2,522 occurrences /
1,261 cases):

- `Level 2 escalates to level 3 support`
- `WIP - level 3 support`
- `Ticket assigned to level 2 support`
- `WIP - level 2 support`

This is a **mandatory rework cycle**: every Variant 7 Bug is escalated to L3,
then bounced *back* to L2 for a second pass, then closed. It is 100% consistent
across all 1,261 incidents — no variance at all, which is unusual in real
operational data and suggests the process is at least partly deterministic or
synthetic.

**The three long steps average 4.12 h across 2,522 transitions, contributing
8.23 h per incident — 30.9% of the 26.64 h average.**

## 5a. Variant 6 is a second deterministic L3 process — added after review

*This section was not in the original analysis. It was found during adversarial
review of the ML layer, and it corrects an omission in §5.*

| | Variant 6 | Variant 7 | All others |
|---|---:|---:|---:|
| Incidents | 718 | 1,261 | 29,608 |
| Mean cycle h | **18.74** | **26.64** | 14.55 |
| Reaches L3 | **100%** | **100%** | 0% |
| Mean events | 10 | 15 | 7.39 |
| Mandatory rework loop | No | Yes | No |
| Issue type | Mixed | 100% Bug | Mixed |

**`reached_level_3` is an exact function of variant membership.** All 1,979 L3
cases in the dataset are Variant 6 (718) or Variant 7 (1,261). The remaining
**29,609 cases — 93.7% of all incidents — contain zero L3 cases**, and no variant
has a mixed L3 outcome. Verified in `sql/05_provenance.sql`.

Two consequences:

1. "Predict which tickets reach L3 at intake" was never a well-posed question.
   The answer is already carried by the variant label. An intake classifier
   scoring AUC 0.84 was recovering a cluster membership, not forecasting.
2. Variant 6 is a genuine operational finding, not a statistical artefact. It is
   718 cases moving 2.4× slower than the median for a reason that has nothing to
   do with escalation difficulty — every one of them escalates.

**Why it was missed:** Variant 6's 18.74 h mean is unremarkable beside Variant 7's
26.64 h, so it never looked like an outlier. It was sitting in
`data/cycle_time_by_variant.csv` the whole time. The original §5 examined
variants for *slowness*; this one is only anomalous on the L3 axis.

---

## 6. Recommendations

> **Validation status — read this first.** The Strategic recommendation below is
> **NOT validated by experiment.** It rests entirely on descriptive statistics from
> a single year of observational data. No analysis in this project has tested
> whether reducing intake latency or L1 attempt time actually reduces cycle time;
> that requires a controlled before/after trial, which cannot be done retrospectively
> from event logs. The ML layer did not test it either. Read it as a
> well-evidenced hypothesis about where time is spent, not as a proven lever.

### Strategic

> Cycle time is not lost at escalation — it is accumulated in the **L1 work queue**
> and in **intake**. Three states hold 72.8% of all elapsed time, and every
> escalation attempt costs ~4.2 h of L1 effort before handing off. The highest-ROI
> intervention is therefore **not** faster escalation but **shorter L1 attempts and
> faster first assignment**: every incident waits 3.89 h in `Ticket created` before
> first assignment, and `WIP - level 1` accounts for 28.8% of all process time.
> Cutting intake latency by 1 h and L1 attempt time by 20% would remove roughly
> 2 h (~16%) from the median incident.

### Tactical

1. **Attack intake first.** Every one of the 31,588 incidents waits in
   `Ticket created` before first assignment, averaging 3.89 h (median 3.43 h).
   The state alone is 25.9% of all process time. Auto-assign on intake by
   product area or reporter. Cheapest win available.

2. **Set a WIP limit on the L1 queue.** `WIP - level 1 support` is 28.8% of all
   time. A WIP limit forces work to be finished before new work is accepted,
   which is the standard remedy for exactly this queueing pattern.

3. **Alert on the ~4.2 h L1 attempt.** Every transition *out of*
   `WIP - level 1 support` averages 4.24 h (p95 = 8.97 h). Flag any L1 case still
   open after 4 h — that threshold catches the majority of stalled work, and the
   p95 shows roughly 1 in 20 will run to 9 h.

4. **Separate Bug escalation from Performance Issue escalation.** They are
   different problems: Performance Issues escalate fast and return (76.4% → 16.35 h),
   Bugs escalate slow and stay (43.8% → 21.59 h, 21.9% reach L3). One combined
   escalation metric hides both.

5. **Investigate the priority inversion before acting on it.** Low priority takes
   4.1× longer than High and holds every 24 h breach in the dataset. Do not
   build an SLA on `priority` until a process owner confirms how it is assigned.

6. **Treat Variants 6 and 7 as separate processes, not variants.** Both are
   100% L3 by construction. Variant 7 is 1,261 cases at 26.64 h with a mandatory
   double-pass rework loop; **Variant 6 is a second such process — 718 cases at
   18.74 h, also 100% L3** (see §5a, added after review). Neither resembles the
   other 11 variants. They need their own workflow, SLA, and ownership. Measuring
   them as "Variant 6" and "Variant 7" alongside 11 normal paths hides that they
   are a different kind of animal.

### Longer term

**The previously proposed ML layer has been built, tested, and rejected on the
evidence. See [`ML_FINDINGS.md`](ML_FINDINGS.md) for the full write-up.**

> **FALSIFIED — withdrawn 2026-10-01.** This section previously proposed a text
> classifier over `short_description` to route likely-Variant-7 tickets before the
> L1 attempt was spent. It does not work, for three independent reasons:
>
> 1. **There is no text.** `short_description` holds **8 distinct values** across
>    31,588 cases (max 21 characters), and is 60.55% redundant with `issue_type`
>    (NMI 0.6055). A text-only model scores PR-AUC 0.1819.
> 2. **There is nothing to predict.** `reached_level_3` is an exact function of
>    variant membership — all 1,979 L3 cases are Variant 6 or Variant 7, and
>    29,609 cases (93.7%) contain zero positives.
> 3. **Rules match the model.** A categorical-only model (AUC 0.8408) beats the
>    full pipeline (AUC 0.8400). Gradient boosting buys ~0.004 AUC over a linear
>    model on five one-hot columns.
>
> A real triage signal would need a genuinely free-text field, which this dataset
> does not contain.

The intervention itself — routing hard cases earlier — is still sound in principle.
What changed is the *method*: the leverage is in a transparent lookup rule, not a
model. See `ml_artifacts/INTERPRETATION.md`.

---

## 7. Caveats — read before using these numbers

| Caveat | Detail |
|---|---|
| **Satisfaction is capped for 4 variants** | Variant 10, 7, 4 and 2 have max score 3; the other 9 reach 5. Their satisfaction values are censored, so **cross-variant satisfaction comparisons are invalid**. Variant 7's "1.90 vs 3.26" gap is real in direction but the magnitude is not trustworthy. |
| **`resolver` NULL is structural** | 96,496 rows (39.8%) have no resolver — 100% of `Ticket created`, `Ticket closed`, `Customer feedback received`, 0% of any WIP/assignment event. These are system transitions, not missing data. Do not fill them. |
| **1 row has a NULL event name** | `INC0305`, 2023-06-14 09:37. Excluded from transition metrics; it has no usable label. |
| **Variant 7 is structurally deterministic** | 100% Bug, 100% L3, a single fixed 15-event sequence with no deviation across all 1,261 cases. Determinism is in the **sequence, not the timing** — cycle time still varies (sd 13.49 h, range 7.03–56.32). Real processes can be tightly standardised, but this level of uniformity plus Variant 6's identical property should be confirmed with the data owner. See §7a. |
| **Cycle time includes closed time** | Measured first event → last event, so it includes the `Customer feedback received → Ticket closed` wait (~1.06 h) that may be administrative rather than active work. |
| **`priority` semantics unverified** | The inversion in §4 is robust but its *cause* is unknown from event logs alone. |

---

## 7a. Is this data real? Unresolved — and it gates every recommendation

*Added after review of the ML layer. This is the most important open question in
the project and no amount of further analysis can close it.*

Three structural properties are hard to explain as ordinary operational behaviour:

| Observation | Value | Why it matters |
|---|---|---|
| Event-count spread within variant | **0 for all 13 variants** | Every case of a variant is exactly the same length. Real cases get cut short, reworked, or abandoned. |
| Distinct event sequences per variant | **1 for 12 of 13** (Variant 10 has 2) | A variant *is* a sequence, so this is partly definitional — but total uniformity is still unusual. |
| `priority` as a global time multiplier | intake ×4.59/×5.71, L1 work ×4.34/×5.13, L2 work ×4.50/×5.53 (Medium/Low vs High) | Real triage shifts time between queueing and active work. Multiplying every state by nearly the same factor is what a generator parameterised on `priority` would do. |

Measured in [`sql/05_provenance.sql`](sql/05_provenance.sql); exports in `data/1_*`
through `data/6_verdict.csv`.

**This is not proof of generation.** A tightly standardised, heavily templated
service desk could also produce it. The two cannot be distinguished from the log.

**What it gates:**

- Every operational recommendation in §6. If the data is generated, §6 describes
  the generator's parameters, not a real service desk.
- The priority inversion in §4 is a *real pattern in the data* either way, but its
  operational meaning depends entirely on the answer.
- Nothing in the pipeline or the findings should be presented externally as
  describing a real process until the data owner confirms this.

**Action required from the data owner, not from analysis:** one question — is
`Incident_Management_CSV.csv` real operational data or synthetic?

---

## 8. Corrections to the previous analysis

Documented for provenance; the old files are in `archive/`.

Corrections 1–4 are from the first rebuild. Corrections 5–7 are from the ML
investigation and adversarial review (2026-10-01).

**5. Variant 6 was missing entirely.** The original analysis examined variants for
slowness and identified only Variant 7. **Variant 6 is also 100% L3** — 718 cases
at 18.74 h. Because its mean cycle time is unremarkable beside Variant 7's 26.64 h,
it never registered as an outlier. Together the two variants account for **all
1,979** L3 cases; the other 29,609 incidents contain zero. See §5a.

**6. "Zero variance" for Variant 7 was wrong.** The determinism is in the *event
sequence*, not in timing. Cycle time still varies widely: sd **13.49 h**, range
7.03–56.32 h — more spread than the dataset average. Corrected in §7.

**7. The proposed text classifier was never viable.** §6 previously recommended an
ML classifier over `short_description`. It has since been built and rejected:
the field holds 8 distinct values across 31,588 cases. Withdrawn in §6 "Longer
term". Full account in [`ML_FINDINGS.md`](ML_FINDINGS.md).

**Additionally:** the Strategic recommendation in §6 is now explicitly marked as
**unvalidated by experiment** (§6 header). It is a descriptive hypothesis about
where time accumulates, not a proven causal lever.

---

**Earlier corrections:**

**1. Truncated load.** `to_sql(chunksize=5000, method="multi")` committed
55,000 of 242,901 rows and raised no error. Every published KPI was computed on
22.6% of the data.

| Metric | Published | Correct |
|---|---:|---:|
| Avg cycle time | 52,462.74 s (14.57 h) | **54,114.39 s (15.03 h)** |
| Avg step duration | 7,874.33 s (2.18 h) | **8,125.20 s (2.26 h)** |
| Avg total steps | 8.48 | **7.69** |
| Max cycle time | 202,740 s | 202,740 s ✓ |

**2. Backwards bottleneck attribution.** `LAG()` labelled each wait with the
*following* event, so "Ticket escalated to level 2 support — 4.36 h" was actually
time spent in `WIP - level 1 support`. This produced a materially wrong
recommendation: "reduce time spent in escalation events by 30%" targets the
hand-offs (~1 h each) rather than the L1 work that precedes them (~4.2 h).

**3. Inflated resolver counts.** Filling NULL `resolver` with the literal
`"Unknown"` added one distinct resolver per affected case — Variant 7 read
**7.53** instead of **6.53**.

**4. Wrong scale.** "≈1000+ Cases" understated the true 31,588 by ~30×. The
table was also named `incident_events` in the README but is `incident_data`.