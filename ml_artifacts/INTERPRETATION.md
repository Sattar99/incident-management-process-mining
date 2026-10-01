# ML Triage Layer — Analytical Interpretation

**Author:** HERCULES (Analytical Intelligence)
**Date:** 2026-10-01
**Subject:** Business interpretation of `ml_artifacts/metrics.json` + `run_log.txt` (run 2026-10-01T02:51:09)
**Scope:** Interpretation only. No model code written, no files modified, no repository changes.

> **Headline conclusion.** The ML layer produced a clean negative result. The project's
> proposed `short_description`-based triage classifier **cannot be built**, because the
> field contains 8 boilerplate strings, not free text. The negative result is the finding.
> Additionally, the one target that *did* score strongly (`slow_24h`) is shown here to be
> **statistically indistinguishable from a two-line SQL query on `priority`** — so it is
> redundant with an already-documented finding, not new decision support.

---

## 0. Verification of Artemis's reported numbers

All figures in the brief were checked against `metrics.json` and `run_log.txt`. **No
numeric discrepancies found.** Values confirmed: L3 base rate 1,979/31,588 = 6.265%; LogReg
0.8400/0.4029; HistGB 0.8438/0.3769, Brier 0.0405; stratified-random AUC 0.4989; split
delta +0.0056; escalated 0.6400/0.7019 and 0.6481/0.7365; slow_24h 0.9326/0.6235 and
0.9304/0.6395, operating point P 0.578 / R 0.945 / 27.6% flagged; regressor MAE 3.59 h,
R² 0.683, Spearman 0.815, baseline MAE 7.04 h; all six ablation rows; Variant 7
1,261 cases / 63.72% of L3 positives; categorical-only 0.8408 > full 0.8400.

Three qualifications the brief's framing slightly obscures:

1. **`short_description` is not merely "boilerplate" — it is fully redundant with
   `issue_type`.** NMI = 0.6055, and the cross-tab shows near-deterministic mapping
   ("Unable to login" → 100% Incident, 2,198; "Password reset needed" → 100% Service
   Request, 1,460; "New feature request" → 100% Feature Request/Service Request). It is a
   *second label field*, not a description field.
2. **The leaky-feature claim is stronger than stated.** The `customer_satisfaction` gain
   (+22% PR-AUC) is not merely a metric artifact — the field is *present on every row*
   (`present_on_every_row: true`, 0 nulls at intake) while being a post-closure survey
   score. It is a denormalisation artifact in the ETL, not a modelling choice.
3. **`slow_24h` operating point quoted in the brief is the LogReg best-F1 threshold.**
   The HistGB best-F1 point flags 29.5% at P 0.555/R 0.968 — materially different
   operating characteristics from the same nominal AUC. Any "27.6% flagged" figure is
   model-and-threshold-specific, not a property of the problem.

Independent DB check (read-only, PostgreSQL `Incident_Management`, 31,588 cases):
`slow>24h` = 5,224 ✓; `priority=Low` = 9,348 ✓; `slow AND Low` = 5,144; `slow AND High`
= **0**; `slow AND Medium` = 80; `variant='Variant 7'` = 1,261 ✓. `priority` never
changes within a case (0 cases with intra-case priority variation), so it is genuinely an
intake-time attribute and a rule on it is legitimate.

---

## 1. Per-target business interpretation

### 1.1 `reached_level_3` — OBSERVED: not actionable at intake

At its best-F1 operating point the model flags **7.9% of tickets (≈2,500/yr)** at
**precision 0.504, recall 0.660**. Read operationally: to catch two-thirds of the 1,979
annual L3 escalations an operations team must triage ~2,500 tickets, and **half of the
tickets they look at are false alarms**.

**The decision that would change:** "route this ticket straight to L2, skipping the L1
attempt." For this to pay off, the skipped L1 attempt must cost more than the routing
overhead plus the reviewer time on 1,250 false positives. The established finding is that
an L1 attempt costs ~4.2 h of elapsed time. Whether that 4.2 h is *saved* by pre-routing
or merely *relocated* is **UNKNOWN** — the log contains no counterfactual.

**The decisive objection is not the precision number — it is the ablation.** Removing
Variant 7 collapses the model (AUC 0.844 → 0.610, PR-AUC 0.377 → 0.036). See §2.

### 1.2 `escalated` — OBSERVED: not a prediction problem, a definition problem

AUC 0.648 against a 59.65% base rate. At best-F1 the models flag **87–89% of all
tickets**. A classifier that says "escalated" about nearly nine tickets in ten is not
triaging; it is restating the base rate.

INFERRED: escalation at 59.65% is close to the process's default behaviour, so "predict
escalation" has almost no decision content. There is no scarce resource being allocated by
this prediction. **No operations team should be asked to act on this target.** It should be
dropped, not improved.

### 1.3 `slow_24h` — OBSERVED: strong metric, and see §3 for why it is still not useful

AUC 0.9326, PR-AUC 0.6235, at the LogReg best-F1 point flags **27.6% of tickets
(≈8,725/yr)** at **P 0.578 / R 0.945**. This is the only target with a plausible
operational reading.

---

## 2. Why the L3 signal collapses without Variant 7 — the 63.7% concentration

**OBSERVED.** Variant 7 is 1,261 cases (4.0%), 100% Bug, 100% L3. It supplies 1,261 of
1,979 L3 positives = **63.72%**. Excluding it: base rate falls 6.27% → 2.33%, AUC
0.844 → 0.610, PR-AUC 0.377 → 0.036.

**OBSERVED (independent DB check).** Outside Variant 7: 718 of 30,327 cases reach L3
(2.37%). Of all 1,979 L3 positives, 1,490 are Bug. Excluding Variant 7, only **229 of
5,543 non-Variant-7 Bugs** reach L3 (4.1%), and 489 non-Bugs reach L3 in total.

**INFERRED — the central interpretation.** The model's apparent skill is not "learning to
recognise escalation risk." It is learning a single fact: *`issue_type = Bug` co-occurs
with Variant 7*. The coefficients confirm it — `issue_type=Bug` (+1.47) is the largest
positive weight, and `Performance Issue` (−1.52) is the largest negative, because
Performance Issues dominate the never-escalate-to-L3 population.

**INFERRED — was "predict L3 at intake" ever well-posed? No, for three compounding reasons.**

1. **Label-definition circularity.** Variant 7 is *defined* by process-mining as the trace
   shape that includes "Level 2 escalates to level 3 support" — twice. So `reached_level_3`
   is partly a restatement of variant membership, and variant membership is determined by
   events that have not happened yet at intake. The oracle ablation (AUC 1.0000 with
   `variant`) is not evidence of predictability; it is evidence of **circularity**, and it
   proves the metric was never measuring foresight.
2. **The residual signal is too small to matter.** Outside Variant 7, 718 annual cases
   spread across 30,327 tickets. Even a perfect classifier there changes ~718 hand-offs a
   year — and Variant 7 already supplies 1,261 of them by a rule (`issue_type = Bug`
   captures 75.3% of all L3 positives, per DB check).
3. **Uniformity is a data-integrity flag, not a business pattern.** RESULTS §7 already
   notes zero variance across 1,261 cases and suspects synthetic generation. A population
   that is 100% uniform on 11 attributes should not be used to justify an ML investment.
   **Any conclusion about Variant 7 is conditional on the data being real.**

**INFERRED.** The proposed use case ("route before the ~4 h L1 attempt is spent") was
never viable, because the population it targets is 4% of volume with a deterministic
label already visible in `issue_type` at intake. The correct response to "63.7% of
positives sit in 4% of cases" is **not** to build a classifier for that 4%; it is to
pull Variant 7 out of the population and manage it as a separate process — which
RESULTS §6 tactical recommendation 6 already says.

---

## 3. Business value of `slow_24h` — the operational arithmetic

### 3.1 The volume math

At 31,588 incidents/yr, 5,224 breaches, flagging 27.6% (8,725 tickets) at P 0.578 /
R 0.945:

| Quantity | Value |
|---|---|
| Tickets flagged for review | **8,725/yr** (~168/week) |
| True breaches caught | **~4,936/yr** (94.5% of 5,224) |
| False alarms | **~3,789/yr** (~73/week) |
| Breaches missed | **~288/yr** (~5.5/week) |

**The reviewer cost is the whole story.** To prevent ~288 escapes per year the team must
inspect 8,725 tickets — a **30:1 review-to-catch ratio**. Unless reviewing a flagged
ticket costs seconds (a dashboard glance, not a triage action), this is a net loss of
attention. Even at a generous 60 seconds of review per ticket that is ~146 reviewer-hours
per year consumed, to catch 288 breaches.

### 3.2 Is it just re-learning the priority inversion? **Yes — decisively.**

I tested this directly against the database rather than inferring it.

**OBSERVED (DB, full population):**

| Priority | n | Breaches >24h | Breach rate |
|---|---:|---:|---:|
| Low | 9,348 | **5,144** | **55.0%** |
| Medium | 15,774 | 80 | 0.5% |
| High | 6,466 | **0** | 0.0% |
| **Total** | 31,588 | 5,224 | 16.5% |

**The rule "flag `priority = Low`" scores: flags 9,348 (29.6%), precision 0.550, recall
0.985.**

Compare:

| | Flags | Precision | Recall |
|---|---:|---:|---:|
| ML model (LogReg best-F1) | 27.6% | 0.578 | 0.945 |
| **SQL rule `priority='Low'`** | **29.6%** | **0.550** | **0.985** |

**INFERRED — the model is redundant, and demonstrably so.** A one-line SQL predicate
matches the 0.93-AUC model on precision (0.550 vs 0.578, within noise) and **beats it on
recall by 4 percentage points**, because *every single breach in this dataset except 80
Medium-priority cases is a Low-priority case*. The model's entire apparent skill is a
noisy re-derivation of `priority`. Its AUC of 0.93 is impressive-looking and buys nothing
a `WHERE priority = 'Low'` clause does not already give.

**Arguing the other side, honestly:** the model is not *zero*-value. It captures 80
Medium-priority breaches the rule misses, and it degrades gracefully if the priority
inversion is *fixed* — a rule built on today's inverted labelling would become actively
misleading the moment priority is corrected, whereas... in truth, so would the model, since
it learned the same inversion. This argument does not survive scrutiny. The honest
counter-argument is weaker and worth stating: **the model is a more legible *symptom*
report than the rule**, and if the inversion is fixed the rule's failure is *visible and
blameable* while the model's would be silent. That favours the rule.

**Conclusion on `slow_24h`: redundant.** Do not ship it. Its value was diagnostic — it
independently rediscovered the priority inversion from intake features alone, which is
genuine corroboration of RESULTS §4 from a completely separate method. That is a real
(if incidental) validation result, and it is worth saying so plainly: **the ML layer
produced one useful cross-check and zero deployable models.**

---

## 4. Evaluation of "ship a rule, not a model"

Artemis recommends a transparent lookup rule instead of the ML layer. **The recommendation
is correct in direction and should be accepted — but it is under-specified in a way that
matters, and the specific rule he proposes ("Bug + Low priority → pre-route") is the wrong
rule for the wrong target.**

### 4.1 Testing the proposed rule

`Bug AND Low` = 2,046 cases, of which 465 reach L3 (**precision 0.227**, recall 0.235).
Compare the ML L3 model: P 0.504 / R 0.660. **The proposed rule is far worse than the
model it replaces** on the modeler's own metric — it flags 2,046 tickets to catch 465
escalations where the model catches 660 of 1,979 from 2,500 flags. Worse, the rule fires
on 465/2,046 = 22.7% precision while the model achieves 50.4%.

**INFERRED: Artemis's example rule should be rejected on its own terms.** He proposes it
for routing (pre-route to L2), not for L3 prediction, so it is not strictly
like-for-like — but as an L3-triage rule it is clearly dominated.

### 4.2 The rule that *is* supported by the evidence

From the DB cross-tab, for the SLA-breach use case:

- **`priority = 'Low'`** → P 0.550, R 0.985, 9,348 flagged. The best single rule found.
- Within Low priority, breach rates by issue type are 44–55% (Feature Request 54.9%,
  Performance Issue 67.3%, Incident 53.4%) — **no issue type meaningfully separates them**,
  so there is no useful second condition to add.

**INFERRED: a one-condition rule is optimal here, not a multi-branch rule.** Adding
conditions to `priority='Low'` cannot raise recall (already 98.5%) and only costs coverage.

### 4.3 Failure modes of the rules approach

Stated plainly, because Artemis's framing understates these:

1. **The rule encodes a bug as a feature.** It says "Low priority → will breach SLA."
   RESULTS §4 already flags the inversion as possibly an assignment artifact. **If the
   inversion is fixed, this rule becomes actively harmful** — it will keep fast-tracking
   exactly the tickets that have become genuinely low-priority. *This is the most serious
   failure mode and Artemis's recommendation does not mention it.*
2. **Coverage ceiling.** 288 breaches/yr escape. If any breach carries contractual
   penalty, that residual matters and needs a human queue, not a bigger model.
3. **Maintenance is not zero.** Not "no maintenance" — different maintenance. A rule's
   correctness depends on the *labelling convention*, which is exactly the thing under
   investigation. Rules need re-auditing whenever `priority` semantics change; models need
   retraining. Rule maintenance is cheaper but not absent.
4. **Auditability cuts both ways.** A rule is trivially auditable — but so is a logistic
   regression on 5 one-hot columns (AUC 0.8408, and its coefficients ARE the rule, printed
   in `run_log.txt` lines 42–53). **The complexity argument does not actually separate the
   two options for the L3 target.**
5. **The rules do not generalise to a second question.** A hand-built rule answers exactly
   one question. If the project later asks "which Bugs need L2 now?", it needs a new rule
   with no shared infrastructure. A fitted pipeline at least offers a reusable harness.
   *This is a real but modest argument for the model.*

### 4.4 Is a rules engine better than a 0.84-AUC model for the L3 decision?

**INFERRED — yes, but not primarily for the reason given, and the margin is small.**

The strongest reason to prefer the rule is **not** simplicity. It is that the decision the
0.84-AUC model supports is *not worth making*: 50.4% precision means half the pre-routed
tickets were unnecessary, and the model's advantage over a good rule is a fraction of an
AUC point (0.8408 vs 0.8400 — categorical-only actually *beats* the full pipeline). When
model and rule are within 0.001 AUC and the rule is inspectable, ship the rule. **But do
not ship it for L3 routing — ship nothing, and manage Variant 7 as the separate process
RESULTS §6 already recommends.** The model should not be replaced by a rule; it should be
superseded by a structural change.

---

## 5. Impact on the project's headline strategic recommendation

> *Cut intake latency by 1 h and L1 attempt time by 20%; this is the highest-ROI
> intervention (~2 h, ~16% off the median).*

**The ML layer leaves this recommendation essentially UNTOUCHED — and weakly corroborates
it.** Explicitly:

- **SUPPORTED (independently).** Temporal-only features are near-useless (AUC 0.528,
  PR-AUC 0.059 — *below* base rate). Created-hour, day-of-week, weekend, month,
  day-of-year all have permutation importance ≤ 0.010, most exactly 0.000. **INFERRED:**
  when does a ticket arrive carries essentially no information about how long it will take.
  Intake-time congestion — the mechanism by which cutting intake latency would help — does
  **not** appear in the data as a driver of duration. This is *consistent with* the intake
  recommendation while being mildly *uncomfortable* for it: if arrival time doesn't predict
  duration, the queue may not be congestion-driven in the way a WIP-limit fix assumes.
- **SUPPORTED.** Cycle-time regression from intake features alone reaches R² 0.683,
  Spearman 0.815, MAE 3.59 h (vs 7.04 h baseline). **INFERRED:** intake features explain
  two-thirds of the variance in cycle time — but see §3, that explanatory power is
  substantially `priority` in disguise.
- **NOT SUPPORTED and NOT REFUTED.** Nothing in the ML layer tests the intervention's
  mechanism. No model can validate a proposed change to dwell time; only a controlled
  before/after can. **The headline recommendation stands or falls on the process
  analysis, which the ML evidence does not disturb.**
- **WEAKENED (indirectly, one clause).** RESULTS §6 "Longer term" proposes a text-based
  classifier. **That clause is falsified and must be struck.** This is the only part of the
  existing document the ML layer damages, and it is a *proposal*, not a finding.

**Net: the ML layer does not touch the strategic recommendation.** It removes the project's
own follow-on proposal, which is the correct outcome for a proposal that could not have
worked.

---

## 6. Recommended next analysis (non-ML) — the deliverable that matters

**Proposed: a priority-assignment provenance audit — reconstructing *when and by what rule*
each incident received its `priority` label, from the event log's own structure.**

**The question it answers:** *Is `priority` assigned at intake as an ex-ante triage
judgement, or derived after the fact from how the incident actually behaved?*

**Why this beats every alternative:**

- RESULTS §4 already names the inversion as "the highest-leverage question in the dataset"
  and states it "cannot be resolved from event logs alone." **This analysis is the
  strongest available attempt at resolving it anyway, and it uses only what the log
  contains.**
- I already ran the first probe of it. **OBSERVED:** `priority` never varies within a case
  (0 of 31,588 cases show any intra-case change) — so the label is stamped once, at or
  before the first event, and never revised even as the incident escalates to L3 or runs
  26 h. That is itself evidence: a genuinely ex-ante urgency judgement would normally be
  revised when L1 fails. **INFERRED: a label never revised across a 26-hour escalation
  smells like a value set at creation from a static field, not a live triage decision.**
  This needs confirming against `created_at` vs first-assignment timing and by issue type.
- **It resolves the single most dangerous live risk.** The recommended SLA-breach rule
  (§4.2) is built on `priority`. If `priority` is a post-hoc artifact, that rule is
  actively harmful — it fast-tracks tickets that were never urgent. **Shipping the rule
  before this audit would be building on an unverified foundation.** The audit must
  precede the rule.
- **It is non-ML, cheap, and decisive either way.** A per-case reconstruction of
  label-assignment timing, cross-tabulated by issue type and variant, is a few SQL queries
  against data already loaded and already verified complete.

**Runner-up (only if the audit is inconclusive):** dwell-time decomposition of the 4.2 h
L1 attempt *conditioned on priority* — to test whether Low-priority tickets wait longer
before work starts (queueing) or work longer per attempt (difficulty). This discriminates
"WIP limit" from "auto-assign" as the fix and directly sharpens the headline recommendation.

**Explicitly not recommended:** more models, more feature engineering, richer text
modelling. There are 8 distinct strings. There is nothing to model.

---

## 7. Evidence ledger

### OBSERVED (directly in data / ML output)
- 8 distinct `short_description` values over 31,588 cases, max 21 chars; NMI with
  `issue_type` = 0.6055; near-deterministic cross-tab.
- L3: LogReg AUC 0.8400 / PR-AUC 0.4029; HistGB 0.8438 / 0.3769; random baseline 0.4989;
  split delta +0.0056; best-F1 flags 7.9% at P 0.504 / R 0.660.
- Ablations: oracle+variant 1.0000; leaky+satisfaction PR-AUC 0.4934 (+22% vs 0.4029);
  text-only 0.7774/0.1819; categorical-only 0.8408/0.3928; temporal-only 0.5280/0.0587;
  exclude-Variant-7 0.6095/0.0358.
- Variant 7 = 1,261 cases (4.0%), 100% Bug, 100% L3, supplies 63.72% of L3 positives.
- `escalated` base rate 59.65%; AUC 0.6400/0.6481; best-F1 flags 87–89%.
- `slow_24h`: 5,224/31,588 = 16.54%; AUC 0.9326/0.9304; LogReg best-F1 flags 27.628% at
  P 0.5779 / R 0.9450; HistGB best-F1 flags 29.474% at P 0.5546 / R 0.9675.
- Regressor MAE 3.5927 h, R² 0.6832, Spearman 0.8147; baseline MAE 7.0364 h.
- Permutation importance: `issue_type` 0.294, `short_description` 0.189, all temporal
  ≤ 0.010; `priority` and `report_channel` negative (noise).
- **DB check:** slow>24h 5,224; Low 9,348 with 5,144 breaches (55.0%); Medium 15,774 with 80;
  High 6,466 with **0**.
- **DB check:** outside Variant 7, 718 of 30,327 reach L3; non-V7 Bugs reaching L3 = 229 of
  5,543 (4.1%); non-Bug L3 = 489. `Bug` rule captures 75.3% of all L3 positives.
- **DB check:** `Bug AND Low` = 2,046 cases, 465 reach L3 (precision 0.227).
- **DB check:** `priority` has zero intra-case variation in 31,588 cases; `short_description`
  has zero intra-case variation.
- `customer_satisfaction` present on every row including creation, 0 nulls — post-closure
  survey score denormalised onto intake rows.

### INFERRED (reasoned, not directly measured)
- The L3 model's skill is substantially "`issue_type = Bug` co-occurs with Variant 7",
  not generalisable escalation-risk judgement.
- `reached_level_3` is partly circular with variant membership; the oracle AUC 1.0000 is
  evidence of circularity, not predictability.
- `escalated` at a 59.65% base rate has almost no decision content; flagging 87–89% of
  tickets is not triage.
- **`slow_24h` is redundant**: `priority='Low'` gives P 0.550 / R 0.985 vs the model's
  P 0.578 / R 0.945. The model matches on precision and loses on recall.
- `slow_24h`'s value was as an independent rediscovery of the priority inversion —
  corroboration of RESULTS §4 by separate method.
- Temporal features carry no duration signal; arrival time does not predict duration.
- Artemis's proposed `Bug + Low → pre-route` rule is dominated by the model it would
  replace (P 0.227 vs 0.504).
- A one-condition `priority='Low'` rule is near-optimal; no issue-type split separates
  breaches within Low (44–55%).
- A rule encoding the inversion becomes actively harmful if the inversion is corrected.
- For the L3 decision the model should be superseded by a structural change (separate
  Variant 7 process), not replaced by a rule.
- `priority` being stamped once and never revised is consistent with a creation-time
  static value rather than a live triage decision.

### HYPOTHESES (with the test that would settle each)
1. **`priority` is assigned at creation from a static field, not as an ex-ante urgency
   judgement.** *Test:* reconstruct label-assignment timestamp vs first-assignment and
   first-escalation timestamps; if assignment always precedes first L1 contact, and never
   follows it, H1 holds. Refuted by any case where priority changes after work has begun.
   → **This is the recommended next analysis (§6).**
2. **Low priority is a holding bucket that never gets worked** (RESULTS §4's own reading).
   *Test:* decompose the 25.76 h Low mean into queue-wait vs active-attempt; if Low's
   `Ticket created` dwell is long but its L1 attempt dwell matches High's, the bucket
   reading holds.
3. **Variant 7 is partly synthetic.** *Test:* check for exact timestamp-spacing regularity,
   duplicated per-case event sequences, and whether the double-escalation-to-L3 occurs at
   a fixed offset. *Refuted* by natural variation in offsets. This must be settled before
   any operational conclusion is drawn about Variant 7.
4. **The 80 Medium-priority breaches are a distinct sub-population** (e.g. Bugs escalating
   to L3). *Test:* inspect the 80 cases; only 229 non-V7 Bugs reach L3, so cross-tabulate.
5. **Skipping the L1 attempt for pre-routed tickets would actually save elapsed time.**
   *Test:* impossible from logs — needs a controlled trial. Explicitly UNKNOWN.

### UNKNOWN (not establishable from available evidence)
- Whether pre-routing saves or merely relocates the ~4.2 h L1 attempt. No counterfactual
  exists in an event log.
- The true meaning and assignment mechanism of `priority` — the project's own stated
  open question, still open.
- Whether the data is real or partly synthetic (Variant 7's zero variance is a live flag).
- Whether any of this generalises beyond 2023 — one year, one organisation, no drift
  detected but only within that year.
- Business cost of a missed SLA breach (no monetary or contractual data in the dataset),
  so the ~288 missed breaches/yr cannot be priced.
- Whether the 27.6% review load is actually infeasible — depends on reviewer seconds per
  ticket, which is not in the data.