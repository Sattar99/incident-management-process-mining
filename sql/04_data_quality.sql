-- 04_data_quality.sql : known defects in the source data.
--
-- These are NOT pipeline bugs. They are properties of Incident_Management_CSV.csv
-- that materially affect how the metrics should be read. Each is quantified here
-- so the numbers in the docs can be interpreted correctly.

-- Completeness by column -----------------------------------------------------
SELECT
    count(*)                                                          AS total_rows,
    count(*) FILTER (WHERE variant IS NULL)                           AS null_variant,
    count(*) FILTER (WHERE priority IS NULL)                          AS null_priority,
    count(*) FILTER (WHERE reporter IS NULL)                          AS null_reporter,
    count(*) FILTER (WHERE event IS NULL)                             AS null_event,
    count(*) FILTER (WHERE issue_type IS NULL)                        AS null_issue_type,
    count(*) FILTER (WHERE resolver IS NULL)                          AS null_resolver,
    count(*) FILTER (WHERE report_channel IS NULL)                   AS null_channel,
    count(*) FILTER (WHERE short_description IS NULL)                 AS null_description,
    count(*) FILTER (WHERE customer_satisfaction IS NULL)             AS null_satisfaction
FROM incident_data;


-- Rows with a NULL event name (breaks transition labelling) ---------------
-- Known: INC0305 has one such row. It is excluded from v_transition_metrics.
SELECT case_id, event_timestamp, resolver
FROM incident_data
WHERE event IS NULL
ORDER BY case_id, event_timestamp;


-- Resolver nulls are structural, not random ---------------------------------
-- Support/touchpoint events legitimately have no resolver, so NULL resolver
-- means "system transition", not "missing data". Filling these with a literal
-- 'Unknown' (as an earlier notebook did) inflates COUNT(DISTINCT resolver) by
-- one per affected case and overstates staffing involvement.
SELECT
    event,
    count(*)                                                    AS rows,
    count(*) FILTER (WHERE resolver IS NULL)                    AS null_resolver,
    round(100.0 * count(*) FILTER (WHERE resolver IS NULL) / count(*), 2) AS null_pct
FROM incident_data
GROUP BY event
ORDER BY rows DESC;


-- Customer satisfaction ceiling per variant -------------------------------
-- Four variants top out at 3 while the rest reach 5. Satisfaction for those
-- variants is capped, so cross-variant satisfaction comparisons are only
-- meaningful between capped and uncapped groups, not within them.
SELECT
    variant,
    count(*)                                                        AS incidents,
    min(customer_satisfaction)                                      AS min_score,
    max(customer_satisfaction)                                      AS max_score,
    round(avg(customer_satisfaction)::numeric, 2)                  AS mean_score,
    (max(customer_satisfaction) = 3)                                AS appears_capped_at_3
FROM v_case_metrics
GROUP BY variant
ORDER BY mean_score;


-- Out-of-order and negative intervals -------------------------------------
-- Must be zero; a non-zero count would mean clock skew in the source.
SELECT
    count(*) FILTER (WHERE to_timestamp < from_timestamp) AS out_of_order,
    count(*) FILTER (WHERE duration_hours < 0)             AS negative_durations,
    count(*)                                               AS total_transitions
FROM v_transition_metrics;