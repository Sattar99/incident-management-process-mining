-- KPI.sql : headline process KPIs, computed from the fully loaded incident_data.
--
-- Every figure here is derived from v_case_metrics, which uses the corrected
-- forward-transition timing. Run sql/01_views.sql first.

-- Overall process KPIs -------------------------------------------------------
SELECT
    COUNT(*)                                                        AS incidents,
    ROUND(AVG(cycle_time_hours)::numeric, 2)                        AS mean_cycle_hours,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY cycle_time_hours)::numeric, 2)
                                                                    AS median_cycle_hours,
    ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY cycle_time_hours)::numeric, 2)
                                                                    AS p75_cycle_hours,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY cycle_time_hours)::numeric, 2)
                                                                    AS p95_cycle_hours,
    ROUND(MAX(cycle_time_hours)::numeric, 2)                        AS max_cycle_hours,
    ROUND(AVG(event_count)::numeric, 2)                             AS mean_events,
    ROUND(AVG(unique_resolvers)::numeric, 2)                        AS mean_resolvers,
    ROUND(AVG(customer_satisfaction)::numeric, 2)                    AS mean_satisfaction
FROM v_case_metrics;


-- Cycle time by issue type ---------------------------------------------------
SELECT
    issue_type,
    COUNT(*)                                                        AS incidents,
    ROUND(AVG(cycle_time_hours)::numeric, 2)                        AS mean_cycle_hours,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY cycle_time_hours)::numeric, 2)
                                                                    AS median_cycle_hours,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY cycle_time_hours)::numeric, 2)
                                                                    AS p95_cycle_hours,
    ROUND(AVG(event_count)::numeric, 2)                             AS mean_events,
    ROUND(AVG(customer_satisfaction)::numeric, 2)                    AS mean_satisfaction
FROM v_case_metrics
GROUP BY issue_type
ORDER BY median_cycle_hours DESC;


-- Cycle time by variant ------------------------------------------------------
SELECT
    variant,
    COUNT(*)                                                        AS incidents,
    ROUND(AVG(cycle_time_hours)::numeric, 2)                        AS mean_cycle_hours,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY cycle_time_hours)::numeric, 2)
                                                                    AS median_cycle_hours,
    ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY cycle_time_hours)::numeric, 2)
                                                                    AS p75_cycle_hours,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY cycle_time_hours)::numeric, 2)
                                                                    AS p95_cycle_hours,
    ROUND(AVG(event_count)::numeric, 2)                             AS mean_events,
    ROUND(AVG(unique_resolvers)::numeric, 2)                        AS mean_resolvers,
    ROUND(AVG(customer_satisfaction)::numeric, 2)                    AS mean_satisfaction
FROM v_case_metrics
GROUP BY variant
ORDER BY median_cycle_hours DESC;


-- Cycle time by intake channel ----------------------------------------------
SELECT
    report_channel,
    COUNT(*)                                                        AS incidents,
    ROUND(AVG(cycle_time_hours)::numeric, 2)                        AS mean_cycle_hours,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY cycle_time_hours)::numeric, 2)
                                                                    AS median_cycle_hours,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY cycle_time_hours)::numeric, 2)
                                                                    AS p95_cycle_hours,
    ROUND(AVG(event_count)::numeric, 2)                             AS mean_events,
    ROUND(AVG(customer_satisfaction)::numeric, 2)                    AS mean_satisfaction
FROM v_case_metrics
GROUP BY report_channel
ORDER BY median_cycle_hours DESC;


-- Escalation impact ----------------------------------------------------------
SELECT
    escalated,
    COUNT(*)                                                        AS incidents,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)               AS pct_of_incidents,
    ROUND(AVG(cycle_time_hours)::numeric, 2)                        AS mean_cycle_hours,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY cycle_time_hours)::numeric, 2)
                                                                    AS median_cycle_hours,
    ROUND(AVG(customer_satisfaction)::numeric, 2)                    AS mean_satisfaction
FROM v_case_metrics
GROUP BY escalated
ORDER BY escalated;


-- Cycle time and SLA breach by priority --------------------------------------
-- Counterintuitive but robust: LOWER priority means LONGER cycle time.
-- The priority mix is near-identical across issue types (~30% Low / 20% High
-- everywhere), so this is not confounding by issue type; the same ordering
-- holds within Bugs alone and within every individual variant.
SELECT
    priority,
    COUNT(*)                                                        AS incidents,
    ROUND(AVG(cycle_time_hours)::numeric, 2)                        AS mean_cycle_hours,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY cycle_time_hours)::numeric, 2)
                                                                    AS median_cycle_hours,
    ROUND(100.0 * COUNT(*) FILTER (WHERE cycle_time_hours > 24) / COUNT(*), 2)
                                                                    AS pct_over_24h,
    ROUND(AVG(customer_satisfaction)::numeric, 2)                    AS mean_satisfaction
FROM v_case_metrics
GROUP BY priority
ORDER BY mean_cycle_hours DESC;


-- Where the elapsed time actually sits ---------------------------------------
-- Absolute hours are the decision-relevant view: the three states below hold
-- ~73% of all process time.
SELECT
    from_event,
    ROUND(SUM(duration_hours), 0)                                    AS total_hours,
    ROUND(100.0 * SUM(duration_hours) / SUM(SUM(duration_hours)) OVER (), 1)
                                                                    AS pct_of_all_time,
    ROUND(AVG(duration_hours)::numeric, 3)                          AS mean_hours,
    COUNT(DISTINCT case_id)                                          AS cases
FROM v_transition_metrics
GROUP BY from_event
ORDER BY total_hours DESC;


-- The 10 slowest incidents ---------------------------------------------------
SELECT
    case_id,
    variant,
    issue_type,
    priority,
    event_count,
    ROUND(cycle_time_hours::numeric, 2)                             AS cycle_time_hours,
    ROUND((max_step_seconds / 3600.0)::numeric, 2)                  AS worst_step_hours,
    customer_satisfaction
FROM v_case_metrics
ORDER BY cycle_time_seconds DESC
LIMIT 10;