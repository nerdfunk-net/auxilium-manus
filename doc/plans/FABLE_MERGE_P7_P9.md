# Review: Phases 7–9 of `FABLE_MERGE_20261009.md`

Reviewed: 2026-10-09, against the uncommitted working tree (not a commit).
Plan: `doc/plans/FABLE_MERGE_20261009.md`. Source findings: `doc/analysis/FABLE_MERGE_20261009.md`.

**Verdict.** Phases 7 and 8 follow the plan, and the unit tests that cover phases 7–9 pass
(`123 passed, 4 subtests`: secret fields, credentials service, certificate upload limit,
body limit, step-runner scope, inventory ownership, inventory transfer, apply-updates,
base repository, ISE error decorator, OIDC link script, RBAC, service factory, request-model
extra-forbid). Two problems should be fixed before this is treated as done. Phase 9 is only
partly done; the leftovers are already listed in `doc/OPEN_TODOS.md`. Phase 10 is not in
the diff.

The tests never run a fan-out child, so they do not catch bug 1.

---

## What landed

| Phase | Items | In the diff |
|---|---|---|
| 7 | W6, W5/S15 | Yes. Content scrubbing works on the in-process runner. It does not cover fan-out (bug 1). Certificate reads are capped at 64 KiB. Declared `Content-Length` above 25 MiB returns 413. |
| 8 | S14 / R6 | Yes. Rename carries `created_by`, delete removes private inventories, startup logs orphans. Same session, one commit. |
| 9 | Q2–Q6, Q8, R7, T6, CI file | Yes. Q5 logs a cache failure once. Q4 replaces silent `pass`. Q7, Q9, and Q1/Q10 are started only. |
| 10 | D1–D7, T5 | No. |

W6 records cleartext in a `ContextVar` set for the segment (`run_secret_scope` /
`with_run_secret_scope` on `execute_all`, `resume_after_join`, and `execute_subgraph`).
`unwrap_secret` and the three `get_decrypted_*` methods add values of at least 8 characters.
`redact_secrets_in_data` then replaces those strings in string leaves, longest first.

S15 checks `Content-Length` in middleware and stops a certificate upload after 64 KiB + 1.
`docker/DOCKER.md` and `backend/.env.example` document the 25 MiB default and the chunked-body gap.

S14 is `reassign_creator` / `delete_private_created_by` inside `UserService.update_user` and
`delete_user`, plus `warn_about_orphaned_inventories` in the lifespan. Global rows stay, with
the old username kept as a label. Access checks use `created_by` only for `scope == "private"`,
so a later holder of that name does not gain those global inventories. The `owner_user_id`
follow-up is in `doc/OPEN_TODOS.md`.

---

## Bugs

### 1. Fan-out saves step output after the secret registry is gone

Inventory runs do not persist step output inside `execute_all`. They return a fan-out signal,
and each device group runs in `execute_subgraph`. That method is wrapped in
`with_run_secret_scope`, so passwords decrypted during the child are recorded. The wrapper
clears the registry when `execute_subgraph` returns. The child then serializes the raw context:

```144:154:backend/hatchet/workflows/device_group_execution.py
    # Serialize outcomes for parent aggregation; exclude the inventory step itself.
    # "__step_errors__" is a reserved key (not a canvas node_id) carrying
    # node_id -> {message, category, error_id} for nodes whose executor raised.
    result: dict[str, Any] = {"__step_errors__": step_errors}
    for node_id, outcomes in step_outcomes.items():
        if node_id == input.start_node_id:
            continue
        result[node_id] = {
            outcome_name: context_val.model_dump(mode="json")
            for outcome_name, context_val in outcomes.items()
        }
```

`model_dump` does not call `redact_secrets_in_data`. The parent aggregates in another task,
where the registry was never set, and writes that dump to `WorkflowStepResult.output`:

```212:215:backend/hatchet/workflows/workflow_run/aggregation.py
        for outcome_name, ctx_list in node_outcomes.items():
            merged_ctx = merge_fan_out_contexts(ctx_list) if len(ctx_list) > 1 else ctx_list[0]
            node_merged[outcome_name] = merged_ctx
            merged_output[outcome_name] = redact_secrets_in_data(merged_ctx.model_dump(mode="json"))
```

Key-name and sealed-envelope redaction still run. Content redaction does not, because
`_RUN_SECRETS` is empty. A TACACS key or device password that was unwrapped so the child
could log in, and that then appears in a command transcript or a config blob, is stored in
the clear. The Hatchet task result is the same unredacted dump.

On the non-fan-out path, `_serialize_outcomes` runs inside `execute_all`, so the same text
is scrubbed. The unit test only checks that `_RUN_SECRETS.get()` is a set inside the
decorator. It never dumps a child result.

The fan-in still needs the cleartext context. Scrub a copy for persistence before the scope
ends, and pass that copy to the parent for `WorkflowStepResult`. Keep the raw context for
the merge. Do the same for `step_errors["message"]`: `ValueError` and `RuntimeError` text is
stored as `error_message` and is not passed through the scrubber (`get-device-configs`
raises `RuntimeError(result.error)`, git push raises `RuntimeError(push_result.message)`).

### 2. The credential write that commits still accepts any attribute

Q6 replaced `hasattr` + `setattr` with `apply_updates` and a frozenset. `update_no_commit`
uses it. The method `update_credential` actually calls does not:

```149:154:backend/repositories/credentials_repository.py
    def update(self, credential: Credential, **kwargs) -> Credential:
        for key, value in kwargs.items():
            setattr(credential, key, value)
        self.db.commit()
        self.db.refresh(credential)
        return credential
```

`CredentialsService.update_credential` builds the dict itself today (`name`, `username`,
`type`, encrypted secrets, `visibility`, `owner_user_id`, `vault_secret_fields`,
`updated_at`), so a request cannot add `id` or `storage_backend` through this method.
The repository no longer enforces that. Any later caller that spreads a request body into
`update()` writes whatever attribute exists, including `password_encrypted`,
`owner_user_id`, and `id`. That is the hole Q6 closed on the other repositories.
`update` should call `apply_updates` with `_UPDATABLE_FIELDS`, as `update_no_commit` does.

---

## Smaller issues

**SSH private keys used for git never enter the registry.** The plan said to register every
decrypt, and to confirm the three `get_decrypted_*` methods are the only funnel.
`get_ssh_key_path` reads the vault key, and `export_single_ssh_key` decrypts the local key,
without `register_secret_value`. `CredentialManager.git` uses `get_ssh_key_path`, not
`get_decrypted_ssh_key`. A transcript that contains that PEM is not scrubbed.

**Restoring a git remote URL can log the URL.** The new warning says not to log the URL,
then passes `exc_info=True`. GitPython puts the `remote set-url` command, including the URL,
in the traceback. Log the exception type only. The existing `Git pull failed: %s` /
`Pull failed: {e}` path still stringifies `GitCommandError` the same way; a failed pull
while the token URL is set puts the token in the step error and the worker log.

**Two tracked secrets that overlap in one string leave a tail.** The scrubber walks
longest-first and uses `str.replace`. That covers a secret that contains another. It does
not cover two secrets of the same length that overlap in the text (`abcdefgh` and
`defghijk` inside `abcdefghijk`): one replacement destroys the other match, and the
leftover characters stay. Equal-length order follows set iteration.

**The 64 KiB certificate cap does not stop the body from being buffered.** Starlette spools
the upload before `upload()` runs. `file.read(MAX_CERT_UPLOAD_BYTES + 1)` only limits what
is parsed and written. A declared body up to 25 MiB is still accepted by the middleware and
then rejected. A chunked body with no `Content-Length` is not limited at all, which
`docker/DOCKER.md` already says. The comment on `MAX_CERT_UPLOAD_BYTES` ("without being
buffered") overstates the check.

**`BaseRepository.updatable_fields` defaults to every column.** The plan used an empty
frozenset so a subclass that forgets the allow-list cannot update anything. `None` means
"every mapped column", including `id`. `GitRepositoryRepository` and
`SecretManagerConnectionRepository` both set a frozenset, so nothing in the tree hits the
default today.

**A private inventory created during a rename or delete can still be orphaned.** The
reassign and the user row share one transaction, so a failed rename rolls both back.
`created_by` is not a foreign key. An insert that commits after the `UPDATE`/`DELETE` and
before the user row changes is not covered, and the next holder of that username inherits
it. The startup warning only sees it on the next boot. The deferred `owner_user_id` plan
is what closes this.

**ISE 404s now include the request path.** Handlers that used to return a sanitized 502 for
a missing ISE object now return 404 with `detail=str(exc)`, and that message is
`ISE resource not found: {endpoint}`. The plan called this status change out. The path was
not previously shown to the client.

---

## Still open (not this diff, or only started)

**Q7.** `test_request_models_forbid_extra.py` locks the allow-list. Credentials is strict.
`doc/OPEN_TODOS.md` still counts 82 lenient request models (git repositories, workflows,
templates, sources, settings, the rest).

**Q9.** `GitRepository` is `Mapped[...]`. Pyright basic went from 73 errors to 54. The rest,
and the `requirements-dev.txt` pin, are in `doc/OPEN_TODOS.md`. CI leaves the types job
advisory until that hits zero.

**Q1 / Q10.** The five long functions were split, and none of the three the plan called out
are at or under 50 lines (`_process_one_device` 92, `run_git_workflow_step` 100,
`open_change_request.execute` 118). Q10 was not started. Both are recorded in
`doc/OPEN_TODOS.md`.

**Phase 10** (D1–D7, T5), including `SECURITY.md`, is not in this diff.

**Chunked request bodies** remain unbounded unless a proxy enforces a limit. That matches
the plan; it is not implemented in the application.
