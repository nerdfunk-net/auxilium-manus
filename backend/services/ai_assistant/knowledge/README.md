# AI assistant knowledge files

This directory holds the curated markdown the in-app AI assistant can read. The files are plain
text: no build step, no database, no registry. Editing a file and restarting the backend is enough
to change what the assistant knows.

Background: `doc/ai_integration/AI_ASSISTANT.md` (design) and the section "In-app AI assistant" in
`doc/ARCHITECTURAL_OVERVIEW.md` (how a chat turn works).

## What is in here

| File | Tool that returns it | Surface | Purpose |
|------|----------------------|---------|---------|
| `template_reference.md` | `get_template_reference` | Template editor | Jinja2 syntax and what `device`, `nautobot`, `commands`, `parsed.*` and `run_input` contain |
| `workflow_reference.md` | `get_workflow_reference` | Workflow builder | **Rules**: plan format, outcomes, capability flow, fan-out/fan-in, static attributes, references, secrets |
| `inventory_reference.md` | `get_inventory_reference` | Inventory page | **Rules and recipes** for writing an inventory filter: fields, operators per field, value formats, AND/OR/negate, location semantics |
| `workflow_recipes.md` | `get_workflow_recipes` | Workflow builder | **Recipes**: which steps and wiring a recurring request phrase usually means, plus silent-failure pitfalls |
| `wiki_notes_template.md` | `get_wiki_template` | Workflow builder (with `workflows:write`, saved workflow) | The wiki structure (Purpose / Assumptions / Gotchas / Example), how to fill it from the canvas, a finished example. Keep in line with `doc/HOWTO_BUILD_WORKFLOWS.md` "Documenting the workflow" |

Rule of thumb for where new text goes:

- "How the workflow system works" (a rule that is always true) -> `workflow_reference.md`.
- "When the user says X, build Y" or "this wiring fails silently" -> `workflow_recipes.md`.
- "What does field F of step S do" -> **neither**. That belongs in the step's `description` /
  `overview` / config field descriptions in `backend/workflow_steps/registry.yaml`, which the
  assistant reads live through `list_steps` and `get_step_schema`. Fixing it there helps the
  assistant, the UI and the external AI collaboration at once.

## How a file reaches the model

The model does not see these files by default. The flow is:

1. The app sends the model a list of tools, including `get_workflow_recipes` and its description.
2. The system prompt (`WORKFLOW_EDITOR_PROMPT` in `services/ai_assistant/prompts.py`) tells the model
   to read the recipes when a request resembles a common task.
3. The model asks for the tool; the app runs it (`_get_recipes` in
   `services/ai_assistant/tools/workflow_tools.py`) and returns the file's text as the tool result.
4. The model reads it and continues.

Consequences:

- A file is only paid for (in tokens) on turns where the model asks for it.
- The model decides *whether* to read it, guided by the tool description and the prompt. If a recipe
  is never applied, check that the tool description still mentions the topic (see "If the assistant
  ignores a recipe" below).
- The text is read through `services/ai_assistant/knowledge_loader.py::load_knowledge`, which caches by file
  modification time: an edit is live on the next tool call, no restart needed.

## Updating a file

1. **Edit the markdown.** Keep it short; the whole file is returned in one tool result and then sits
   in the conversation for the rest of the turn. There is a size cap on tool output, and anything over
   it is truncated with a marker, so do not let a file grow past a few thousand words.
2. **Verify every step id and field you mention** against the current registry:
   - ids and display names: `grep -n "^  - id:" backend/workflow_steps/registry.yaml`
   - fields, outcomes, capabilities: `get_step_schema` in a chat, or the step's entry in
     `registry.yaml`.
   A stale recipe is worse than none, because the model will follow it with confidence.
3. **No restart needed.** `load_knowledge` re-reads a file when its modification time changes. The Hatchet
   workers do not read these files.
4. **Try it** in the workflow builder: open the AI Assistant panel, ask for something the recipe
   covers, and check that a "Reading the workflow recipes" chip appears and the proposal follows it.
5. **Run the tests:** `cd backend && python -m pytest tests/unit/test_ai_workflow_tools.py --no-cov`.
   The test asserts that the recipes tool returns the file and that `device_already_exists` is in it.
   If you rename or remove that recipe, update the assertion.
6. **Keep the twin in sync** (next section), then commit both files together.

## Keeping `AI_VOCABULARY.md` in sync

`doc/ai_collaboration/AI_VOCABULARY.md` is the same idea for the *external* AI coding session that
drives `backend/scripts/ai_*_apply.py` from the host. The two files overlap on purpose but are
maintained separately, because they differ in mechanics:

| | `workflow_recipes.md` (in-app) | `AI_VOCABULARY.md` (external) |
|---|---|---|
| Finds an inventory with | `list_references(kind="inventories")` | a script using `InventoryService.get_inventory_by_name` |
| Counts devices for fan-out | cannot; asks the user | `count_inventory_devices(...)` |
| Applies a change with | a proposal the user reviews and applies | `ai_workflow_apply.py` after stating the plan in chat |
| Has an aliases table | no | yes (empty today) |

When a *mapping or wiring convention* is confirmed or corrected, update both. When a change only
concerns one mechanic (a script, a tool), update only that file.

## Recipe or alias?

- A **recipe** (this directory, reviewed in git) says how steps are wired or why a wiring fails
  silently. It is product knowledge and holds for every installation.
- A **step alias** (Settings -> AI Assistant -> Assistant glossary, tab "Workflow step aliases")
  maps one organisation-specific word to one step id, for example "Get from GIT" ->
  `get-git-devices` ("Get from Git"). The assistant looks it up with `get_glossary` when
  `list_steps` finds nothing; it can never carry wiring or config. Record a nickname there, not in
  `workflow_recipes.md` and not in the aliases table of `AI_VOCABULARY.md` (that table remains for the
  external AI session).

## What makes a good recipe

A recipe records something the model cannot work out from the registry alone. Use this shape:

```
### "the phrase the user says" / "a variant of it"
One or more steps, each as display name plus registry id: "Get from Nautobot (`get-nautobot-devices`)".
- The config that matters and where each value comes from (a tool, not a guess).
- The wiring: which outcome leads to which step.
- The reason, when a mistake fails silently or looks plausible.
- What to tell the user (an unwired outcome that is deliberate, an extra step that was added).
```

Add a recipe when:

- the assistant proposed a wrong interpretation of a phrase and you corrected it, or
- you confirmed an interpretation that was not obvious, or
- a workflow failed silently (no validation error, wrong or empty result) because of a wiring detail.

Do **not**:

- record guesses. Only confirmed mappings go in; an unconfirmed phrase should be proposed in chat and
  confirmed first.
- copy the registry (step schemas, the id/name table). It goes stale; `get_step_schema` is live.
- write instructions that belong to the external path (`ai_workflow_apply.py`, "state the plan in
  chat before applying"). The in-app flow has diff review instead.
- put secrets, real hostnames or customer data in examples. Use placeholders such as `NAME`, `DEVICE`.
- include anything the assistant must not see (device or run data). These files are class A
  (definitions) and are sent to the provider as is.

Always cite steps with both display name and registry id; this is a standing rule in this project and
the assistant is told to do the same.

## If the assistant ignores a recipe

Work from the cheapest cause to the most expensive:

1. **Was the file loaded?** The tool chip "Reading the workflow recipes" should appear in the panel
   during the turn. If not, the model decided the request did not match.
2. **Strengthen the trigger.** The model chooses from the tool description in
   `WORKFLOW_EDITOR_TOOLS` (`workflow_tools.py`) and the sentence in `WORKFLOW_EDITOR_PROMPT`
   (`prompts.py`). Add the missing topic to the description, for example a new recipe family.
3. **Was it read but not followed?** Make the recipe more explicit: put the phrase in its heading
   exactly as users write it, and state the concrete config values.
4. **Smaller models follow long files less reliably.** If the file has grown, split rarely used
   recipes out or trim prose. Providers are treated equally in this app, so do not add
   model-specific text.

## Adding a new knowledge file or tool

1. Add the markdown file here.
2. In the matching tools module, load it with `load_knowledge("<file name without .md>")` (never build a
   path yourself), add an async function returning `ToolOutput(text)`, and register a `Tool("name", "description", NoInput,
   fn)` in the surface's tool tuple (for example `WORKFLOW_EDITOR_TOOLS`).
3. Mention it in the surface prompt in `prompts.py` if the model should read it proactively.
4. Add the friendly label to the tool-name map in
   `frontend/src/components/features/ai-assistant/components/assistant-panel.tsx`.
5. Add the tool to the expected set in `tests/unit/test_ai_workflow_tools.py` (or the matching test
   module) and document it in `doc/ai_integration/AI_ASSISTANT.md` (tool tables in §3.5 and §11).

A tool must be a pure read or a proposal; anything else does not ship in this feature.

## Local additions and local playbooks (operators)

Nothing here needs a code change or a new image. Both locations live on the data volume
(`${DATA_DIRECTORY}`, `/app/data` in Docker, created by `docker/start.sh`); a missing directory is empty.

| What | Where | Effect |
|------|-------|--------|
| Addition to a reference file | `${DATA_DIRECTORY}/ai/knowledge/<name>.local.md`, where `<name>` is `inventory_reference`, `template_reference`, `workflow_reference` or `workflow_recipes` | Placed **first**, under "Local additions", in what the matching tool returns (at most 8,000 characters; the whole answer is capped at 20,000, and if the built-in text no longer fits its tail is cut with a marker, so site rules are never the part that is lost) |
| Playbook | `${DATA_DIRECTORY}/ai/playbooks/<name>.md` | Offered by `list_playbooks` / `get_playbook` on Ask the Net. Same name as a built-in one: the local file wins. `disabled: true` (with just `name`) hides a built-in one |

Local files are edited by whoever can write to the data volume; they are not user input. They must be regular
files: a symlink or a FIFO is refused (and logged), and the text must be valid UTF-8. Everything in them
is sent to the AI provider when the model reads it: **no credentials, secrets or customer data**. A local
playbook has `data_class: B` unless it says `A`, so a user who has not shared inventory data does not get it. **`data_class: A`
turns that gate off**: the text is offered to every user and sent to the provider, and the model is told to
follow it (`check_playbooks.py` prints a note for each such file). A knowledge overlay has no data class at
all and is always shown, so keep both free of anything that should not reach every user.

Operator facts, such as which git repository holds the production config backups or that backups run
nightly, belong in a local playbook (or a `.local.md` addition), not in a built-in one. Built-in playbooks
never contain repository names or paths; where a config backup lives is the repository's config path
template (Settings -> Git Repositories).

Playbook format (`playbooks/target-unreachable.md` is the model to copy; files starting with `_` are ignored):

```
---
name: my-playbook            # lowercase slug, equals the file name
title: One line
when: "phrases that should make the model pick it"
tools: [get_routes, ...]     # exact tool names of the general surface
scope: read-only
data_class: B                # optional: A or B (local default B, built-in A)
---
## Steps
1. ...
```

Rules the loader enforces: all front matter fields above; every tool named in `tools` exists; a tool-like word
(`get_...`, `list_...`, ..., with or without backticks) in the text is a real tool and also listed in `tools`; a `## Steps` heading; no configuration command in the text
(a command at the start of a line or in backticks: `conf t`, `reload`, `write memory`, `copy running-config ...`,
`commit`, `clear ip bgp`, ...; the title and `when` are checked too, and prose that only mentions a word such as
"the device was reloaded" is fine); at most 16,000 characters and 100 files per
directory. An invalid local file is ignored (the built-in playbook of that name keeps working) and logged.
Check an edit before relying on it, from `backend/`: `python scripts/check_playbooks.py` (add `--dir PATH` to
check another local directory). Edits are live without a restart.

## Deployment note

The files are read from disk at runtime, relative to the module. They must be present in the backend
image or checkout, and are not in the frontend. Nothing needs to be built or migrated when they change.
