-- Bottlenecks.sql : where cycle time is actually lost.
--
-- CORRECTION vs the previous Bottleneck_Identification.pgsql
-- The old query used LAG(timestamp) and then labelled the resulting wait with
-- the event that came AFTER the wait. So "Ticket escalated to level 2 support"
-- was really reporting time spent in "WIP - level 1 support". These queries use
-- v_transition_metrics, which attributes a duration to the state it was spent in.

-- Process-wide transition bottlenecks ---------------------------------------
-- "mean_hours" is the time spent in from_event before moving to to_event.
SELECT
    transition,
    COUNT(*)                                                            AS occurrences,
    COUNT(DISTINCT case_id)                                             AS cases,
    ROUND(100.0 * COUNT(DISTINCT case_id) /
          (SELECT COUNT(DISTINCT case_id) FROM incident_data), 2)      AS case_percentage,
    ROUND(AVG(duration_hours)::numeric, 3)                              AS mean_hours,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_hours)::numeric, 3)
                                                                        AS median_hours,
    ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY duration_hours)::numeric, 3)
                                                                        AS p75_hours,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_hours)::numeric, 3)
                                                                        AS p95_hours,
    ROUND(MAX(duration_hours)::numeric, 3)                              AS max_hours
FROM v_transition_metrics
GROUP BY transition
ORDER BY mean_hours DESC;


-- Variant 7 transition bottlenecks ------------------------------------------
-- Variant 7 is the slowest and least satisfying variant, so it gets a full
-- transition-level breakdown.
WITH v7 AS (
    SELECT * FROM v_transition_metrics WHERE variant = 'Variant 7'
),
totals AS (
    SELECT COUNT(DISTINCT case_id) AS n FROM v7
)
SELECT
    transition,
    COUNT(DISTINCT case_id)                                             AS cases,
    ROUND(100.0 * COUNT(DISTINCT case_id) / (SELECT n FROM totals), 2)   AS case_percentage,
    COUNT(*)                                                            AS occurrences,
    ROUND(AVG(duration_hours)::numeric, 3)                              AS mean_hours,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_hours)::numeric, 3)
                                                                        AS median_hours,
    ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY duration_hours)::numeric, 3)
                                                                        AS p75_hours,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_hours)::numeric, 3)
                                                                        AS p95_hours,
    ROUND(MAX(duration_hours)::numeric, 3)                              AS max_hours
FROM v7
GROUP BY transition
ORDER BY median_hours DESC;


-- Rework: events that occur more than once per case -----------------------
-- Repeat occurrences of the same event inside one case indicate a rework loop.
SELECT
    variant,
    event,
    COUNT(*)                                                  AS cases,
    SUM(occurrences)                                           AS total_occurrences,
    ROUND(AVG(occurrences)::numeric, 2)                        AS mean_occurrences,
    MAX(occurrences)                                           AS max_occurrences
FROM (
    SELECT variant, case_id, event, COUNT(*) AS occurrences
    FROM incident_data
    WHERE variant = 'Variant 7'
    GROUP BY variant, case_id, event
) t
GROUP BY variant, event
ORDER BY max_occurrences DESC, mean_occurrences DESC, event;


-- Escalation funnel ---------------------------------------------------------
SELECT
    issue_type,
    COUNT(*)                                                            AS incidents,
    COUNT(*) FILTER (WHERE escalated)                                   AS escalated,
    ROUND(100.0 * COUNT(*) FILTER (WHERE escalated) / COUNT(*), 2)     AS escalation_rate_pct,
    COUNT(*) FILTER (WHERE reached_level_3)                             AS reached_l3,
    ROUND(100.0 * COUNT(*) FILTER (WHERE reached_level_3) / COUNT(*), 2) AS l3_rate_pct,
    ROUND(AVG(cycle_time_hours) FILTER (WHERE NOT escalated)::numeric, 2)     AS mean_hours_no_escalation,
    ROUND(AVG(cycle_time_hours) FILTER (WHERE escalated)::numeric, 2)         AS mean_hours_with_escalation
FROM v_case_metrics
GROUP BY issue_type
ORDER BY escalation_rate_pct DESC;