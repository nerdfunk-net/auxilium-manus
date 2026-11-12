# Wiki notes: the template and how to fill it

The wiki of a workflow is Markdown that humans and the AI collaboration read to learn what a
workflow is for before they reuse it. Every workflow uses the same structure, so a reader knows
where to look. Write the notes from the canvas in <canvas_state> and from the step schemas
(get_step_schema); never from guesses.

## Structure

```markdown
# <Workflow Name>

## Purpose
One or two sentences: what problem this solves and when to use it instead of another workflow.

## Assumptions / prerequisites
* credentials: <names>
* inventory: <name>
* git repository: <name or role>
* nautobot: <source>

## Gotchas
Anything destructive, irreversible or order-dependent that the canvas does not make obvious.

## Example
A worked input/output case, only if there is a natural one.
```

## How to fill each section

- **Title**: the workflow name from <canvas_state>.
- **Purpose**: describe what the steps do end to end, in the order they run (data in, what is
  changed or written, what is reported). Mention notifications and statistics if steps do them.
- **Assumptions / prerequisites**: list what must exist, by NAME. Resolve credential, inventory,
  git repository and source ids with list_references (ids mean nothing to a reader). Use one bullet
  per kind, as in the structure above. Add Nautobot data the workflow expects (locations, roles,
  custom fields) when the steps filter on them. Skip a bullet that does not apply.
- **Gotchas**: look for fan-out (which step starts it) and where fan-in ends it, steps that write
  to devices or git (commit/push flags, branches, `commit_after_write`, `push_after_write`),
  removal or overwrite of config, steps that must run before others, run inputs that must be
  filled, and "stop here" steps. Write "nothing destructive" only after checking the steps.
- **Example**: for a backup-style workflow, name one concrete device and the files or commit it
  produces; for a check, one pass and one fail case. Use generic names (`LAB`, `Hamburg`), not
  real addresses.
- Name steps with display name and registry id, for example `Git Push (git-push)`.
- Omit a section that would be empty. Short, true notes beat long ones.

## Rules

- Never write credentials, tokens or IP addresses into notes. Reference credentials by name.
  Keep any __SECRET_n__ / __ADDR_n__ token that already stands in the current notes.
- Change only what the user asked for. When notes exist, keep the sections and wording that are
  still true, update what the canvas no longer matches, and add missing sections.
- Propose the COMPLETE notes with propose_workflow_notes; the user sees a diff and saves it.

## Example (a finished wiki)

```markdown
# Get Backups

## Purpose
This workflow downloads the running and startup configs from the devices, pulls the repository,
writes the configs to the repo and pushes them to git. It collects statistical data and sends
notifications if a backup fails or at the end of the workflow.

## Assumptions / prerequisites
* credentials: 'cisco - noc' credentials
* inventory: 'Full lab env'
* git repository: the configured git repo for device configs
* nautobot: the default nautobot source

## Gotchas
Nothing destructive; fan-out is used in the "Get from Nautobot" step. Fan-in is used before
pulling the git repo.

## Example
For a device named `LAB` at Nautobot location `Hamburg`, this workflow writes:

    configs/Hamburg/LAB.running.cfg
    configs/Hamburg/LAB.startup.cfg

into git repository 'device-configs', one commit per run (`git-push`'s
`commit_message_template`: `"Backup of {timestamp}"`); `git-pull` first fast-forwards the local
working tree to the remote tip. For N devices that is 2xN files but exactly one commit and push
(both `store-artifact` nodes have `commit_after_write` / `push_after_write: false`; only the
trailing `Git Push` step commits, over the whole merged set of files).
```
