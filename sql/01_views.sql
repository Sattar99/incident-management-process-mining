-- Shared metric definitions for the Incident Management process-mining model.
--
-- TIMING METHODOLOGY (corrected)
-- The previous analysis attributed a wait to the event that FOLLOWED it, using
-- LAG(timestamp). That labels "time spent in WIP - level 1 support" as the cost
-- of "Level 1 escalates to level 2 support". Process mining measures the time
-- spent IN a state as the interval from that state to the NEXT event, so the
-- attribution below is deliberately forward-looking.
--
--   step_seconds       = time from an event to the next event in the same case
--   cycle_time_seconds = last event timestamp - first event timestamp
--
-- These views are the contract every downstream metric is built on.

DROP VIEW IF EXISTS v_case_metrics;
CREATE VIEW v_case_metrics AS
WITH ordered AS (
    SELECT
        event_id,
        case_id,
        variant,
        priority,
        reporter,
        event_timestamp,
        event,
        issue_type,
        resolver,
        report_channel,
        customer_satisfaction,
        EXTRACT(EPOCH FROM (event_timestamp - LAG(event_timestamp) OVER (
            PARTITION BY case_id ORDER BY event_timestamp
        ))) AS step_seconds
    FROM incident_data
)
SELECT
    case_id,
    variant,
    priority,
    reporter,
    issue_type,
    report_channel,
    customer_satisfaction,
    COUNT(*)                                            AS event_count,
    COUNT(DISTINCT event)                               AS unique_events,
    COUNT(DISTINCT resolver)                            AS unique_resolvers,
    MIN(event_timestamp)                                AS started_at,
    MAX(event_timestamp)                                AS ended_at,
    EXTRACT(EPOCH FROM (MAX(event_timestamp) - MIN(event_timestamp)))
                                                        AS cycle_time_seconds,
    ROUND((EXTRACT(EPOCH FROM (MAX(event_timestamp) - MIN(event_timestamp))) / 3600.0)::numeric, 4)
                                                        AS cycle_time_hours,
    ROUND(AVG(step_seconds)::numeric, 2)                AS mean_step_seconds,
    MAX(step_seconds)                                   AS max_step_seconds,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY step_seconds)
                                                        AS median_step_seconds,
    BOOL_OR(event ILIKE '%escalat%')                    AS escalated,
    BOOL_OR(event ILIKE '%level 3%')                    AS reached_level_3,
    BOOL_OR(event ILIKE '%closed%')                     AS is_completed
FROM ordered
GROUP BY case_id, variant, priority, reporter, issue_type,
         report_channel, customer_satisfaction;


-- One row per observed transition (A -> B), with the time spent in A.
DROP VIEW IF EXISTS v_transition_metrics;
CREATE VIEW v_transition_metrics AS
WITH ordered AS (
    SELECT
        case_id,
        variant,
        issue_type,
        priority,
        report_channel,
        event_timestamp,
        event,
        LEAD(event) OVER (
            PARTITION BY case_id ORDER BY event_timestamp
        ) AS next_event,
        LEAD(event_timestamp) OVER (
            PARTITION BY case_id ORDER BY event_timestamp
        ) AS next_timestamp
    FROM incident_data
)
SELECT
    case_id,
    variant,
    issue_type,
    priority,
    report_channel,
    event                                        AS from_event,
    next_event                                   AS to_event,
    event || ' -> ' || next_event                AS transition,
    event_timestamp                              AS from_timestamp,
    next_timestamp                               AS to_timestamp,
    EXTRACT(EPOCH FROM (next_timestamp - event_timestamp)) AS duration_seconds,
    ROUND((EXTRACT(EPOCH FROM (next_timestamp - event_timestamp)) / 3600.0)::numeric, 4)
                                                    AS duration_hours
FROM ordered
WHERE next_event IS NOT NULL
  AND event IS NOT NULL            -- 1 source row (INC0305) has a NULL event name
  AND next_timestamp >= event_timestamp;   -- guards against clock skew / out-of-order data