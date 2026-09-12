# Review: open questions and gaps in `FABLE_BACKEND_ISSUES.md`

Source plan: `doc/plans/FABLE_BACKEND_ISSUES.md`, itself sourced from
`doc/analysis/FABLE_BACKEND_20260902.md` §5.3 (S1, S2+S3, S4, S6).
Status: **resolved 2026-09-02**. Every item below was folded into the plan; see its §0.1
"Review resolutions" table (R1–R5) for the decision taken and the section that changed. Kept as
the review record only. Nothing here has been implemented.

## Verdict

The plan is well-written and mostly implementable as-is. Its before/after code snippets were
checked against the live code and match almost verbatim (`OIDCService.provision_or_get_user`,
`RBACService._require_admin_actor`, `core/auth.py::get_current_user`/`_require_active_user_id`,
`production_guards.py`, all three Dockerfiles, `start.sh`), which means whoever wrote it actually
read the code rather than guessing. The RBAC policy (P1–P7) is coherent and closes exactly the
holes the source analysis found; the OIDC fix is a textbook `(issuer, sub)` binding; the Docker
root-entrypoint design correctly accounts for `cert_installer.py` still running (harmlessly) inside
each now-unprivileged process; scoping token invalidation (S5) out as a named follow-up rather than
pretending to fix it is the right call.

That said, four sections have concrete gaps that will trip up a literal implementation. None are
fatal to the overall approach; all are cheap to resolve before or during implementation.

---

## 1. §3 Docker — `docker/.env.example` already exists, with the opposite purpose

The plan lists `docker/.env.example` under "New files": "every required variable with an empty
value and a comment." That file already exists (last touched 2026-08-31) and is a byte-for-byte
mirror of `backend/.env.example` — filled-in *development* defaults, meant for running the backend
directly (outside Docker). `docker-compose.yml` says the opposite of what the plan needs:

```10:13:docker/docker-compose.yml
# Backend settings for manus-web / manus-worker / manus-background-worker are
# declared in x-manus-app-env below (mirrors backend/.env.example). Edit
# values here — not via docker/.env.
```

The plan's `${VAR:?msg}` approach requires Compose to load `docker/.env` for variable
substitution — which directly contradicts this comment and would either collide with or silently
overwrite the existing file's current job.

**Question to resolve before implementing:** rename the existing file (e.g.
`docker/.env.backend.example`) and repoint its one reference, or repurpose it as the new
compose-secrets file and delete the "mirrors backend/.env.example" comment/workflow? The plan
doesn't say, and picking wrong will confuse whichever workflow doesn't win.

---

## 2. §4 Password policy — the bootstrap admin path bypasses the policy entirely

`AuthService.ensure_initial_admin` creates the seeded admin via `UserRepository.create_user`
directly, never through `UserCreate` (Pydantic) or the new `validate_password()`:

```103:109:backend/services/auth/auth_service.py
        try:
            return self.users.create_user(
                username=settings.initial_username,
                password_hash=password_hash.hash(settings.initial_password),
                is_active=True,
            )
```

`production_guards.py` only rejects `INITIAL_PASSWORD == "admin"` (exact literal match). An
operator setting `INITIAL_PASSWORD=xyz1` (5 chars, not the literal default) passes every existing
guard and gets a sub-12-character admin password — silently violating the very policy this fix is
supposed to introduce everywhere else.

**Gap:** the plan's diff for `ensure_initial_admin` only adds `must_change_password=True`. It
should also either call `validate_password(settings.initial_password)` there (raising at startup,
loudly, rather than after the fact), or extend `production_guards.validate_non_development_secrets`
with a length check on `initial_password` alongside the existing literal-default check.

---

## 3. §4.7 Frontend — the described `useApi` / 403 behavior doesn't match the current hook

The plan states: *"`useApi` treats a 403 with `code: "password_change_required"` by opening the
same dialog."* Today, `useApi.apiCall` special-cases 403 **before** ever reading the response
body:

```32:35:frontend/src/hooks/use-api.ts
      if (response.status === 403) {
        throw new Error("Permission denied");
      }
```

It never parses `detail` for 403 responses (only for other failure codes), and — more
fundamentally — a plain hook has no mechanism to "open a dialog"; it can only throw for the
calling component to catch. Making the plan's described behavior real requires:

1. Reading the JSON body before deciding what to do on a 403.
2. Some piece of global state (e.g. a Zustand flag alongside `useAuthStore`) that a
   dashboard-level `<ChangePasswordDialog>` subscribes to, since `useApi` itself can't render
   anything.

This is a real, non-trivial code change to a shared hook used everywhere, not the "small" tweak
the plan's wording implies.

**Related gap — three duplicated response parsers, only two mentioned.** `AuthUser` gaining
`must_change_password: boolean` requires updating the field allowlist in *three* near-identical
parser functions, but the plan only names two:

- `frontend/src/app/api/auth/login/route.ts` — `parseUserResponse` (mentioned)
- `frontend/src/app/api/auth/refresh/route.ts` — `parseSessionResponse` (mentioned)
- `frontend/src/app/api/auth/me/route.ts` — `parseUserResponse` (**not mentioned**)

The third one is what `useAuthStore.loadCurrentUser()` calls on every page load / session
restore. Skipping it means a user who dismisses the forced dialog (or just closes the tab) and
reopens the app won't have `must_change_password` reflected client-side on reload — the backend
still blocks every real action (§4.6 is the actual security boundary), so this is a UX bug rather
than a security hole, but it should be fixed in the same pass, not discovered later.

---

## 4. Smaller, non-blocking observations

- **§1.6 (optional admin OIDC linking)** proposes showing `oidc_provider`/`oidc_subject` fields in
  the user-edit dialog so an admin can bind a pre-existing local account to an IdP identity. But
  `UserAdminResponse` (`backend/models/rbac.py`) currently exposes neither `email` nor
  `oidc_provider`/`oidc_subject` — an admin has no way to see the current binding state before
  deciding what to set. Not blocking (the plan already marks 1.6 as optional / not required for
  release), but worth knowing before starting that "small" follow-up — it's a bit bigger than one
  field addition.

- **§2.4 ("route the `is_active` field of `PUT /users/{id}` through `set_active`")** is directionally
  right but understates the work: `UserService.update_user` today is one flat method that builds a
  single `updates` dict for username/password/is_active together. Splitting `is_active` out to go
  through the guarded `set_active` path needs a bit more restructuring than the one-line hint
  suggests — e.g. deciding what happens when a request simultaneously renames *and* deactivates a
  user who holds `admin` in the same `PUT` call.

- **Repository mass-assignment shape.** `UserRepository.update_user`/`RBACRepository.update_role`
  take `**kwargs` and `setattr` whatever key exists on the model (already flagged as a separate
  finding in the source analysis, §4.4). Not part of this plan's scope, but the plan adds several
  new call sites through this same repository method (`must_change_password`, `oidc_subject`) —
  worth a one-line note in the plan that this pattern is being extended, not just reused.

---

## Suggested resolution before/while implementing

1. Decide the `docker/.env.example` question (rename vs. repurpose) — 5-minute decision, avoids a
   silent collision.
2. Add a `validate_password`/length check on `INITIAL_PASSWORD` in `ensure_initial_admin` or
   `production_guards.py` so the bootstrap path can't undercut the policy it's meant to enforce.
3. Budget real implementation time for `useApi`'s 403 handling and the global dialog-trigger
   mechanism in §4.7 — treat it as a normal feature slice, not a one-line tweak.
4. Update all three frontend auth-response parsers (`login`, `me`, `refresh` routes), not just two.
