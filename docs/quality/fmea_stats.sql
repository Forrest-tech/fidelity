-- Run failure rate for the failure-mode table (docs/quality/FMEA.md). SQLite: data/trust.db.
SELECT date(created_at, 'unixepoch', 'localtime') AS day,
       count(*) AS runs,
       sum(status IN ('error', 'interrupted')) AS failed,
       round(100.0 * sum(status IN ('error', 'interrupted')) / count(*), 1) AS failed_pct
FROM job
GROUP BY day
ORDER BY day;
