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
- The text is read once per backend process (`@cache` on `_recipes_text()` and `_reference_text()`).

## Updating a file

1. **Edit the markdown.** Keep it short; the whole file is returned in one tool result and then sits
   in the conversation for the rest of the turn. There is a size cap on tool output, and anything over
   it is truncated with a marker, so do not let a file grow past a few thousand words.
2. **Verify every step id and field you mention** against the current registry:
   - ids and display names: `grep -n "^  - id:" backend/workflow_steps/registry.yaml`
   - fields, outcomes, capabilities: `get_step_schema` in a chat, or the step's entry in
     `registry.yaml`.
   A stale recipe is worse than none, because the model will follow it with confidence.
3. **Restart the backend.** The dev server auto-reloads on `.py` changes only, so a markdown edit
   alone does not reload it. Stop and start `python start.py`, or touch a `.py` file in the backend.
   The Hatchet workers do not read these files.
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
2. In the matching tools module, load it with `Path(...)` and `@cache` like `_recipes_text()`, add an
   async function returning `ToolOutput(text)`, and register a `Tool("name", "description", NoInput,
   fn)` in the surface's tool tuple (for example `WORKFLOW_EDITOR_TOOLS`).
3. Mention it in the surface prompt in `prompts.py` if the model should read it proactively.
4. Add the friendly label to the tool-name map in
   `frontend/src/components/features/ai-assistant/components/assistant-panel.tsx`.
5. Add the tool to the expected set in `tests/unit/test_ai_workflow_tools.py` (or the matching test
   module) and document it in `doc/ai_integration/AI_ASSISTANT.md` (tool tables in §3.5 and §11).

A tool must be a pure read or a proposal; anything else does not ship in this feature.

## Deployment note

The files are read from disk at runtime, relative to the module. They must be present in the backend
image or checkout, and are not in the frontend. Nothing needs to be built or migrated when they change.
