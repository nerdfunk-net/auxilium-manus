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
| POST | `/api/schedules/{id}/run` | `workflows:execute` (rate limited, 10/min per user) | "Run now": see below |

**Run now.** `ScheduleService.run_now` (through the dispatch breaker, so an engine outage fails fast) starts the schedule's workflow once through the same
`services/execution/schedule_fire.py::start_scheduled_run` the Hatchet trigger uses (pre-run
validation, the schedule's stored `run_inputs`, `trigger_type="scheduled"`). Differences from a
fire: only the schedule's **creator (or an administrator, logged)** may click it, because the stored
inputs carry the creator's sealed secrets; the run belongs to the user who clicked (references
resolve for them), the schedule is left untouched (`last_triggered_at` stays, a
one-time schedule is not consumed) and a disabled schedule can still be run. A run that cannot start
is stored as `failed` and the response says so (`status`, `error_message`).

Ownership: a schedule fires as its creator and only the creator (or an administrator, logged)
edits, disables, deletes or runs it. At every fire `hatchet/workflows/scheduled_trigger.py` re-validates
that the creator is active, still holds `workflows:execute` and can still see the workflow; otherwise
the schedule is disabled instead of run. Deactivating a user disables, and deleting a user deletes,
their schedules.

`ScheduleService` (`backend/services/execution/schedule_service.py`) keys CRUD
by schedule id, validates `run_inputs` against the workflow's
`static_attributes` (`resolve_run_inputs` for shape + `validate_reference_inputs`
for existence/access, scoped to `created_by_id`), and registers each schedule
with Hatchet under `cron_name = f"workflow-{workflow_id}-schedule-{schedule_id}"` (an edit registers
the new entry under the same name plus a short random suffix).

Registration is all-or-nothing. A create stores the row disabled, registers with Hatchet and only then
enables it; if registration fails the row is removed again, so nothing half-created remains, and the
background-tier publish that the call performed is undone as well (a tier it created is removed; one that
already existed stays, with its previous concurrency limit). When the engine cannot be reached (a transport
error or a 5xx from Hatchet) the API answers `503` "The workflow execution engine is unavailable", the same
as a manual trigger; a 4xx from Hatchet stays a `500`. An edit
registers the new Hatchet entry first and removes the old one afterwards; if registration fails the
schedule is stored **disabled** (it cannot fire and the list says so) and the old entry is removed. A
fired one-time schedule keeps its past `run_at`: it can be renamed or have its inputs changed without a
new date; re-enabling it, or changing its timing, needs a future `run_at`. A fire whose run cannot be
dispatched creates a `failed` run (see CF-01), it does not vanish.

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
  `schedules-page.tsx` (list + enable toggle + run now + delete), `dialogs/schedule-editor-dialog.tsx`
  (workflow picker → `ScheduleParameterFields` → `ScheduleTimingFields` +
  concurrency limit), hooks `use-schedules-query.ts` / `use-schedule-mutations.ts`.
- Reuses `useSavedInventoriesQuery`, `useCredentialsQuery` (filtered to
  `type === "ssh"`), and `workflows/utils/schedule-cron.ts`.
- The old in-builder `WorkflowSchedulePanel` (one schedule, no parameters) was
  removed; `WorkflowStaticAttributesPanel` stays — it *declares* the parameters
  the Schedules app then *fills*.
