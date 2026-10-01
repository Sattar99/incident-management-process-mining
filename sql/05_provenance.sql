-- 05_provenance.sql : is this data real, or generated?
--
-- WHY THIS FILE EXISTS
-- --------------------
-- Three findings during the ML investigation could not be explained by ordinary
-- operational behaviour:
--
--   1. `reached_level_3` is an EXACT function of variant membership. All 1,979
--      L3 cases are Variant 6 (718) or Variant 7 (1,261). Zero variants have a
--      mixed L3 outcome. No case outside those two variants ever reaches L3.
--   2. Every variant has exactly ONE event count. 12 of 13 variants have exactly
--      one distinct event SEQUENCE. (Variant 10 has 2.)
--   3. `priority` multiplies every dwell time by nearly the same factor
--      (intake x1.88/x3.95 and L1 work x1.89/x3.83 for Medium/Low).
--
-- Real incident processes do not behave this way. Variants are defined BY their
-- sequence, so (1) is partly definitional rather than suspicious. But (2) and (3)
-- are not, and together they are consistent with a generator parameterised on
-- `priority` and `variant`.
--
-- ONLY THE DATA OWNER CAN SETTLE THIS. Nothing in these queries proves
-- generation or proves reality. They exist to quantify the concern so it is
-- visible to anyone reading the results, instead of living in prose.
--
-- Run 05_provenance.sql and read the verdict row at the end.


-- 1. Determinism: is each variant a single fixed sequence? -------------------
-- One distinct sequence per variant is the normal case for process mining
-- (a variant IS a sequence). This query is therefore a control, not a finding:
-- it shows the measurement works, and isolates any variant that deviates.
WITH paths AS (
    SELECT case_id,
           variant,
           string_agg(event, ' > ' ORDER BY event_timestamp) AS path
    FROM incident_data
    WHERE event IS NOT NULL          -- INC0305's NULL label has no sequence
    GROUP BY case_id, variant
)
SELECT
    variant,
    count(*)                                                        AS cases,
    count(DISTINCT path)                                            AS distinct_sequences,
    count(DISTINCT path) - 1                                        AS deviation_from_single_sequence
FROM paths
GROUP BY variant
ORDER BY deviation_from_single_sequence DESC, cases DESC;


-- 2. Event-count variance within variant -----------------------------------
-- A real process shows spread: cases are cut short, reworked, or abandoned.
-- Zero spread across every case of every variant means every case follows
-- the same length path every time.
SELECT
    variant,
    count(*)                                                        AS cases,
    min(event_count)                                                 AS min_events,
    max(event_count)                                                 AS max_events,
    max(event_count) - min(event_count)                              AS event_count_spread,
    round(avg(cycle_time_hours)::numeric, 2)                        AS mean_cycle_hours,
    round(stddev_samp(cycle_time_hours)::numeric, 2)                AS cycle_hours_sd
FROM v_case_metrics
GROUP BY variant
ORDER BY event_count_spread, cases DESC;


-- 3. Does priority scale every state, or only some? ------------------------
-- Real triage changes WHERE time is spent (queueing vs active work) and
-- usually leaves attempt duration alone. If priority multiplies intake wait
-- and L1 work by the SAME factor, priority is acting as a global time
-- multiplier -- which is what a generator parameterised on priority would do,
-- and not what a queueing process does.
WITH state_hours AS (
    SELECT priority,
           from_event,
           sum(duration_hours) AS hours
    FROM v_transition_metrics
    GROUP BY priority, from_event
),
baseline AS (
    SELECT from_event, hours AS base_hours
    FROM state_hours WHERE priority = 'High'
)
SELECT
    s.from_event,
    s.priority,
    round(s.hours, 0)                                               AS total_hours,
    round(s.hours / b.base_hours, 3)                                 AS multiplier_vs_high
FROM state_hours s
JOIN baseline b ON b.from_event = s.from_event
WHERE s.from_event IN ('Ticket created',
                       'WIP - level 1 support',
                       'WIP - level 2 support')
ORDER BY s.from_event, s.priority;


-- 4. Is reached_level_3 fully explained by variant? ------------------------
-- This is the decisive structural check. If L3 lies entirely inside two
-- variants, then "predict L3 at intake" was never a prediction problem --
-- the answer was already carried by the variant label.
SELECT
    variant,
    count(*)                                                        AS cases,
    count(*) FILTER (WHERE reached_level_3)                         AS reached_l3,
    round(100.0 * count(*) FILTER (WHERE reached_level_3) / count(*), 2)
                                                                    AS l3_pct,
    CASE WHEN count(*) FILTER (WHERE reached_level_3) = count(*)  THEN 'ALL'
         WHEN count(*) FILTER (WHERE reached_level_3) = 0           THEN 'NONE'
         ELSE 'MIXED' END                                           AS l3_behaviour
FROM v_case_metrics
GROUP BY variant
ORDER BY reached_l3 DESC, cases DESC;


-- 5. Cross-check: cases outside the two deterministic variants ----------
-- If the L3 label is fully contained in Variants 6 and 7, this is the
-- population with nothing left to predict. It is 93.8% of all incidents.
SELECT
    count(*)                                                        AS total_cases,
    count(*) FILTER (WHERE variant IN ('Variant 6', 'Variant 7'))  AS in_deterministic_variants,
    count(*) FILTER (WHERE variant NOT IN ('Variant 6', 'Variant 7'))
                                                                    AS outside_them,
    count(*) FILTER (WHERE reached_level_3
                     AND variant NOT IN ('Variant 6', 'Variant 7'))
                                                                    AS l3_outside_them,
    round(100.0 * count(*) FILTER (WHERE variant NOT IN ('Variant 6','Variant 7'))
          / count(*), 2)                                            AS pct_population_without_signal
FROM v_case_metrics;


-- 6. VERDICT -----------------------------------------------------------
-- A single row summarising the evidence. Deliberately conservative: this
-- reports OBSERVABLE STRUCTURE, not a conclusion about authenticity. Only
-- the data owner can answer whether the source is real operational data.
SELECT
    'provenance check'                                              AS check_name,
    (SELECT count(*) FROM (SELECT variant FROM v_case_metrics
                          GROUP BY variant
                          HAVING count(DISTINCT event_count) > 1) x)
                                                                    AS variants_with_event_count_spread,
    (SELECT count(*) FROM (
        SELECT variant
        FROM (
            SELECT variant, case_id,
                   string_agg(event, ' > ' ORDER BY event_timestamp) AS seq
            FROM incident_data
            WHERE event IS NOT NULL
            GROUP BY variant, case_id
        ) p
        GROUP BY variant
        HAVING count(DISTINCT seq) > 1
     ) y)                                                         AS variants_with_multiple_sequences,
    (SELECT count(*) FILTER (WHERE reached_level_3
                             AND variant NOT IN ('Variant 6','Variant 7'))
     FROM v_case_metrics)                                           AS l3_outside_deterministic_variants,
    'UNRESOLVED - requires the data owner. Zero event-count spread and'
    ' single-sequence variants are consistent with a generator, and also'
    ' with a tightly standardised process. This query cannot'
    ' distinguish the two. See ML_FINDINGS.md section 6.'
                                                                    AS verdict;
