# Reports

The Reports app summarizes data that workflows collected across **all devices**. A workflow
runs per device, so nothing else sees the whole fleet: a **Store for Report** step writes small
facts per device into the database, and the Reports app queries them.

Status: **phases 1-4** (catalog, query engine, Explore tab, saved reports and stored snapshots, AI assistant,
report templates, PDF export and email). Planned: nothing fixed; see `doc/plans/REPORT_APP.md` for open items. The full plan,
status and next steps are in `doc/plans/REPORT_APP.md`.

## Data model

| Table | Purpose |
|-------|---------|
| `report_data_records` | Append-only facts. One row per device (device datasets) or per list element (item datasets). `data` is JSONB with flat scalar values. |
| `report_definitions` | Saved reports: unique `name`, `description`, `sections` JSONB (list of `ReportSection`: `id`, `title`, `query`, `presentation` table/number/bar/line, `text`), `created_by`. |
| `report_snapshots` | Immutable generated copies: `definition_id` (set to NULL when the report is deleted), `name`, `generated_by` (username), `status` complete/partial, `content` JSONB (the definition copy plus each section's result or error). |
| `report_datasets` | Catalog: one row per dataset with its grain (`device` or `items`), field names and last collection time. Written by the Store for Report step after each collection (best effort, never fails the step). |

A **collection** is everything one step execution wrote for one (dataset, device), sharing a
`collection_id`. Reads use the **newest collection per device** (scope `latest`) or every
collection (scope `history`). A collection that found no items is stored as a marker row
(`is_empty`). The marker makes the newest collection win over an older non-empty one, so the old items
disappear from `latest` queries. It is **never returned by a query**, so a report cannot tell "this device
has zero items" from "this device was never collected" (see "Zero items"). The repository methods take
`include_empty=True` to see it; only tests use that.

Field names are lowercase `[a-z][a-z0-9_]{0,63}`. `device_name`, `collected_at` and
`time_bucket` are reserved pseudo-fields.

## Catalog and field types

The catalog says *what exists* (dataset, grain, field names). Field **types** (`string`, `number`,
`boolean`, `mixed`, `unknown`), the share of empty values and a few sample values are inferred
from the newest 200 rows of a dataset each time the catalog is read (`GET .../catalog`). Sample
values are for the UI only; they must never be sent to the AI assistant.

If two steps write the same dataset, the newest write defines its mode and fields. Within one run a *different* step writing the same dataset for the same device fails that device (rows carry `node_id`); the same step writing again replaces its rows.

## Query spec

A query is a declarative JSON object (`models/reports.py::ReportQuery`); there is no free SQL.

| Part | Meaning |
|------|---------|
| `source` | `report_data` (the only source today). Sources implement `describe()` and `run(query)`; see `services/reports/sources/`. |
| `dataset` | A catalog dataset. |
| `scope` | `latest` (default) or `history` with optional `since`, `until` and `bucket` (`day`/`week`). |
| `filters` | AND-ed. Operators: `eq`, `ne`, `in`, `contains`, `gt`, `gte`, `lt`, `lte`, `is_null`, `not_null`. `gt..lte` need a number field, `contains` a text field. `ne` also matches rows where the field is missing. |
| `group_by` + `metrics` | Summary. Metrics: `count`, `count_distinct`, `count_missing`, `sum`, `avg`, `min`, `max` (`sum`/`avg` need a number field), plus the field-less `count_devices` and `count_items`, which also read the empty-collection markers (see "Zero items" below). `time_bucket` may be grouped on in a bucketed history scope. |
| `select` | List mode (no metrics): the columns to return; empty means device name plus all fields. |
| `order_by`, `limit` | Order by an output column; `limit` 1-5000 (default 500). `truncated` is set when more rows matched. |

Filter numbers must be finite and at most 10^15 in size. Values are compared by field type. Field types come from a sample, so on PostgreSQL a number or boolean field is read through a
type guard: a stray value of another type (`"N/A"` in a number field) counts as empty instead of
failing the query. A `mixed` field compares the JSON value, so `10`, `"10"`
and `true` stay distinct.

Examples (see `tests/unit/test_report_query_compiler.py`, `tests/integration/test_reports_pg.py`):

* all serial numbers: `select: [device_name, serial]`
* devices per location: `group_by: [location]`, `metrics: [{op: count, alias: devices}]`
* shutdown interfaces per device (item dataset): filter `status eq disabled`, `group_by: [device_name]`, count
* trend: `scope: {kind: history, bucket: day}`, `group_by: [time_bucket]`, `avg ports`

## API and permissions

`GET /api/reports/sources`, `GET /api/reports/sources/{id}/catalog`,
`POST /api/reports/sources/{id}/query`. All need `reports:read`. The query endpoint is rate
limited (60 per minute and user) and PostgreSQL cancels a query after 15 seconds
(`STATEMENT_TIMEOUT_MS` in `query_compiler.py`; the user gets a 422 saying so); the catalog is
rate limited too (120 per minute), because it samples recent rows of every dataset. Invalid queries answer 422 with the reason; an unknown
source 404. `reports:write` and `reports:delete` guard saved reports (below).

## Reports and snapshots

Endpoints (router `routers/report_definitions.py`, service `services/reports/report_service.py`):

| Endpoint | Permission |
|----------|------------|
| `GET/POST /api/reports/definitions`, `GET/PUT/DELETE .../definitions/{id}` | `reports:read` / `reports:write` / `reports:delete` for delete |
| `POST /api/reports/definitions/{id}/generate` (10 per minute and user) | `reports:write` |
| `GET /api/reports/snapshots[?definition_id=]`, `GET .../snapshots/{id}` | `reports:read` |
| `DELETE /api/reports/snapshots/{id}` | `reports:delete` |

Generating runs each section's query through `ReportQueryService` and stores the result. A section
that fails (bad dataset, timeout, unexpected error) does not fail the report: the snapshot is
`partial` and that section holds an `error` (query errors verbatim, anything else a generic text; the
detail is in the server log). Limits: 20 sections per report, 1000 rows per section
(`SNAPSHOT_ROW_CAP`, `truncated` is set), 8 MB per snapshot (`MAX_SNAPSHOT_BYTES`; a section that no
longer fits is recorded as failed), the newest 50 snapshots per report are kept
(`MAX_SNAPSHOTS_PER_DEFINITION`, older ones are deleted on generate). NaN/Infinity cells are stored as null.
Deleting a report keeps its snapshots. Section queries are only checked statically on save (known
source); the dataset and fields are checked when the report is generated.

## Report templates

A report can name a **report template**: a stored template (Templates feature) of category `report`
that turns a snapshot into Markdown. Without one, the built-in default template is used
(`services/reports/report_renderer.py::DEFAULT_TEMPLATE`: title, description, then every section's
title, text and Markdown table). Set it with `template_id` on the report definition; it must be an
active template of category `report`.

Rules for category `report` (`TemplatesService`): type must be `jinja2`; pre-run commands, Nautobot
attributes, a credential and Batfish options are refused (422). The name is unique across all
templates, as for every category. A template cannot be moved into or out of the category (422), and the two editors redirect
to each other when opened with a template of the other kind.

Rendering happens **once per generated snapshot** and the Markdown is stored in the snapshot
(`content.body`: `template_id`, `template_name`, `markdown`, `error`), so a snapshot never changes
when the template is edited later. It runs in the same killable child process as the template
assistant's trial render (5 s, CPU and memory limits, sandboxed Jinja2) with **strict** undefined
handling: a misspelled variable is an error, shown in the snapshot (`body.error`, status `partial`),
and the section results are kept. If the chosen template was deleted, deactivated or is no longer a report template, the default
template is used and the body carries a notice. Generation waits up to 20 s for a free render slot (the pool of 4 is
shared with the assistant's trial renders) instead of storing "busy"; a rendered text over 1 million characters is an
error, not silently cut.

Variables of a report template:

| Variable | Content |
|----------|---------|
| `report` | `name`, `description`, `generated_at` (ISO 8601), `generated_by` |
| `sections` | dict by section id, for example `sections["per-site"]` (ids may contain `-`, use brackets) |
| `section_list` | the same sections in report order |

Each section has `id`, `title`, `text`, `presentation`, `status` (`ok`/`error`), `error`, `columns`
(`key`, `label`, `type`), `rows` (list of dicts keyed by column key), `row_count`, `truncated`,
`first` (first row or `None`), `value` (first numeric cell of the first row, `None` if there is none) and
`table` (the result as an escaped Markdown table).

Examples: `{{ sections["devices"].value }} devices in total`,
`{% for r in sections["per-site"].rows %}- {{ r.location }}: {{ r.devices }}{% endfor %}`.

### Using report templates in the app

- **Templates** page: filter *All / Device / Report*; **New Report Template** opens
  `/templates/report-editor` (a Jinja2 editor with a variable reference, an AI Assistant and a **Preview**
  that renders the unsaved text against a stored snapshot; `POST /api/reports/snapshots/{id}/preview-template`,
  `reports:read`, 30 per minute). Editing a report template from the list opens the same editor.
  A new template starts from the default template's text.
- **Reports** tab: the report editor has a *Report text template* choice (default or a report template).
- **Snapshots**: a snapshot that has report text opens on a **Report** tab (sanitized Markdown with tables;
  raw HTML and unsafe links are not rendered) next to a **Data** tab with the section tables and charts.
- The *Render Jinja template* workflow step no longer lists report templates.
- The AI template assistant knows the report variables when the editor is in report mode
  (`TemplateEditorContext.category = "report"`); it writes templates from the documented shape and tests with
  `sample_variables`, never with the report's values.

## Frontend

`/reports` (sidebar item "Reports", `reports:read`) has three tabs. **Reports** lists saved reports (create/edit with sections and an editable query per section, generate, delete); **Snapshots** lists and opens stored snapshots; **Explore** is described next and has an "Add to report…" button (`reports:write`). Pick a source and a
dataset, set scope and filters, list rows or summarize, run. Code is in
`frontend/src/components/features/reports/`; the pure query-building logic is
`utils/query-spec.ts`.

## PDF and email

Both start from the Markdown stored in the snapshot (`content.body.markdown`); a snapshot without it (older
snapshots, a broken template) falls back to the default template rendered from the stored section data.

* **PDF** (`services/reports/pdf_renderer.py`): reportlab, pure Python, no system libraries (Docker images
  and the air-gap bundle are unchanged). markdown-it-py parses the Markdown with raw HTML off; headings,
  paragraphs, bold/italic/code, lists, block quotes, code blocks, rules and tables (header repeated on
  every page, column widths by content) are drawn; images are never fetched (alt text is printed), only
  http(s)/mailto links are kept. Font: Bitstream Vera, which ships with reportlab (Latin incl. umlauts, ß, €,
  typographic dashes; other scripts render as boxes). Limits (table cells come from device data):
  1,000,000 characters of Markdown; 1,000 rows per table and 4,000 table rows in total, 16 columns, 1,000
  characters per cell and 400 per code line, with a visible "shortened" note. Layout then stays within a few
  seconds; a layout failure is a 422, not a 500.
  `GET /api/reports/snapshots/{id}/pdf` (`reports:read`, 20/min) downloads it.
* **Mail settings** (global): Settings -> **Mail** (`system.mail:read|write`, admin-grantable only because
  `system.*` is protected): server, port, security (none / STARTTLS / SSL), verify TLS, from address and an
  optional login credential. The credential is a **global `generic`** vault credential chosen by name (private
  credentials never resolve), checked on save; a login over `security: none` is refused. Stored under the
  Settings key `mail.smtp`. **Test connection** (6/min) connects and logs in with the saved settings and sends
  nothing. Code: `services/mail/` (`smtp_sender.py` over aiosmtplib, `mail_service.py`, `mail_settings_service.py`),
  `routers/mail.py`. Failures show only the exception class and SMTP code, never server text. The Send Mail
  workflow step still has its own copy of this logic (not yet switched to the shared sender).
* **Sending** `POST /api/reports/snapshots/{id}/send` (`reports:send`, 10/min): body `to` (1-20 addresses),
  optional `subject` (default: the snapshot name), `message` (note above the report) and `include_pdf`
  (default true). The mail has the Markdown as plain text, an HTML version (images off, raw HTML escaped, only
  safe links) and the PDF attached (limit 15 MB). 409 when mail is not configured or the credential is
  unusable, 502 when SMTP fails, 422 for an invalid request or an oversized PDF.
* **Recipient control:** the mail settings can list **allowed recipient domains** (domains and their
  subdomains; empty allows any). A send to another domain is refused (422) before anything is rendered. Every
  successful send is logged (snapshot, user id, recipient count and domains, never the addresses). Errors shown
  to senders are generic (mail host, port and credential name stay in the log and on the admin-only test
  endpoint). There is no global send budget, only the per-user 10 requests per minute.
* **Trust boundary:** the SMTP host is not restricted (admins only, `system.mail:write`). Whoever can change
  it can point the global login credential at a server of their choice, so grant `system.mail:write` only to
  people who may already use that credential.
* Data values that reach the report text through the default template are Markdown-escaped
  (`[`, `]`, `` ` ``, `*`, `_`, `#`, `!`, `<`, `>`, `|`, `~`, `\`), so a value cannot become a link or heading.
* **Default recipients** are saved on the report (`default_recipients`, at most 20) and proposed in the Send
  dialog; the user can edit them before sending.
* Frontend: a snapshot has **PDF** and **Send by email…** buttons (the latter needs `reports:send`); the report
  editor has *Default recipients*.

## AI assistant

The reports page has an AI Assistant panel (when the assistant is enabled for the user). It always sees the
catalog (dataset, field names, types) and can propose a query, which the user applies to the Explore builder
and runs. It reads query results and snapshot contents only if the user switched on **Report data** under
Settings -> AI Assistant -> Data sent to the model. Details and enforcement: `doc/ai_integration/AI_ASSISTANT.md` §20.

## Zero items

An items dataset stores a device whose list was empty as one marker row. Ordinary metrics skip
markers, so such a device vanishes from `group_by device_name` counts. `count_devices` (distinct
devices, markers included) and `count_items` (items, 0 for a marker) read them: `group_by
device_name` + `count_items` lists every collected device with its item count, zero included. A
plain `count` next to them counts items, not markers. `count_devices` counts every collected device, empty or not, so "how many devices have none" is the number of `count_items = 0` groups in the per-device result. Use scope `latest` (or a time bucket): a history scope without a bucket adds up every past collection. Because a marker has no field values, these
metrics accept only `device_name` / time filters and grouping, and cannot be combined with
field-based metrics; run those as a separate query.

## Known limits

* Field types come from the newest 200 rows; a later stray `"N/A"` in a number field counts as empty.
* `report_data_records` is purged daily by age (`REPORT_DATA_RETENTION_DAYS`, default 365, 0 keeps all) by the `purge_report_data` task of the retention cron; the newest collection of each device and dataset is always kept, so a rarely collected device never disappears from "latest" queries.
* The Send Mail workflow step sends through the shared SMTP sender (`services/mail/smtp_sender.py`) but still resolves its credential as the run's user, while report mail resolves only a global one.

## Database notes

* `report_data_records.data` is `JSONB` on PostgreSQL (`JSON` on SQLite in unit tests). The
  startup schema sync and `scripts/database/sync.py` treat JSON and JSONB as the same type, so an
  existing database created before this change keeps `json` until converted. With the table
  empty (or after checking the data), run:

  ```sql
  ALTER TABLE report_data_records ALTER COLUMN data TYPE jsonb USING data::jsonb;
  ```

* The schema sync never drops indexes. Databases that created the table from an earlier
  version of the model may still hold `uq_report_data_run_dataset_device` (rejects item
  datasets) and `idx_report_data_run_dataset_device`; drop both.
* The latest-collection scan reads a dataset's retained history (bounded by `REPORT_DATA_RETENTION_DAYS`).

## Tests

Unit (SQLite): `test_report_query_compiler.py`, `test_report_sources.py`, `test_reports_router.py`,
`test_report_field_stats.py`, `test_report_datasets_repository.py`, `test_report_service.py`, `test_report_definitions_router.py`, `test_report_definitions_repository.py`. PostgreSQL (needs
`backend/.env.test`): `tests/integration/test_reports_pg.py`, `test_report_data_records_pg.py`, `test_report_definitions_pg.py`.
Frontend: `utils/query-spec.test.ts`, `utils/report-sections.test.ts`, `components/ui/markdown-view.test.tsx`. Report templates: `test_report_renderer.py`, `test_templates_report_category.py` and the template cases in `test_report_service.py` / `test_report_definitions_router.py`. PDF and mail: `test_report_pdf.py`, `test_report_mailer.py`, `test_mail_settings.py`, `test_mail_router.py`.
