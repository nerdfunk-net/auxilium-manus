# Schedules

The **Schedules** app (`/schedules`, sidebar entry gated on `workflows:execute`)
runs a workflow on a timer with per-schedule parameters — chiefly *which
inventory* and *which SSH credential*. One workflow definition can back many
schedules (e.g. one per site), so you no longer copy a workflow ten times to
back up ten locations.

This complements `doc/ARCHITECTURAL_OVERVIEW.md` → "Scheduling" (the Hatchet
registration/firing mechanics, unchanged) and `doc/WORKFLOW-STEPS.md` →
"Static attributes" (the `reference` parameter type). Read those for the parts
this doc doesn't repeat.

## Data model

`WorkflowSchedule` (`backend/core/models/schedules.py`):

- `workflow_id` — plain indexed FK, **not** `UNIQUE`. Many schedules per
  workflow.
- `name` — operator label, unique only by convention.
- `run_inputs` — JSON `{attr_name: value}`, this schedule's static-attribute
  values.
- `created_by_id` — the "run as" user. `scheduled_trigger.dispatch` sets the
  run's `triggered_by_id` from it, so credential/inventory resolution is scoped
  to this user.
- `schedule_type` / `cron_expression` / `run_at` / `enabled` / `hatchet_*_id` —
  as before.

> **Migration note.** The legacy `UNIQUE (workflow_id)` constraint must be
> dropped by a one-off `ALTER TABLE workflow_schedules DROP CONSTRAINT <name>`
> (`\d workflow_schedules` in psql to find the exact name — typically
> `workflow_schedules_workflow_id_key`). `AutoSchemaMigration` adds the new
> `name` / `run_inputs` columns automatically on startup but does **not** drop
> constraints.

## API — `backend/routers/workflow_schedules.py`

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/api/schedules?workflow_id=` | `workflows:execute` | all schedules on workflows the user can see |
| POST | `/api/schedules` | `workflows:execute` **+ `workflows:publish`** | also publishes the workflow to the background tier |
| GET/PUT/DELETE | `/api/schedules/{id}` | `workflows:execute` | |

`ScheduleService` (`backend/services/execution/schedule_service.py`) keys CRUD
by schedule id, validates `run_inputs` against the workflow's
`static_attributes` (`resolve_run_inputs` for shape + `validate_reference_inputs`
for existence/access, scoped to `created_by_id`), and registers each schedule
with Hatchet under `cron_name = f"workflow-{workflow_id}-schedule-{schedule_id}"`.

## Overlap protection = background tier

Creating a schedule calls `BackgroundTierService.publish(workflow_id,
concurrency_limit)` (limit from the editor dialog, **default 1**). With
`concurrency_limit: 1`, a fire that lands while the previous run is still
draining is queued by Hatchet instead of starting a second, overlapping device
fan-out. This is why `POST /api/schedules` needs `workflows:publish`, and why
publishing takes effect only after the dynamic worker restarts (see
`doc/ARCHITECTURAL_OVERVIEW.md` → "Background-tier workflows").

Editing a schedule's concurrency limit re-publishes (idempotent). Deleting the
last schedule does **not** unpublish — that's a separate explicit action in the
workflow builder's Properties panel.

## Making a workflow schedulable with dynamic inventory + credential

1. In the workflow builder → Properties (nothing selected) → **Run parameters**,
   declare two `reference` attributes, e.g. `target_inventory`
   (`ref_kind: inventory`) and `ssh_creds` (`ref_kind: credential`).
2. On `get-nautobot-devices`, set **Inventory source: from run parameter** and
   point it at `target_inventory`.
3. On each SSH step (`get-device-configs`, `run-command`,
   `deploy-rendered-template`, `login-successful`, `upload-config`,
   `add-pyats-testbed`), set **Credential: from run parameter** → `ssh_creds`.
4. Save the workflow.
5. In the Schedules app, create one schedule per site: pick the workflow, pick
   the inventory and credential in **Parameters**, set the timer, save.

## Frontend

- Route stub: `frontend/src/app/(dashboard)/schedules/page.tsx`.
- Feature: `frontend/src/components/features/schedules/` —
  `schedules-page.tsx` (list + enable toggle + delete), `dialogs/schedule-editor-dialog.tsx`
  (workflow picker → `ScheduleParameterFields` → `ScheduleTimingFields` +
  concurrency limit), hooks `use-schedules-query.ts` / `use-schedule-mutations.ts`.
- Reuses `useSavedInventoriesQuery`, `useCredentialsQuery` (filtered to
  `type === "ssh"`), and `workflows/utils/schedule-cron.ts`.
- The old in-builder `WorkflowSchedulePanel` (one schedule, no parameters) was
  removed; `WorkflowStaticAttributesPanel` stays — it *declares* the parameters
  the Schedules app then *fills*.
