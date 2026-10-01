WITH RankedEvents AS (
    SELECT *,
        LAG("timestamp", 1) OVER (PARTITION BY "case_id" ORDER BY "timestamp") as previous_timestamp,
        FIRST_VALUE("timestamp") OVER (PARTITION BY "case_id") as start_timestamp,
        LAST_VALUE("timestamp") OVER (PARTITION BY "case_id" ORDER BY "timestamp" ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) as end_timestamp
    FROM
        incident_data
)
SELECT
    "case_id" AS incident_id,
    "issue type" AS issue_type,
    EXTRACT(EPOCH FROM (end_timestamp - start_timestamp)) AS total_cycle_time_seconds,
    ROUND(AVG(EXTRACT(EPOCH FROM ("timestamp" - previous_timestamp))), 2) AS average_step_duration_seconds,
    COUNT(*) AS total_steps
FROM
    RankedEvents
WHERE
    previous_timestamp IS NOT NULL OR ("timestamp" = start_timestamp)
GROUP BY
    "case_id", "issue_type", start_timestamp, end_timestamp
ORDER BY
    total_cycle_time_seconds DESC
limit 10;
