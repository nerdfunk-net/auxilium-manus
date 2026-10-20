# How to Test the Frontend

Three layers, cheapest first. Use all three for a change that touches behaviour, and say in the
summary which ones you actually ran.

| Layer | Finds | Cost |
|---|---|---|
| 1. `tsc` + `eslint` | type errors, hook-dependency mistakes | seconds |
| 2. vitest (unit, hook and component tests) + coverage ratchet | logic bugs, state bugs, regressions | seconds |
| 3. Playwright pass against a real, isolated stack | layout bugs, wiring bugs, permission cases, real network behaviour | 15–30 min |

Layer 2 reads code; layer 3 runs it. Several bugs here were found only in the browser (a dialog whose
buttons overflowed its card, an Import button that was clickable while its checks were still
loading), and several unit-test findings were only *confirmed* there. Don't claim a UI behaviour
you only read from code.

---

## 1. Static checks

From `frontend/`:

```bash
npx tsc --noEmit -p .
npx eslint src          # never pass a directory to Prettier; see CONTRIBUTING.md
```

## 2. Unit, hook and component tests (vitest)

```bash
npm test                              # whole suite, no coverage (fast)
npx vitest run path/to/file.test.tsx  # one file; no coverage, no threshold check
npm run test:coverage                 # whole suite + coverage ratchet (this is what CI runs)
```

**Where tests go.** Next to the code. `*.test.ts` runs in the `node` project, `*.test.tsx` in the
`dom` (jsdom) project, which also registers `src/test/setup-dom.ts` (unmounts after every test;
vitest runs without `globals`, so Testing Library does not do it by itself).

**Ratchet.** `vitest.config.ts` → `coverage.thresholds` fails the run when coverage drops. The
numbers sit just under the measured values. Raise them after a round of new tests; never lower them
to make a run pass. Gaps: `npm run test:coverage`, then rank `coverage/coverage-summary.json` by
uncovered statements (logic files first: hooks and utils).

**Patterns that worked**

- **Hooks:** `renderHook` with `createQueryWrapper()` from `src/test/query-wrapper.tsx` (no retries,
  exposes the client). Mock `@/hooks/use-api` (`useApi: () => ({ apiCall })`) and `@/hooks/use-toast`.
  Assert the endpoint/body, the query keys that get invalidated (`vi.spyOn(client, "invalidateQueries")`),
  the toast, and the failure path.
- **Hooks that own state:** keep the real `useState`/real Zustand store in the harness (as the hook
  does in production) and mock only the network and routing. A mocked setter hides ordering bugs.
- **Orchestrator hooks:** run the real child hooks (variables, Batfish, …) and mock only queries,
  `next/navigation` and the save hook; the effects are the logic under test.
- **Every hook:** add a "returns the same object when nothing changed" test. Mocks that return a
  fresh object or `vi.fn()` per render make it fail for the wrong reason: hoist stable mocks with
  `vi.hoisted`. `useMutation` returns a new object every render, so depend on `mutate` /
  `mutateAsync`, never on the mutation object.
- **Components:** render the real component, mock its hooks and heavy children, and assert behaviour
  (`getByRole`, `getByLabelText`), not markup. Radix `Select` needs pointer APIs jsdom lacks: use
  `vi.mock("@/components/ui/select", () => import("@/test/native-select-mock"))` (a native `<select>` that keeps the
  trigger's `id` and the placeholder). `ResizeObserver` is stubbed in `src/test/setup-dom.ts`. Stub factories inside
  `vi.mock` must come from `await vi.hoisted(...)`, not from a top-level `const`. A page that wires dozens of hooks
  (`workflow-builder-page.tsx`) is tested by stubbing every child and checking only the dialogs the page itself renders.
- **Mutation checks in bulk:** a small script that replaces one pattern, asserts the pattern was found, runs the file's
  tests and restores the source (in a `finally`) is faster and safer than editing by hand. Name equivalent mutants
  (a guard the UI cannot reach, a class name) instead of chasing them.
- **Pure utils:** table-driven edge cases (empty, duplicate, wrong type, `true` where a number is
  expected, a `null` entry), an idempotence/round-trip test, and "does not mutate its input".
- **Layout cannot be tested in jsdom.** Write a behaviour test, and check the layout in layer 3.

**Rules that paid off**

1. Write the test first and watch it fail for the reason you expect. A test that was never red
   proves nothing; most of the bugs found in this way showed up as a red test before any fix.
2. After a fix, **mutation-check** the new test: revert the fix, confirm the test fails, restore.
3. A failing test is a finding, not an annoyance. Check whether the *test* is wrong before touching
   the source (several failures were fixture mistakes), then fix the source in the same change.
4. Do not record a known bug with `it.fails` for longer than one session; fix it or list it in
   `doc/OPEN_TODOS.md`.

---

## 3. Playwright pass against an isolated stack

The user's dev servers (backend 8000, `next dev` 3000, a real Hatchet worker) and their data are
**off limits**. Never kill their PIDs, never write to their database, never let a test reach their
Hatchet engine. Run a throwaway stack instead.

### 3.1 Start the stack

Ports below are examples; check `lsof -nP -iTCP -sTCP:LISTEN` first (8100 is held by an OrbStack
forward on the author's machine). Use a scratch directory outside the repo (`$SCRATCH`).

**Database and Redis.** Postgres and Redis run in Docker (`postgres`, `redis`). Create
`manus_pwtest` with `docker exec -e PGPASSWORD=… postgres psql -U … -d postgres -c "CREATE DATABASE manus_pwtest"`
(credentials from `backend/.env`; read them into variables, do not print them). Use Redis database
5 with its own key prefix.

**Backend** (`$SCRATCH/start_backend.sh`):

```zsh
#!/bin/zsh
ENVF=<repo>/backend/.env
get() { grep -E "^$1=" "$ENVF" | head -1 | cut -d= -f2-; }
q() { python3 -c 'import sys,urllib.parse;print(urllib.parse.quote_plus(sys.argv[1]))' "$1"; }

export ENV=development MANUS_ENV_FILE=/dev/null          # do not read backend/.env
export SECRET_KEY=$(openssl rand -hex 32)                # generated per run; never write a literal key into a file
export DATABASE_HOST=localhost DATABASE_PORT=$(get DATABASE_PORT) DATABASE_NAME=manus_pwtest
export DATABASE_USERNAME=$(get DATABASE_USERNAME) DATABASE_PASSWORD=$(get DATABASE_PASSWORD)
RPW=$(get MANUS_REDIS_PASSWORD)
export MANUS_REDIS_URL="redis://:$(q "$RPW")@localhost:6379/5" MANUS_REDIS_KEY_PREFIX=manus-pwtest
export INITIAL_USERNAME=admin INITIAL_PASSWORD='Playwright-Pass-2026'
export DATA_DIRECTORY=$SCRATCH/data LOG_DIRECTORY=$SCRATCH/data/logs
export BACKEND_HOST=127.0.0.1 BACKEND_PORT=8150
export VAULT_ENABLED=false AI_ASSISTANT_ENABLED=false ENABLE_DEV_TOOLS=false
# Dead Hatchet endpoint: a run can never reach the real engine or worker.
export HATCHET_CLIENT_TOKEN=<fake JWT: header.payload.sig, payload aud/grpc_broadcast_address/server_url = localhost:1>
export HATCHET_CLIENT_HOST_PORT=localhost:1 HATCHET_CLIENT_TLS_STRATEGY=none HATCHET_CLIENT_SERVER_URL=http://localhost:1

mkdir -p $SCRATCH/run && cd $SCRATCH/run                  # a cwd without the user's .env
nohup <repo>/.venv/bin/python -m uvicorn main:app --app-dir <repo>/backend \
  --host 127.0.0.1 --port 8150 > $SCRATCH/backend.log 2>&1 &
echo $! > $SCRATCH/backend.pid
```

Check `curl -s http://127.0.0.1:8150/health/ready`. Runs cannot execute on this stack (no Hatchet);
everything else works.

**Frontend.** A second `next dev` in `frontend/` is refused while the user's server runs, and a
build would overwrite their `.next`. Use a scratch copy:

```bash
rsync -a --delete --exclude node_modules --exclude .next --exclude coverage \
  --exclude '*.test.ts' --exclude '*.test.tsx' <repo>/frontend/ $SCRATCH/fe/
ln -sfn <repo>/frontend/node_modules $SCRATCH/fe/node_modules
cd $SCRATCH/fe && PORT=3150 BACKEND_URL=http://localhost:8150 \
  nohup ./node_modules/.bin/next dev --webpack -p 3150 > $SCRATCH/frontend.log 2>&1 &
echo $! > $SCRATCH/frontend.pid
```

`--webpack` because Turbopack rejects the symlinked `node_modules`. To test a fix, `rsync` the
changed file into the copy; hot reload picks it up.

### 3.2 Users

The seeded `admin` must change its password on first login (a flow worth exercising; the first
`/api/auth/me` 401s on the login page are normal). For a **non-admin** case create a role and user
through the API with a bearer token (`POST /api/auth/login`, `/api/auth/change-password`,
`/api/rbac/roles`, `/api/rbac/roles/{id}/permissions`, `/api/users`, `/api/rbac/users/{id}/roles`).
The `viewer` role is read-only; to test someone who builds workflows but cannot see credentials,
git repositories or sources, grant `workflows:read`, `workflows:write`, `workflow_steps:read`,
`templates:read`, `workflow_runs:read` only. A new user is also forced to change the password.

### 3.3 What to cover

For a builder change, at least:

- Sign-in, forced password change, the builder after a **hard reload**.
- Add steps from the library, **Auto layout**, connect two steps (an incompatible pair must be
  refused with a toast), delete a step and add another (ids must stay unique).
- Save As, leave the page and come back (draft restored), hard reload then File → Open.
- File → Manage → Export, then Import (also a duplicate name, and a file that references a
  credential, git repository or source).
- Save conflict: change the workflow from the page with
  `fetch('/api/proxy/workflows/<id>', {method:'PUT', …})`, make an edit and save; check the dialog
  and each of its choices.
- Multi-select, Align, Group, open the group and add a step inside it.
- The same flows as a **non-admin**. Look at the network log: a request that fails with 403 must not
  be retried, and a dialog must not offer an action the user cannot perform.

Always watch: `browser_console_messages` (errors), `browser_network_requests` with
`filter: "/api/"`, and whether the unsaved marker ("Draft") appears only when something changed.

### 3.4 Playwright tool tips

- Prefer `browser_find`, `browser_evaluate` and CSS selectors over full snapshots (the builder's
  snapshot is huge). Nodes: `[data-id="<node id>"]`; handles:
  `[data-id="…"] .react-flow__handle.source` / `.target`; fit view: `.react-flow__controls-fitview`.
- **Measure layout, do not eyeball it:** compare `getBoundingClientRect()` of a dialog and its
  buttons (`outside: x.right > card.right`). That is how the conflict-dialog overflow was proven.
- Multi-select needs Ctrl/Cmd-click (`modifiers: ["ControlOrMeta"]`); Shift is the selection box.
- Overlapping nodes block clicks: run Auto layout and fit view first. The minimap can cover the
  bottom-right handles at 1200×700; collapse it with `.react-flow__panel.bottom.right button`.
- Screenshots and downloads must land inside the repo, in `.playwright-mcp/` (git-ignored); the
  scratch directory is refused. Exports are downloaded there too, and a file to upload must be
  there as well.
- To check a fix is live, use evidence the old code could not produce (a request count, a measured
  width, a state value), not just "it looks fine".

### 3.5 Clean up

1. `browser_close`.
2. Stop **only your own** processes: `lsof -nP -iTCP:8150 -iTCP:3150 -sTCP:LISTEN`, plus the
   launcher PIDs in `$SCRATCH/*.pid`, with `kill <pid> <pid> …`. In zsh an unquoted `$VAR` is not
   split, so `kill $PIDS` fails; write the numbers out.
3. Confirm the user's servers are still alive (same PIDs on 3000 and 8000). Killing one process can
   take related ones with it.
4. `DROP DATABASE manus_pwtest`; delete the `manus-pwtest*` keys in Redis database 5.
5. Leave nothing behind in the repo except intended changes (`git status`).

---

## 4. Reporting

Report what you ran and what you did **not** run (no workflow execution, no second browser tab,
only one viewport). For each bug: the evidence (request log, measurement, failing test), the cause,
the fix and how it was verified. Things that are a product decision rather than a defect go to the
user as a question; deferred cleanups go to `doc/OPEN_TODOS.md`. Do not commit; the user does.
