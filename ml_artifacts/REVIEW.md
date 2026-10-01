# ODIN — Independent Adversarial Review

**Reviewer:** ODIN · **Date:** 2026-10-01
**Artifacts read:** `ml_triage.py`, `ml_artifacts/metrics.json`, `ml_artifacts/run_log.txt`,
`ml_artifacts/INTERPRETATION.md`, `RESULTS_AND_SUGGESTIONS.md`, `etl_pipeline.py`, git log.
**Independent verification:** 9 read-only queries against `Incident_Management.incident_data`
(242,901 rows / 31,588 cases, re-confirmed), plus a refit of the `slow_24h` LogReg on the same
chronological split (reproduced AUC **0.9326**, matching metrics.json exactly).
**Standing:** the project holds itself to strict evidence standards after the 22.6% truncation
episode. That standard is applied here to *both* specialists, including the negative results.

---

## VERDICT

| # | Finding | Verdict |
|---|---|---|
| 1 | `priority='Low'` → P 0.550 / R 0.985 | **ESTABLISHED** (reproduced exactly from DB) |
| 2 | "The `slow_24h` model is redundant with the rule" | **SUPPORTED WITH LIMITATIONS** — true conclusion, wrong reason. At matched recall the *rule beats the model*; the model wins only at best-F1. See §A |
| 3 | Hercules's precision gloss ("matches on precision, within noise") | **CONTRADICTED BY THE DATA** — not noise. The model is worse than the rule at every matched-recall point tested |
| 4 | `Bug + Low → pre-route` rule is dominated | **ESTABLISHED** — P 0.2273, R 0.2350, reproduced |
| 5 | Excluding `customer_satisfaction` from intake features | **ESTABLISHED** (correct call) |
| 6 | Excluding `variant` from production features | **ESTABLISHED** (correct call) |
| 7 | "Intake features" framing (fields known *at* intake) | **PLAUSIBLE BUT UNVERIFIED** — staticness is equally consistent with backfill. §C |
| 8 | Headline `AUC 0.84` for `reached_level_3` | **CONTRADICTED BY THE DATA as a generalisable result** — `reached_level_3` is an *exact function of variant*. §D |
| 9 | "L3 is not actionable" / "escalation is a definition problem" | **SUPPORTED WITH LIMITATIONS** — directionally right, stated too absolutely. §E |
| 10 | Variant 7 is partly synthetic | **SUPPORTED WITH LIMITATIONS** — but for a *different and larger* reason than either specialist gave. §F |
| 11 | Priority-inversion rediscovery = "genuine cross-check" | **WEAK EVIDENCE** — substantially circular. §E |
| 12 | Recommended next analysis: priority-provenance audit | **UNSUPPORTED as specified** — the log structurally cannot answer it. §F |
| 13 | ML layer was a defensible use of effort | **SUPPORTED WITH LIMITATIONS** — yes, but with a sequencing indictment. §G |
| 14 | "8 distinct strings. There is nothing to model." | **ESTABLISHED** — verified, 8 values, max 21 chars |
| 15 | RESULTS §6 "Longer term" text-classifier proposal is falsified | **ESTABLISHED** — must be struck |

---

## DISCREPANCIES FOUND

Every figure below is recomputed from the database or refit, not taken from either document.

| # | Claim | Claimed | **Verified** | Note |
|---|---|---|---|---|
| D1 | Low / Medium / High breach counts | 5,144 / 80 / 0 | **5,144 / 80 / 0** ✓ | Reproduced exactly |
| D2 | Rule precision / recall | 0.550 / 0.985 | **0.5503 / 0.9847** ✓ | 5,144 / 9,348; 5,144 / 5,224 |
| D3 | **Rule F1 — never computed by either specialist** | — | **0.7060** | **Model best-F1 F1 = 0.7172. The model wins F1 by 1.1 pts.** Hercules compares only P and R |
| D4 | "matches on precision (0.550 vs 0.578, within noise)" | "within noise" | **At the rule's own recall (0.979) the model scores P = 0.4665** | The gap is 8.3 precision points *in the rule's favour*. Not noise — the opposite sign |
| D5 | **Variant 6 L3 rate — not reported by anyone** | — | **718 of 718 = 100.0%** | Variant 6 is a *second* 100%-L3 variant. Both specialists analysed only V7 |
| D6 | "Outside Variant 7: 718 of 30,327 reach L3" | treated as diffuse residual | **All 718 are Variant 6. Zero non-V7 L3 outside Variant 6** | Hercules's "718/yr spread across 30,327 tickets" is wrong in kind: it is one homogeneous deterministic cluster |
| D7 | Excluding V7 → base rate 2.33%, AUC 0.61 | "too small to matter" | **Excluding V7 *and* V6: n = 29,609, L3 positives = 0** | The target is not rare-and-hard. It is **exhaustively enumerated** |
| D8 | "Variant 7 has zero variance" | RESULTS §7 | **Cycle-time std = 13.49 h; mean 26.64** | Zero *structural* variance (event sequence), NOT zero duration variance. Wording invites over-correction |
| D9 | `short_description` 8 values, max 21 chars | stated | **8 values confirmed** ✓ | But all 18,915 V7 rows carry the single value `Application crash` |
| D10 | RESULTS §6 "~2 h (~16%) off the median" | 2 h, 16% | **1.48–1.84 h, 11.6–14.5%** | Only reaches 2 h/16% by mixing the *mean* L1 (4.2 h) with a *median* denominator (12.72 h). Overstated |
| D11 | Hercules: "HistGB flags 29.5%" | 29.5% | **29.474%** ✓ | Correct |
| D12 | Within-Low predictive power | "no issue type meaningfully separates them" | **issue_type AUC 0.601; all four together AUC 0.612** | Directionally right; 0.61 is not nothing. Claim should be quantified, not asserted |
| D13 | Priority dwell-multiplier | not reported | **Intake ×1.88/×3.95, L1 work ×1.89/×3.83 for Med/Low** | The two multipliers agree to within 1%. New evidence — see §F |

D1, D2, D9, D11 reconcile. **D3–D8, D10, D12, D13 do not appear in either document and must be
addressed before publication.**

---

## TECHNICAL REVIEW (ARTEMIS)

**The engineering is genuinely strong and I am not going to manufacture doubt about it.**
Reproducing the LogReg refit to 4 decimal places from the raw database, the leakage contract
in the module docstring, the mandatory base-rate-before-metric reporting, the permutation
importance table, and the explicit refusal to publish an oracle ablation as performance — this
is better practice than most portfolio work.

**Leakage exclusions: both correct.**

- `customer_satisfaction` — excluding it is right, and the reasoning is right for the right
  reason. I verified it is non-null on all 31,588 cases including every `Ticket created` row.
  A customer cannot rate handling that has not happened; its presence on the creation row is a
  denormalisation artefact. Excluding it *and* reporting the delta as an ablation is the correct
  handling. The +22% PR-AUC it buys is a fair measure of how much a careless pipeline would
  have flattered itself.
- `variant` — correct, and correctly quarantined as an oracle rather than a feature.

**Where the framing overreaches: "at intake."** Every candidate intake feature —
`priority`, `issue_type`, `report_channel`, `reporter`, `short_description`, `customer_satisfaction`,
`variant` — has **exactly zero intra-case variation across all 31,588 cases.** I verified this for
all seven. Staticness is evidence that a value is *written once*. It is **not** evidence that it is
written *at t₀*. A column backfilled after case closure is equally static. `priority` is not
special here; it is in exactly the same epistemic position as `issue_type`, and Artemis treats one
as intake-available and the other as post-hoc suspect. That inconsistency matters, because the
whole `slow_24h` result is a re-derivation of `priority` — so if `priority` is backfilled, the
model's 0.93 AUC is measuring a post-outcome field, and the leakage analysis has a hole in it at
the load-bearing feature. **This is the single largest unforced weakness in the ML work.**

**The exclusion list is defensible but the *discipline* is not consistently applied.** Everything
excluded is excluded on "not known at intake." That principle is correct. It is then not applied
to `priority`, which is the one field where it actually bites.

**Minor:** `desc_length` has permutation importance 0.001 and is 8 distinct values × fixed strings
— a deterministic function of `short_description`, i.e. a redundant feature. Harmless, but it
inflates the appearance of a rich temporal block. Four of six temporal features are exactly zero.

---

## THE CIRCULARITY PROBLEM — the finding that changes the picture

Artemis already flagged the oracle (variant → AUC 1.0000) as an upper bound. Hercules correctly
says the oracle proves circularity. **Both understate it, because neither checked whether
`reached_level_3` has any variance left once you remove the two deterministic variants.**

I checked. Per-variant L3 rates:

```
Variant 7      1,261 cases    1,261 L3   100.0%
Variant 6        718 cases      718 L3   100.0%
all 11 others  29,609 cases        0 L3     0.0%
```

**`reached_level_3` is not a stochastic outcome. It is an exact function of process-mining variant
membership.** Excluding Variants 6 and 7 leaves **29,609 cases and zero positives** — a base rate
of exactly 0.0000. Hercules reports the intermediate number (exclude V7 → 718 cases) and calls it
a "diffuse residual spread across 30,327 tickets." It is not diffuse. It is **one variant, 718
cases, 100% positive**, i.e. the same deterministic structure as V7, one tier down.

Three consequences:

1. **The `AUC 0.84` is not measuring foresight. It is measuring cluster recovery.** The task is
   "guess which of two fixed trace archetypes this ticket will follow, from a field that is
   near-deterministically tied to the archetype." V7 is 100% Bug / 100% `Application crash`; V6
   spans all 7 issue types and all 8 descriptions. A model that learns "`issue_type=Bug` and short
   crash text → V7" gets exactly the ~0.84 reported. **That is a real skill at recovering a
   synthetic generator's label from its fingerprint. It is not a skill at predicting escalation.**
2. **The headline number should NOT be published as "AUC 0.84 for L3 prediction."** It is a
   number about a label that was defined by clustering the thing you are predicting. Publish it
   with the variant-6 fact attached or not at all.
3. **The `EXCLUDING Variant 7` ablation (AUC 0.6095) is the most informative row in the table and
   is presented as a supporting footnote.** It should be the headline caveat.

---

## INTERPRETATION REVIEW (HERCULES)

### Where he is right, and right for better reasons than he gives

**The decisive claim is verified and his conclusion is, if anything, understated.** I recomputed
`priority='Low'` → P **0.5503** / R **0.9847** on all 31,588 cases. Reproduced exactly. The
`slow_24h` model is not deployable. That is the right conclusion.

**But the comparison as framed is not fair, and it does not favour him.** He compares the rule at
**29.6% flags** against the model at **27.6% flags** — different review budgets — and then reports
the precision gap as "within noise." It is not noise, and I checked at matched operating points:

| Comparison | Rule | Model | Winner |
|---|---:|---:|---|
| Best-F1 **F1** | 0.7060 | **0.7172** | Model (+1.1 pt) |
| Precision @ best-F1 | 0.5494 | 0.5775 | Model (+2.8 pt) |
| **Precision @ rule's own recall (0.979)** | **0.5494** | **0.4665** | **Rule (+8.3 pt)** |
| **Precision @ flag rate 0.3012 (rule's budget)** | **0.5494** | **0.5494** | **Tie** |

So: the model is genuinely better at its own chosen operating point, and the rule is genuinely
better once you hold recall fixed. Hercules reports only the first comparison and calls the
precision gap "within noise." **That is the wrong characterisation, and it happens to understate
his own case** — at matched recall the rule wins by 8.3 points, not 0. He should have said "the
rule dominates at matched recall" instead of "matches on precision."

### Where he is overconfident

**"Escalation is a definition problem, not a prediction problem."** Overstated. AUC 0.640/0.648
against a 59.65% base rate is weak, and his "flags 87–89% of tickets" point is fair — but
"no decision content" is an inference about *the business*, dressed as an inference about *the
data*. The data shows a weak-but-real signal (PR-AUC 0.7365 vs 0.5965 base rate, lift 1.24). The
correct statement is: **escalation is a weak target at a base rate that makes thresholded action
expensive.** Whether it has decision content depends on whether escalating costs anything scarce —
which is not in the data. Note also that a 59.65% "escalation rate" in a support process is itself
a finding worth escalating to the process owner, not a target to delete.

**"L3 is not actionable."** Right conclusion, wrong supporting argument. He grounds it on "718
cases a year spread across 30,327 tickets" — but as shown, those 718 are Variant 6, a single
100%-positive deterministic variant. So L3 is not *unactionable*; it is **fully enumerable by
variant membership**, which is a stronger and more useful statement. Handle V6 the way RESULTS §6
already says to handle V7 — as a separate process. **RESULTS §6 recommendation 6 is incomplete:
it names Variant 7 only. Variant 6 has the same 100%-L3 structure and is not mentioned anywhere in
the project.**

**"The priority-inversion rediscovery is a genuine cross-check."** Weak. The model was trained on
`priority` as an input feature. A model that takes `priority` as input and achieves AUC 0.93 on
slow-outcomes is *demonstrating that priority predicts slowness* — that is not an independent
rediscovery, it is a restatement with extra steps. **Permutation importance already said this
directly: `priority` had importance −0.005 (i.e. noise), while the model still hit AUC 0.93.** The
model did not learn priority as a decision surface; it recovered the same partition from
issue_type and text. That is mildly informative about robustness, but calling it "corroboration
of RESULTS §4 from a completely separate method" is a stretch. It is corroboration that *the
dataset contains a priority/slowness association*, which was never in doubt.

---

## VARIANT 7 — THE SYNTHETIC HYPOTHESIS, RE-EXAMINED

**What survives.** Structural uniformity is real and I confirmed it: V7 has exactly one
(short_description, issue_type) pair — `Application crash`/`Bug` — across 18,915 rows, 100% L3, and
satisfaction capped at 3.

**What does not survive: "zero variance."** RESULTS §7 and Hercules both lean on this. Cycle-time
std within V7 is **13.49 h** on a mean of 26.64 h (CV ≈ 0.51). Gap std per step is 0.19–3.02 h.
**There is substantial duration variation.** The uniformity is *structural* (which events occur),
not *temporal* (how long they take). This matters in both directions: it weakens the "looks
generated" case somewhat, and it means RESULTS §7's phrasing ("zero variance") is imprecise enough
to be embarrassing — V7 has *more* duration variance than the dataset overall (Low std 8.05 h on
mean 25.76 vs V7 13.49 on 26.64).

**The decisive point neither specialist made.** I decomposed dwell time by priority:

| Priority | Intake wait (h) | L1 work (h) | Intake ×High | Work ×High |
|---|---:|---:|---:|---:|
| High | 1.679 | 2.395 | 1.00 | 1.00 |
| Medium | 3.161 | 4.521 | 1.883 | 1.888 |
| Low | 6.630 | 9.163 | **3.949** | **3.826** |

**The intake-wait multiplier and the L1-work multiplier agree to within 1% for both Medium and Low.**
If priority were a triage decision — someone choosing to deprioritise a ticket and thereby leaving
it in queue — intake wait would rise while work time stayed flat. It does not. **Both rise by the
same factor.** That is the signature of `priority` acting as a *time multiplier* on the generator,
not as a behavioural signal about queueing. It is a second, independent reason to suspect the data
is synthetic, and it is a much stronger argument for the provenance audit than anything in
RESULTS §4 — while simultaneously making that audit unanswerable from this log.

**What collapses if the data is partly synthetic:** essentially all of RESULTS §4 and §5, the
`slow_24h` model entirely, and the priority-inversion headline. **What survives:** the ETL/COPY
rebuild, the 18-test CI suite, the parity assertions, and the *method* — every query in this
project is reproducible and re-runnable, which is the actual deliverable.

---

## THE RECOMMENDED NEXT ANALYSIS — IT CANNOT BE ANSWERED

**Hercules's priority-provenance audit is the right question and the wrong instrument.** He says
explicitly it will work "from the event log's own structure" by reconstructing "label-assignment
timestamp." **There is no such timestamp.** I enumerated every column:

```
event_id, case_id, variant, priority, reporter, event_timestamp, event,
issue_type, resolver, report_channel, short_description, customer_satisfaction
```

One time column, `event_timestamp`, one value per event. There is no `priority_set_at`, no audit
table, no revision history — and `priority` has zero intra-case variation, so there is nothing to
reconstruct *from*. His H1 test ("if assignment always precedes first L1 contact, and never follows
it") is **untestable**: with a single static column there is no assignment event to order against
anything. His own probe ("priority never varies within a case") is evidence that the audit is
impossible, and he reads it as evidence for the hypothesis.

**So: is this unfalsifiable optimism dressed as rigour? Partly.** The framing promises "it uses only
what the log contains" — it does not. He is right that a non-ML analysis is the correct next step,
and right that it must precede the rule. He is wrong that this one can be done. Presenting an
unrunnable analysis as "the deliverable that matters," with "a few SQL queries against data already
loaded" as its cost, is the most misleading sentence in INTERPRETATION.md.

**What to do instead:**
1. **Ask a person, not the log.** `priority` semantics is a question for the process owner. This
   is a one-email question, not an analysis. RESULTS §4 already says exactly this — the ML layer
   should not have pretended otherwise.
2. **Test the multiplier signature directly** (D13). If the ratio test holds on data from another
   source, the inversion is a generator artifact and there is nothing to audit operationally.
3. **Establish provenance of the dataset as a whole.** The V6/V7 determinism and the priority
   multiplier are both reasons to ask where this CSV came from before any operational
   recommendation is built on it.

---

## IS THE ML LAYER DEFENSIBLE? (SEQUENCING, BLUNTLY)

**Yes, and Hercules is right to say so — but his framing is too comfortable.** The layer produced a
genuine negative: 8 boilerplate strings, no text to model. Negative results are worth having, and
the discipline of running a proper chronological split and reporting ablations made the negative
*conclusive* rather than speculative. That is real value.

**But the sequencing was wrong, and the log shows it.** The project had already documented, in
RESULTS §4, that priority was inverted, that the cause was unknown, and that it "cannot be resolved
from event logs alone." The ML layer was then built with `priority` as an input feature, and its
strongest result was rediscovering that inversion. **The decisive question was asked in §4 and
left open; the ML layer spent its effort re-deriving an answer already in hand.** What would have
been worth building first: anything that attacked the V6/V7 determinism, which I found in one
query and which was missed by two specialists and a 998-line script.

**The honest framing for the README:** not "we tried ML and it didn't work," but "we established
that the `short_description` ML layer cannot be built, and in doing so surfaced that
`reached_level_3` is exactly the set {Variant 6, Variant 7} — which is a more useful finding than
the model would have been."

---

## WHAT MUST CHANGE BEFORE PUBLICATION

**Must be corrected (factual errors that will not survive review):**

1. **Variant 6 is missing from the entire project.** 718 cases, 100% L3, 18.74 h mean. RESULTS §5
   and §6 recommendation 6 must add it. This is the biggest omission found.
2. **Strike "zero variance"** wherever it appears (RESULTS §7 caveat, INTERPRETATION §2). V7 cycle
   std is 13.49 h. Say "zero *structural* variance in event sequence."
3. **Add the variant-6 finding to the circularity argument.** Excluding V6+V7 leaves 29,609 cases
   and **zero** positives. This is the single most important number in the review.
4. **Fix RESULTS §6's "2 h (~16%)".** Correct range is **1.48–1.84 h, 11.6–14.5%** of the median.
   The current figure mixes a mean L1 attempt with a median denominator.
5. **Fix "every single breach except 80 Medium cases is Low."** 5,144 Low + 80 Medium + 0 High =
   5,224 ✓ — this one reconciles. But INTERPRETATION §3.2's "beats it on recall by 4 points"
   understates it (recall gap is 0.985 vs 0.945 = **4.0 points** ✓, correct) while §3.2's
   "matches on precision (within noise)" does **not** survive — replace with the matched-recall table.

**Must carry explicit caveats:**

6. **AUC 0.84 must never appear without the V6/V7 caveat.** Suggested phrasing: *"AUC 0.840
   predicting `reached_level_3`, a label that is exactly the union of two deterministic
   process-mining variants (V7: 1,261 cases; V6: 718 cases). The metric measures cluster recovery,
   not escalation foresight. Excluding both variants leaves 29,609 cases with zero positives."*
7. **The `slow_24h` result must state the redundancy up front**, with the honest note that the
   model wins F1 at its own threshold and the rule dominates at matched recall. Do not publish
   0.9326 unaccompanied — a reader will assume it is deployable.
8. **Every intake-framed claim needs the staticness caveat** (task 2): zero intra-case variation
   is consistent with creation-time assignment *and* post-hoc backfill. Applies to `priority`,
   `issue_type`, `report_channel`, `reporter`, `short_description`.

**Must NOT be published at all:**

9. **The priority-provenance audit as a log-based deliverable.** Cannot be executed. Replace with
   "escalate to the process owner" + the multiplier test.
10. **"Genuine cross-check" framing** for the priority rediscovery. It is substantially circular —
    `priority` was a model input.
11. **Any implication that `Bug + Low → pre-route` is a usable rule** (P 0.2273, R 0.2350).
12. **The `short_description` classifier proposal** (RESULTS §6 "Longer term"). Strike it — correct
    call by Hercules, and he is right for the right reason.
13. **The saved `.pkl` model files.** They are fitted on a label that is a deterministic function of
    variant membership. Shipping them invites someone to load and deploy. Either delete or add a
    prominent README warning.

---

## WHAT SURVIVES

- **ETL/COPY rebuild, parity assertions, 18-test CI suite** — the strongest asset here, and the
  direct answer to the truncation episode. Untouched by anything in this review.
- **Priority inversion is REAL and ROBUST.** Low 25.76 h / Medium 12.28 h / High 6.23 h, holds
  within every issue type and variant, 0 High breaches. Verified. **But** the D13 multiplier
  signature says it is more likely a generator artifact than a behavioural finding. Publish the
  measurement; do not publish the causal story.
- **Three states hold 72.8% of elapsed time** (WIP-L1 28.8%, intake 25.9%, WIP-L2 18.2%).
  Unaffected by the ML layer.
- **`short_description` is boilerplate** — 8 values, 21 chars max. Established, and the cleanest
  negative result in the project.
- **`escalated` is a weak target** (AUC 0.64 at 59.65% base rate). Established as weak; the
  "drop it" recommendation is a business call, not a data call.
- **Cycle-time regression R² 0.683** — established as a measurement, but note it is substantially
  `priority` and the duration features in disguise.
- **The intake-fixing recommendation** — untested by ML, not refuted. Rests on the process analysis
  alone. Note the discomfort Hercules correctly flags: temporal features carry no duration signal,
  so the intake queue may not be congestion-driven the way a WIP-limit fix assumes. **The D13
  result strengthens that discomfort considerably** — intake wait scales with priority at the same
  rate as work, which is not what a congested queue looks like.

---

## THE SINGLE MOST IMPORTANT UNRESOLVED QUESTION

**Is this dataset real operational data, or generated with `priority` and `variant` as
deterministic parameters?**

Everything else is downstream of it. Variant 6 and Variant 7 are each 100% L3 with zero
structural variance; `priority` multiplies every dwell time by the same factor for intake and for
work (×1.88/×1.89 Medium, ×3.95/×3.83 Low). Those are not the signatures of a support desk. If the
answer is "generated," then the priority inversion is a parameter of the generator, the `slow_24h`
model is fitting a generator, the L3 target is a lookup table, and **every operational
recommendation in RESULTS §6 — including the headline intake/WIP intervention — is describing the
generator, not a process.**

That question cannot be answered from the log. It has to be answered by whoever produced
`Incident_Management_CSV.csv`. Until it is, the strongest thing this project can honestly claim is
its data engineering: a complete, verified, transactional, reproducible load with assertions that
would have caught the truncation — plus one clean negative result and one alarming one.

---

*Review conducted read-only. No existing file was modified; no git operation was performed.
One file written: `ml_artifacts/REVIEW.md`. All figures independently recomputed against
`Incident_Management` (242,901 rows / 31,588 cases) or refit from source.*