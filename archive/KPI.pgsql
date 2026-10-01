SELECT
    "issue type" AS issue_type,
    ROUND(AVG(total_cycle_time_seconds), 2) AS average_total_cycle_seconds,
    ROUND(AVG(average_step_duration_seconds), 2) AS avg_step_duration_seconds,
    ROUND(AVG(total_steps), 2) AS avg_total_steps,
    ROUND(MAX(total_cycle_time_seconds), 2) AS max_cycle_seconds
FROM
    ( 
    WITH RankedEvents AS (
        SELECT
            *,
            LAG("timestamp", 1) OVER (PARTITION BY "case_id" ORDER BY "timestamp") as previous_timestamp,
            FIRST_VALUE("timestamp") OVER (PARTITION BY "case_id") as start_timestamp,
            LAST_VALUE("timestamp") OVER (PARTITION BY "case_id" ORDER BY "timestamp" ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) as end_timestamp
        FROM
            incident_data
    )
    SELECT
        "case_id", "issue type",
        EXTRACT(EPOCH FROM (end_timestamp - start_timestamp)) AS total_cycle_time_seconds,
        ROUND(AVG(EXTRACT(EPOCH FROM ("timestamp" - previous_timestamp))), 2) AS average_step_duration_seconds,
        COUNT(*) AS total_steps
    FROM
        RankedEvents
    WHERE
        previous_timestamp IS NOT NULL OR ("timestamp" = start_timestamp)
    GROUP BY
        "case_id", "issue type", start_timestamp, end_timestamp
    ) AS IncidentMetrics
GROUP BY
    issue_type
ORDER BY
    average_total_cycle_seconds DESC;
