# ML Investigation: Findings and Negative Result

**Project:** Incident Management Process Optimization (Project #2)
**Component:** `ml_triage.py` — intake-triage classifier, built, executed, and rejected on the evidence
**Underlying data:** `Incident_Management_CSV.csv` → PostgreSQL `Incident_Management.incident_data`
**Volume:** 242,901 events · 31,588 incidents · 13 process variants · 2023-01-01 → 2024-01-02
**Artifacts:** `ml_artifacts/` — `metrics.json`, `run_log.txt`, `INTERPRETATION.md`, `REVIEW.md`, figures, fitted models

> **Headline:** the intake-triage classifier proposed in `RESULTS_AND_SUGGESTIONS.md` §6 cannot be
> built from this dataset. The hypothesis was falsified, not weakened. In the process of falsifying
> it I found that **`reached_level_3` is an exact deterministic function of process-mining variant
> membership** — which makes it a lookup, not a prediction problem, and which the original analysis
> missed entirely because it only ever looked at Variant 7.

---

## 1. What I attempted, and why

`RESULTS_AND_SUGGESTIONS.md` §6 ("Longer term") proposed a classifier over the free-text
`short_description` field:

> a classifier predicting *at intake* whether a ticket will become a Variant 7 / L3 Bug would let
> routing happen before the ~4 h L1 attempt is spent, which is where the leverage is.

The reasoning was sound in principle. The process analysis established that escalation is the
dominant driver of cycle time (escalated 17.40 h vs non-escalated 11.53 h, +51%, 59.65% escalate)
and that Bugs behave unlike every other issue type — 43.8% escalate (lowest of all seven types) but
21.9% reach L3 and take 21.59 h (longest of all seven). If L3 escalation were predictable at intake,
routing those tickets earlier would attack the 4.2 h L1 attempt that precedes every escalation. That
is a real lever with a real cost, and if the prediction were possible it would be worth building.

So I built it. Three targets, two model families, chronological and random splits, and a set of
ablations designed to answer the question I actually cared about: *is there any signal here that
survives contact with the structure of the data?*

The answer is no, for reasons that are specific, measurable, and — for the `short_description`
premise — total.

---

## 2. Method

Full detail in `ml_triage.py` (module docstring carries the leakage contract) and
`ml_artifacts/metrics.json`. Summary:

**Grain.** One row per incident, 31,588 rows, built from each case's **first event only**. Verified
at runtime: all 31,588 cases begin with `Ticket created`, so the intake frame is complete with no
case dropped and no post-hoc rows included.

**Splits.** Chronological 70/30 (train 22,112 / test 9,476, test window 2023-09-12 → 2023-12-31) as
the primary, plus a random 70/30 split as a drift control. The two differ by **+0.0056 AUC** on the
primary target (chronological 0.8438, random 0.8494), so there is no meaningful temporal drift in
this window.

**Models.** `LogisticRegression` (class-balanced, one-hot categoricals + TF-IDF char n-grams) and
`HistGradientBoostingClassifier`. sklearn 1.9.1, Python 3.11.6, pandas 3.0.3.

**Leakage controls — two exclusions, both deliberate and both reported as ablations rather than
buried:**

- `customer_satisfaction` **excluded**. It is non-null on all 31,588 cases *including every
  `Ticket created` row* — a customer cannot rate handling that has not happened. Its presence on the
  creation row is a denormalisation artefact of a post-closure survey. Including it lifts PR-AUC from
  **0.4029 to 0.4934** (+22%). I took the lower number. That delta is the honest measure of how much
  a careless pipeline would have flattered itself here.
- `variant` **excluded from the production feature set**, because variant is assigned by process
  mining over the *completed* log. It is retained only as a deliberate oracle ablation (§3).

Everything else excluded (`event_count`, `unique_resolvers`, `cycle_time_hours`, `resolver`,
post-first `event`, timestamps) is excluded on the same principle: not known at intake.

**Base rates reported before any metric**, because at these prevalences a bare accuracy is
meaningless:

| Target | Positives | Base rate | Trivial always-negative accuracy |
|---|---:|---:|---:|
| `reached_level_3` | 1,979 | 6.27% | 93.73% |
| `escalated` | 18,841 | 59.65% | 59.65% |
| `slow_24h` (>24 h) | 5,224 | 16.54% | 83.46% |

---

## 3. Results, and the ablations that killed the hypothesis

### 3.1 Primary target: `reached_level_3`

Chronological split, test base rate 0.0605:

| Model | ROC-AUC | PR-AUC | Lift | F1 @ 0.5 |
|---|---:|---:|---:|---:|
| Logistic regression | 0.8400 | 0.4029 | 6.66× | 0.4577 |
| HistGradientBoosting | 0.8438 | 0.3769 | 6.23× | 0.5098 |
| Random guess | 0.4989 | 0.0604 | 1.00× | 0.0600 |

Read cold, AUC 0.84 against a 6% base rate looks like a strong model. **It is not a model of
escalation foresight.** The ablation table explains why:

| Ablation | ROC-AUC | PR-AUC | What it means |
|---|---:|---:|---|
| **+ `variant`** (oracle) | **1.0000** | **1.0000** | The target *is* variant membership |
| + `customer_satisfaction` (leakage) | 0.8416 | 0.4934 | Not usable at intake — excluded |
| Text-only (`short_description`) | 0.7774 | **0.1819** | 2.9× lift; the actual text signal |
| **Categoricals-only** (no text) | **0.8408** | 0.3928 | **A non-ML rule does this well** |
| Temporal-only | 0.5280 | 0.0587 | Time-of-day carries nothing |
| **Excluding Variant 7** | **0.6095** | **0.0358** | What is left after the real structure |

Two of these rows are decisive.

**The oracle ablation proves circularity.** Adding `variant` gives a perfect score. A label that can
be read off a feature with certainty was defined by clustering the thing being predicted.

**The categorical-only model beat the full pipeline.** 0.8408 versus 0.8400 for the full model with
HistGB at 0.8438 — i.e. five one-hot columns through a linear model matched or beat gradient
boosting over the whole feature set, for a difference of roughly 0.004 AUC. Simple threshold rules
on those same categoricals reproduce the model's operating characteristics. There was no gradient
boosting to be had here.

### 3.2 `short_description` is not text

The field the whole proposal rested on has **8 distinct values across 31,588 cases** (0.0253%
distinct, longest 21 characters, mean 16.09):

| Value | Cases |
|---|---:|
| New feature request | 7,660 |
| Application crash | 5,804 |
| Data loss issue | 5,035 |
| Server outage | 4,295 |
| UI glitch | 2,848 |
| Printer not working | 2,288 |
| Unable to login | 2,198 |
| Password reset needed | 1,460 |

A text-only model over these 8 strings reaches PR-AUC 0.1819 against a 0.0604 baseline. It is
boilerplate, and it is largely a re-encoding of `issue_type`: the normalised mutual information
between the two fields is **0.6055**, and each description maps onto at most three issue types
(`New feature request` → Feature Request / Service Request; `Server outage` → Incident / Maintenance
/ Technical Issue; and so on). All 18,915 Variant 7 event rows carry the single string
`Application crash`.

**The proposed text-based triage classifier has no input.** Not "weak input" — there are eight
strings. The `short_description` proposal in `RESULTS_AND_SUGGESTIONS.md` §6 should be struck.

### 3.3 `slow_24h`: the model is redundant with a SQL predicate

The best-looking number in the whole run was `slow_24h` at **ROC-AUC 0.9326**. It is also the least
useful. The operating characteristics of that model are reproduced, with no model at all, by:

```sql
WHERE priority = 'Low'
```

| | Precision | Recall |
|---|---:|---:|
| `priority='Low'` rule | **0.5503** | **0.9847** |
| Logistic regression | 0.5775 @ best-F1 | 0.9450 @ best-F1 |

The rule's counts: 5,144 of 9,348 Low-priority cases breach 24 h; 5,144 of 5,224 total breaches are
Low (the other 80 are Medium; **zero** are High). Two honest qualifications, both from
`ml_artifacts/REVIEW.md`:

- The model *does* win at its own chosen operating point — best-F1 0.7172 versus the rule's 0.7060,
  a 1.1-point margin.
- At **matched recall** the ordering reverses: at the rule's own recall (~0.979) the model scores
  precision 0.4665 against the rule's 0.5494, an 8.3-point gap in the rule's favour.

So the defensible statement is not "the model ties the rule" and not "the model beats the rule". It
is: **a one-predicate SQL rule and a gradient-boosted model are the same finding, the rule is
simpler, and which one wins depends on where you set the threshold.** And the "independent
rediscovery" framing has to go: `priority` was a model input, so the model was partly restating a
partition it was handed.

### 3.4 `escalated` is a weak target, not a solved one

AUC 0.6400 (LogReg) / 0.6481 (HistGB) against a 59.65% base rate; best-F1 recall 0.9426, which
means thresholded action flags 87–89% of all tickets. There is a weak-but-real signal (PR-AUC 0.7365
versus a 0.5948 baseline, lift 1.24) — it is not literally nothing. But at this prevalence and this
recall, escalation does not support a triage rule. Whether escalating costs anything scarce is a
business question the log does not answer.

One secondary note: `desc_length` has permutation importance 0.001 and is a deterministic function
of `short_description` (8 distinct values, fixed strings), so it is a redundant feature that makes
the feature block look richer than it is. Four of the six temporal features are exactly zero.

---

## 4. The finding that matters: `reached_level_3` is a lookup, not a prediction

This was not in any project document before now. I found it while checking whether the L3 target had
any variance left once the obvious variant was removed, and I verified it twice — once through the
ML artifacts, once directly against the database with an independent query.

Per-variant L3 rates, computed from `v_case_metrics` (242,901 events / 31,588 cases, re-confirmed):

| Variant | Cases | Reach L3 | L3 rate | Mean cycle h |
|---|---:|---:|---:|---:|
| **Variant 7** | 1,261 | 1,261 | **100.0%** | 26.64 |
| **Variant 6** | **718** | **718** | **100.0%** | **18.74** |
| Variant 3 | 11,901 | 0 | 0.0% | 16.07 |
| Variant 1 | 9,896 | 0 | 0.0% | 11.12 |
| Variant 4 | 2,234 | 0 | 0.0% | 15.36 |
| Variant 5 | 1,188 | 0 | 0.0% | 23.33 |
| Variant 8 | 954 | 0 | 0.0% | 21.92 |
| Variant 2 | 934 | 0 | 0.0% | 5.81 |
| Variant 11 | 626 | 0 | 0.0% | 11.07 |
| Variant 9 | 625 | 0 | 0.0% | 22.24 |
| Variant 10 | 606 | 0 | 0.0% | 11.17 |
| Variant 12 | 337 | 0 | 0.0% | 10.83 |
| Variant 13 | 308 | 0 | 0.0% | 22.26 |

Three queries, and the structure is absolute:

```
L3 cases outside {Variant 6, Variant 7}          = 0
Excluding Variant 7          : 30,327 cases,   718 positives  (all Variant 6)
Excluding Variants 6 and 7   : 29,609 cases,     0 positives
```

1,979 total L3 cases = 1,261 (V7) + 718 (V6). All 1,979. **No variant has a mixed L3 outcome.**

### 4.1 Variant 6 was missed entirely

`RESULTS_AND_SUGGESTIONS.md` §5 documents Variant 7 as "a distinct failure mode" and §6
recommendation 6 says to treat it as a separate process. It does not mention Variant 6, which has
the same 100%-L3 structure one tier down:

| | Variant 7 | **Variant 6** | All others |
|---|---:|---:|---:|
| Incidents | 1,261 | **718** | 29,609 |
| Reaches L3 | 100% | **100%** | **0.0%** |
| Mean cycle h | 26.64 | **18.74** | 14.45 |
| Mean events | 15.00 | **10.00** | 7.32 |
| Mean resolvers | 6.53 | 5.26 | — |
| Issue type | 100% Bug | all 7 types | mixed |
| `short_description` | 1 value | all 8 values | mixed |
| Mean satisfaction | 1.90 (censored at 3) | 3.47 (**not censored**) | 3.49 |

Variant 6 is *not* a Bug loop. It spans every issue type and every description. Its signature is
purely structural: a fixed nine-transition path (`Ticket created → assigned L1 → WIP L1 → escalate
to L2 → WIP L2 → escalate to L3 → WIP L3 → solved by L3 → feedback → closed`), 718/718 occurrences
of each transition, and a mandatory single pass through L3 with **no** rework loop — unlike
Variant 7, which bounces back to L2 for a second pass.

The distinction matters operationally. Variant 7 needs rework-loop remediation; Variant 6 is a clean
one-pass L3 path that simply always terminates in L3. Treating them as one bucket would misdirect the
fix.

### 4.2 What this does to the ML result

**`reached_level_3` is not a stochastic outcome. It is an exact function of process-mining variant
membership.** Three consequences:

1. **AUC 0.84 measures cluster recovery, not foresight.** The task is "guess which of two fixed
   trace archetypes this ticket will follow", and Variant 7's fingerprint is blatant — 100% Bug, one
   description string. A model that learns "`issue_type=Bug` and crash text → Variant 7" scores
   exactly what was reported. That is real skill at recovering a label from a generator's
   fingerprint. It is not skill at predicting escalation.
2. **The headline number must never be published bare.** Wherever AUC 0.84 appears, the variant-6
   fact and the 29,609-cases-zero-positives fact travel with it.
3. **The "excluding Variant 7" ablation is the headline caveat, not a footnote.** AUC 0.6095 is the
   most informative row in the table, and its residual positives are exactly the Variant 6 cases
   still in the test set (212 of 9,115 test rows, base rate 0.0233). The model was never predicting
   escalation — even inside that ablation it was still pattern-matching a variant.

### 4.3 L3 is fully enumerable — a better answer than "unpredictable"

The practical consequence is stronger than the negative result. L3 escalation is not an
unpredictable risk requiring a model. It is **completely enumerable by variant membership, today,
with SQL**. Handle Variant 6 the way §6 already says to handle Variant 7 — as a separate process
with its own workflow and SLA — and the L3 population becomes a known, finite, 1,979-case list rather
than a 6% base rate to be guarded against.

The `Bug + Low → pre-route` rule tested during this work is **not** a usable substitute
(precision 0.2273, recall 0.2350) and should not be presented as one.

---

## 5. What this means for the process conclusions

Being precise about which conclusions this layer touched, because most of them it did not.

**Falsified — one documented proposal.** The `short_description` intake classifier in
`RESULTS_AND_SUGGESTIONS.md` §6 is dead. Eight distinct strings is not a modelling problem. That
proposal should be struck rather than softened.

**Materially changed — the L3 picture.** Variant 6 enters the analysis as a second 100%-L3
population. `RESULTS_AND_SUGGESTIONS.md` §5, §6 recommendation 6, and §7 need it added. This is the
ML layer's one genuinely productive output.

**Untouched — the headline strategic recommendation.** The §6 strategic intervention (shorter L1
attempts, faster first assignment) rests entirely on the process analysis. The ML layer did not test
it and did not refute it. **It remains unvalidated.** If anything the temporal-only ablation (AUC
0.5280) and the priority dwell-multiplier result (§6.1 below) *weaken* the assumption underneath it:
the intake queue may not be congestion-driven in the way a WIP-limit or auto-assign fix assumes.

**Untouched — the 72.8% time concentration.** `WIP - level 1 support` 28.8%, `Ticket created`
25.9%, `WIP - level 2 support` 18.2%. Verified independently; no ML finding bears on it.

**Untouched, and still unexplained — the priority inversion.** Low 25.76 h / Medium 12.28 h / High
6.23 h, holding within every issue type and every variant, satisfaction flat at 3.25–3.26. The ML
layer reproduced this and added nothing. The cause is still unknown, and §4 of `RESULTS_AND_SUGGESTIONS.md`
is right that it cannot be resolved from event logs alone.

### 5.1 A note on the sequencing, recorded honestly

The decisive question — why is priority inverted, and is it a behavioural signal or a labelling
artefact? — was already documented as open in `RESULTS_AND_SUGGESTIONS.md` §4. I then built an ML
layer whose strongest result was re-deriving that same inversion from a dataset in which `priority`
was an input feature. That is effort spent confirming a known association.

What *would* have been worth building first is the query in §4 above — one piece of SQL, and it
changed the project's conclusions. Recorded here because the sequencing was wrong, and because the
artefact of getting it wrong is more useful than a claim that it wasn't.

### 5.2 A measurement that bears on the inversion

Dwelling time by priority, from `v_transition_metrics`:

| Priority | Intake wait (h) | L1 work (h) | Intake ×High | Work ×High |
|---|---:|---:|---:|---:|
| High | 1.681 | 2.418 | 1.00 | 1.00 |
| Medium | 3.162 | 4.553 | **1.881** | **1.883** |
| Low | 6.637 | 9.255 | **3.949** | **3.828** |

(`L1 work` = per-case total dwell across `WIP - level 1 support` and
`Ticket assigned to level 1 support`; intake = `Ticket created`.)

If priority were a triage *decision* — someone deprioritising a ticket and leaving it queued —
intake wait would rise while work time stayed flat. **Both rise by the same factor.** For Medium the
two multipliers agree to 0.1%. For Low they agree to 3.1% (3.949 vs 3.828) — close, but not the
within-1% figure quoted in `ml_artifacts/REVIEW.md`, which appears to use a slightly different
aggregation of L1 work.

This is the signature of `priority` acting as a **time multiplier** rather than a behavioural signal
about queueing. It is a second, independent reason to take the provenance question in §6 seriously
— and it is also why the intake recommendation in §6 deserves scrutiny before anyone builds an
auto-assign rule on it.

---

## 6. Limitations

### 6.1 Is this data real? Unresolved, and everything else is downstream of it

**Whether `Incident_Management_CSV.csv` is real operational data or generated with `priority` and
`variant` as deterministic parameters is not established, and I cannot establish it from the log.**
This is the most important open question in the project, and it gates everything above. The evidence
that keeps it open:

- **Structural determinism is total, not partial.** Every one of the 13 variants has exactly **one**
  distinct event sequence (`string_agg` over events ordered by timestamp — 1 distinct signature for
  12 variants, 2 for Variant 10, where a single case of 606 omits a `WIP - level 1 support` state).
  Event count has zero variance within Variant 6 (10 for all 718) and within Variant 7 (15 for all
  1,261). Per-case gap standard deviations within Variant 7 are 0.19–3.02 h.
- **`priority` multiplies dwell times almost identically** for intake and for work (§5.2).
- **Two variants are 100% L3 and eleven are 0% L3.** No overlap anywhere.

None of that is what a support desk looks like. It is consistent with a generator parameterised on
`priority` and `variant`. **It is not proof**, and I am not claiming it as a conclusion — real
processes can be surprisingly uniform, and the provenance question is answerable only by whoever
produced the CSV.

If the data is partly synthetic, the priority inversion is a generator parameter, the `slow_24h`
model is fitting a generator, and the L3 target is a lookup table — which would mean every
operational recommendation in `RESULTS_AND_SUGGESTIONS.md` §6 describes the generator rather than a
process. **Until the data owner answers this, the honest scope of this project is its data
engineering, its method, and the two findings in §4 — not its operational recommendations.**

### 6.2 "At intake" is not verifiable from this log

Every candidate intake feature (`priority`, `issue_type`, `report_channel`, `reporter`,
`short_description`, `customer_satisfaction`, `variant`) has **zero intra-case variation** across all
31,588 cases. Staticness is evidence that a value is *written once*. It is **not** evidence that it
is written at ticket creation. A column backfilled after closure is equally static. `priority` sits
in exactly the same epistemic position as `issue_type`, and the distinction only becomes load-bearing
for `priority` — because it is the feature carrying the `slow_24h` result. If `priority` is
backfilled, that model is reading a post-outcome field. This is the largest unforced weakness in the
ML work and it cannot be closed with the data available.

### 6.3 Carried forward from the process analysis

| Limitation | Detail |
|---|---|
| Satisfaction censored for 4 variants | Variants 2, 4, 7, 10 max out at 3 vs 5 elsewhere (5,035 incidents). Cross-variant satisfaction comparison is invalid. Variant 6 is **not** censored (max 5, mean 3.47). |
| `resolver` NULL on 96,496 rows (39.8%) | Structural — system transitions have no owner. Not missing data, and deliberately not filled with a placeholder. |
| 1 NULL event name | `INC0305`, 2023-06-14 09:37. Excluded from transition metrics; a test asserts exactly 1. |
| Cycle time includes closure wait | First event → last event, so it includes the ~1.06 h `Customer feedback received → Ticket closed` gap, which may be administrative. |
| "Zero variance" is wrong wording for Variant 7 | Its *event sequence* is deterministic; its cycle-time standard deviation is **13.49 h** on a mean of 26.64 (CV ≈ 0.51) — more duration variance than the dataset overall (Low: 8.05 h on 25.76). Structural uniformity is not temporal uniformity. |
| Priority-inversion cause unknown | Robust in the data, unexplained by it. |

### 6.4 Fitted model files

`ml_artifacts/model_logreg_l3.pkl` and `model_histgb_l3.pkl` are fitted on a label that is an exact
function of variant membership. **They are not deployable and must not be described as such.** They
are kept only as reproduction artifacts for this investigation. Anyone loading them expecting a
triage model will get a variant-membership lookup with a confidence score attached.

---

## 7. Provenance — errors found and corrected in this project

Self-correction is the strongest thing in this repository, so it is recorded rather than smoothed
over. Full detail in `RESULTS_AND_SUGGESTIONS.md` ("Corrections to the previous analysis") and
`ml_artifacts/REVIEW.md`.

1. **Truncated load, undetected for two days.** A `to_sql(chunksize=5000, method="multi")` load
   committed **55,000 of 242,901 rows** and raised no error. Every published KPI was computed on
   **22.6%** of the data. The pipeline was rebuilt around a single-transaction `COPY` with load-parity
   assertions; `test_db_row_count_matches_source` and `test_no_case_is_partially_loaded` exist
   specifically to make that failure loud, and both were confirmed to fail against a deliberately
   truncated table.
2. **Backwards bottleneck attribution.** An earlier `LAG()`-based query labelled each wait with the
   *following* event, so "Ticket escalated to level 2 support — 4.36 h" was really time in
   `WIP - level 1 support`. That produced a materially wrong recommendation: reduce escalation
   events, when escalation events cost ~1 h and the L1 work preceding them costs ~4.2 h. Fixed by
   forward-looking attribution (`next_timestamp − timestamp`) in both views.
3. **Inflated resolver counts.** Filling NULL `resolver` with the literal `"Unknown"` added one
   distinct resolver per affected case — Variant 7 read **7.53** instead of **6.53**. NULLs are now
   left alone.
4. **Wrong scale and wrong table name.** "≈1000+ cases" understated 31,588 by ~30×; the table was
   documented as `incident_events` when it is `incident_data`.
5. **An over-strong comparison, corrected in this layer.** An earlier write-up of the `slow_24h` work
   described the precision gap between the model and the `priority='Low'` rule as "within noise". It
   is not noise — at matched recall the rule leads by 8.3 precision points, the opposite sign. Now
   reported as a matched-operating-point comparison (§3.3).
6. **Variant 6 missing from the project.** 718 cases, 100% L3, absent from every document until now.
   Added in §4.

---

## 8. Summary

| Question | Answer |
|---|---|
| Can a `short_description` intake classifier be built? | **No.** 8 distinct strings, max 21 chars, NMI 0.6055 with `issue_type`. Text-only PR-AUC 0.1819. |
| Can `reached_level_3` be predicted at intake? | **It does not need to be.** It is an exact function of variant membership: V7 (1,261) ∪ V6 (718) = 1,979 of 1,979. Excluding both leaves 29,609 cases and zero positives. |
| Was Variant 7 the only 100%-L3 variant? | **No.** Variant 6: 718 cases, 100% L3, 18.74 h mean, single-pass L3 path with no rework loop. Previously undocumented. |
| Does the `slow_24h` model add anything? | **No.** `WHERE priority='Low'` gives P 0.5503 / R 0.9847. The model wins best-F1 by 1.1 points; the rule wins at matched recall by 8.3. And `priority` was a model input, so the rediscovery is partly circular. |
| Did gradient boosting earn its place? | **No.** Categorical-only LogReg (0.8408) matched the full pipeline (0.8400). |
| Was the methodology sound? | Leakage actively controlled and documented (`customer_satisfaction` excluded at a cost of 0.09 PR-AUC; `variant` quarantined as an oracle). No temporal drift (Δ 0.0056 AUC). Base rates reported before metrics. |
| What is still unknown? | Whether the data is real or generated — and therefore whether any operational recommendation describes a process or a generator. |

**The value this layer delivered:** a clean falsification of a documented proposal, a
leakage-controlled methodology that makes the negative conclusive rather than speculative, a
correction to the project's own comparison claim, and the discovery that L3 escalation is
enumerable rather than predictable.

**It did not deliver a deployable model, and it was never going to.** Nothing in
`ml_artifacts/` should be deployed.