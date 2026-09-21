# Removing debug mode — deploy note

This release removes the per-node "debug mode" workflow-run feature
(`run_mode` on `WorkflowRun`) in favor of the `stop-here` step, and drops the
now-unused `workflow_runs.run_mode` column from the SQLAlchemy model.

## Why this needs a manual step

`AutoSchemaMigration` (`backend/migrations/auto_schema.py`) applies missing
tables/columns/indexes automatically on every app startup, but it **never
drops** columns or tables on its own — that's a deliberate safety choice
(see `doc/MIGRATION_SYSTEM.md`). Restarting the app alone will not remove the
old `run_mode` column.

Until it's dropped, that column stays `NOT NULL` in Postgres with no
server-side default. Since the new code no longer sets it, every
`INSERT INTO workflow_runs` (i.e. every workflow trigger) will fail with:

```
psycopg.errors.NotNullViolation: null value in column "run_mode" of relation "workflow_runs" violates not-null constraint
```

## Fix: run this once, at deploy time

Local-only (SQLAlchemy ↔ your own Postgres) — no network access required, so
this is safe to run in an air-gapped environment.

1. Back up the database.
2. Deploy/restart with the new backend code.
3. Run once:

   ```bash
   cd backend
   source .venv/bin/activate   # or your prod venv
   python scripts/database/sync.py --migrate --drop-columns --table workflow_runs
   ```

   (Optional first: `python scripts/database/sync.py --table workflow_runs`
   to preview the diff without applying anything — it should report
   `run_mode` as an extra column.)

That's it — after this one run, `workflow_runs.run_mode` is gone and normal
restart-only deploys go back to being fully automatic. This step is only
needed for this release; it doesn't become part of your regular deploy
process — future additive-only schema changes (new tables/columns/indexes)
still apply automatically on startup with no manual action.
