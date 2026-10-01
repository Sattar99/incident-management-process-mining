WITH RankedEvents AS (
    SELECT
        *,
        LAG("timestamp", 1) OVER (PARTITION BY "case_id" ORDER BY "timestamp") as previous_timestamp,
        "event" as current_event
    FROM
        incident_data
),
EventDurations AS (
    SELECT
        current_event,
        EXTRACT(EPOCH FROM ("timestamp" - previous_timestamp)) AS duration_seconds
    FROM
        RankedEvents
    WHERE
        previous_timestamp IS NOT NULL
)
SELECT
    current_event AS bottleneck_event,
    ROUND(AVG(duration_seconds), 2) AS average_duration_seconds,
    COUNT(*) AS event_count
FROM
    EventDurations
GROUP BY
    current_event
ORDER BY
    average_duration_seconds DESC
LIMIT 3;
