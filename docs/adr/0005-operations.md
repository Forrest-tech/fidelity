# ADR 0005: Operations on one Windows machine: keep the job queue, add verified backups, health and a deploy script

Date: 2026-11-22. Status: accepted (requirements v2, phase D).

## Options scored

| Option | Score | Why |
|---|---|---|
| Replace the job queue with Celery / Dramatiq / Procrastinate | 6.0 | Each needs Redis, RabbitMQ or PostgreSQL. None runs well on the 4 GB Windows VM (RabbitMQ was blocked). The current queue in `jobs/queue.py` already has leases, heartbeats, capacity points and takeover after a restart; that takeover was exercised live six times on 2026-11-22. Revisit on the Mac mini or server, together with PostgreSQL. |
| One-command deploy with checks, a health test and automatic rollback (`deploy/windows/deploy.ps1`) | 9.6 | Replaces manual steps that had already gone wrong: missing Python packages after a merge, slow restarts mistaken for failures, and a checkout left on a feature branch. |
| Daily backups, verified by restoring them (`app/ops/backup.py`) | 9.4 | There were none. SQLite's online backup API gives a consistent copy while the server writes; restoring each copy and running `PRAGMA integrity_check` proves it usable. |
| Health page, Prometheus text metrics and alerts in the bell (`app/ops/health.py`) | 9.5 | Free disk, memory, failed runs and backup age were invisible until something broke. They are now measured every 30 seconds and raised to administrators. |

## Decisions

- **Backups** go to `data/backups/fidelity-<time>.zip`. Each one is checked on creation, one is made per day, and the newest 14 are kept. Setting `FIDELITY_BACKUP_COPY_DIR` (a folder on another disk or a synced cloud folder) adds a copy elsewhere. The zips contain the Dropbox and AI keys, so they stay on this machine or in an administrators-only folder.
- **Alerts:**
  - free disk below 3 GB (warning) or below 1.5 GB (act now);
  - free memory below 500 MB;
  - no backup at all, a backup that failed to verify, or no backup for 36 hours;
  - at least 3 runs, and at least 20% of the runs in the last 7 days, failed.
- **Metrics** are served at `GET /api/v1/system/metrics` in Prometheus text format, behind administrator sign-in. No client library is needed for these gauges.
