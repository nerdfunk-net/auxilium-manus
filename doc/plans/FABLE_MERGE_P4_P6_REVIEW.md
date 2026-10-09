# Review: Phases 4–6 of `FABLE_MERGE_20261009.md`

Reviewed: 2026-10-09, against the uncommitted working tree (not a commit).
Plan: `doc/plans/FABLE_MERGE_20261009.md`. Source findings: `doc/analysis/FABLE_MERGE_20261009.md`.

**Verdict.** Phases 4–6 follow the plan, and the unit tests that cover them pass
(`201 passed, 7 subtests`: secret-manager validation, service, config, registry,
connection service, router, secret-get executor, Batfish client, models, init-snapshot,
validate-facts, query helpers, rate-limit dependency, rate-limited routes, service
factory). Three problems should be fixed before this is treated as done. Phase 4.5
(live Infisical verification) was not run. Phases 7–10 are not in the diff.

---

## What landed

| Phase | Items | In the diff |
|---|---|---|
| 4 | SM5, SM8, SM9, SM11 | Yes. 4.5 (live Infisical check) not run. |
| 5 | B3 row cap, B4, B5, B6, B7, B8 | Yes. Custom networks are refused only when they are another workflow's `manus-workflow-<id>`, as the phase-local decision says. |
| 6 | S9, SM10, B3 limit | Wired on the routes the plan lists. The budget does not hold under a parallel burst (bug 1). |
| 7–10 | W6, W5/S15, S14/R6, Q*, D*, T5 | No. |

SM5 is one validator (`services/secret_manager/validation.py`) used by all three
secret steps and again in `SecretManagerService` on the rendered path. `#`, `%`,
`?`, and empty / `.` / `..` segments are rejected. SM8 moves the synchronous
`httpx` calls onto `asyncio.to_thread` and gives each connection its own lock.
SM9 rejects unknown `backend_config` keys and non-strings, caps names at 255,
and coerces `version` (bool and non-integer floats fail; `0` fails). B4 uses a
per-network lock, an LRU cap of 64, and `load_questions=False` on the list-only
sessions. B8 rejects `question_name` and `exclusions` on the generic query.

---

## Bugs

### 1. The per-user rate limit does not hold under a parallel burst

`rate_limited()` is a plain `def`, so FastAPI runs it on a worker thread. It
calls `LoginRateLimiter.check()`, which counts and records in two Redis calls:

```python
# backend/services/auth/login_rate_limiter.py
def check(self, key: str) -> None:
    self.assert_allowed(key)  # ZCARD
    self.record(key)          # ZADD
```

Requests that arrive together can all see a count under the budget and all
proceed. A user can open far more than 10 SSH sessions, or 30 Batfish queries,
in one burst. Serial traffic is limited. Parallel traffic is not. That is the
case S9 was meant to stop.

When Redis is down, the in-process fallback has the same hole and is also
unsafe across those threads. `_count_fallback` reads `attempts[0]` after a
separate emptiness check:

```python
while attempts and now - attempts[0] > self._window:
    attempts.popleft()
```

Another thread can empty the deque between the check and the index, and the
request becomes a 500. Requests that miss the race are counted only inside
that process, so several API workers multiply the budget. The plan accepted a
per-process fallback. It did not accept a crash, or a burst that skips the
limit.

Count and record need to be one atomic Redis operation (a short Lua script, or
`INCR` with a TTL). The in-process deque needs a lock.

The unit tests drive the limiter one request at a time, with Redis forced
down, so they do not catch this.

### 2. Shutdown can leave a Secret Manager client running

`shutdown_all` copies the client dict and clears it without taking the
per-connection locks:

```python
# backend/services/secret_manager/registry.py
async def shutdown_all(self) -> None:
    cached_clients = list(self._clients.values())
    self._clients.clear()
    self._locks.clear()
    for cached in cached_clients:
        await cached.client.shutdown()
```

`get_or_create` awaits `ensure_started()` while holding that connection's
lock, then inserts the client. A login that is in flight during process
shutdown can put the client back after the snapshot, so its OpenBao
token-renewal task is never stopped. Clearing `_locks` at the same time lets
a second lock be created for the same connection.

The three lines that copy and clear do not await, so they do not interleave
with each other. They do interleave with a coroutine already suspended inside
`ensure_started`.

Shutdown should set a closed flag, take each connection lock, and refuse new
inserts.

### 3. The Batfish row cap runs after the full result is built

`BatfishQueryResponse` cuts the list to 5,000 rows / 1,000 nodes before the
JSON response, and the Template Editor shows the truncation notice. That is
what the plan's model validator does.

The coordinator query and the in-memory table are still the full result. One
ad-hoc routes query can still allocate a full routing table in the API
process. The 30/minute limit only bounds how often that happens.

---

## Smaller issues

**Device ids that sanitize to the same filename share one config.** B6 calls
`sanitize_path_segment`, which turns `/` and `..` into `_`. `a/b` and `a_b`
both become `a_b.cfg`, and the later write wins. No current inventory id
contains `/`. The collision is what that helper does.

**The first caller of a rate-limit bucket fixes its budget.**
`build_user_rate_limiter` caches by bucket name and ignores a later
`attempts` / `window_seconds`. Every bucket in this diff is used once, with
one budget. A second use of the same name would silently keep the first
budget.

**B5 compares the captured id as a string.** The plan wrote
`int(group) != workflow_id`. The code uses `group != str(workflow_id)`. For a
real `manus-workflow-<id>` with no leading zeros the two agree. `manus-workflow-01`
is rejected for workflow 1 as well, and it is not that workflow's actual
default network (`manus-workflow-1`).

---

## Still open (not this diff)

**Phase 4.5** was not run. `doc/SECRET_MANAGER_INTEGRATION.md` still marks
Infisical `PATCH` and version-pinned reads as unverified. `get_field_history`
still returns an empty list and logs a warning.

**Phases 7–10** are not in this diff. Still open: W6 (content-based secret
redaction), W5/S15 (upload size limits), S14/R6 (inventory ownership on
rename and delete), the Q-series cleanup, and D1 (`SECURITY.md`).
