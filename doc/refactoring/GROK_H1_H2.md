# Refactoring Plan — GROK H1 & H2

> Based on: `doc/GROK-ANALYSIS.md` §5.1  
> Date: 2026-07-19  
> Status: PLANNED  
> Issues: **H1** — TACACS shared secrets persist in workflow context · **H2** — Unsandboxed Jinja in TemplatesService

---

## Implementation Order

Apply in this order so each step is independently reviewable and testable.

1. **H2** — Switch `TemplatesService.render` to `SandboxedEnvironment` (small, isolated, no workflow behaviour change)
2. **H1-A** — Add shared secret seal/redact helpers under `services/workflow_context/`
3. **H1-B** — Seal secrets at write sites (`get-ise-tacacs-key`, `update-ise-tacacs-key`, `add-to-ise`, `device_builders`)
4. **H1-C** — Unwrap on read (`resolve_device_attribute`, Jinja context builder)
5. **H1-C2** — Close the `update-attribute` sealing bypass (`reveal_secrets=False` for this non-trusted consumer; seal fixed-mode writes to known secret paths) — **do this before or alongside H1-C**, since H1-C is what introduces the bypass
6. **H1-D** — Redact at persist / dump / log boundaries (`StepRunner._serialize_outcomes`, `log-attributes`, `log-message`)
7. **H1-E** — Frontend + registry + `doc/WORKFLOW-STEPS.md` copy cleanup (placeholder examples that advertise secret interpolation; document the sealed-secret contract for future step authors)
8. **Tests** — unit coverage for seal/unwrap/redact + TemplatesService sandbox + regression on TACACS executors + `update-attribute` bypass regression

> **Design choice (H1):** Prefer **encrypt-at-write + redact-on-export** over “drop the secret from context entirely.” Downstream steps (`render-jinja-template`, `update-ise-tacacs-key`, `add-to-ise`, `log-message` expressions) legitimately need the value *during* a run. Cleartext must not land in PostgreSQL step results, run APIs, log-attributes artifacts, or INFO logs.

---

## H2: Unsandboxed Jinja in TemplatesService

**What:** `TemplatesService.render` uses unrestricted `jinja2.Template`. Workflow rendering already uses `SandboxedEnvironment` in `workflow_steps/common/jinja_render.py`. Align the template-library preview/render path with the same sandbox.

**Why:** Privileged template authors (permission `templates:read` on `/templates/render`) can exercise unrestricted Jinja constructs (attribute access into internals, unsafe callables). Defense-in-depth: match the workflow path.

**Files changed:**
- `backend/services/templates/templates_service.py`
- (optional follow-up) extract shared env to `backend/services/templates/sandboxed_jinja.py` and point `workflow_steps/common/jinja_render.py` at it — **not required for the fix**
- `backend/tests/test_templates_service_render.py` (new)

**Do not** import `workflow_steps.common.jinja_render` from `TemplatesService` — that would violate CLAUDE.md (“External code must never import workflow_steps packages directly”). Duplicate the small `SandboxedEnvironment` setup in the templates service (or share via `services/templates/`).

### Code before

```python
# backend/services/templates/templates_service.py

from jinja2 import Template as JinjaTemplate
from jinja2 import TemplateError
from jinja2.exceptions import UndefinedError

# ...

def render(self, *, template_content: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Render Jinja2 ``template_content`` with the provided ``variables``."""
    variables_used = sorted(set(_VARIABLE_PATTERN.findall(template_content)))
    try:
        rendered = JinjaTemplate(template_content).render(**variables)
    except UndefinedError as exc:
        available = ", ".join(sorted(variables.keys())) or "none"
        raise ValueError(
            f"Undefined variable in template: {exc}. Available variables: {available}"
        ) from exc
    except TemplateError as exc:
        raise ValueError(f"Template syntax error: {exc}") from exc

    return {
        "rendered_content": rendered,
        "variables_used": variables_used,
        "warnings": [],
    }
```

### Code after

```python
# backend/services/templates/templates_service.py

from jinja2 import TemplateError, TemplateSyntaxError
from jinja2.exceptions import SecurityError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment

# Module-level env — same knobs as workflow_steps/common/jinja_render.py
_jinja_env = SandboxedEnvironment(
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)

# ...

def render(self, *, template_content: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Render Jinja2 ``template_content`` with the provided ``variables``.

    Uses ``SandboxedEnvironment`` so template-library preview cannot call
    unsafe attributes/methods the way unrestricted ``jinja2.Template`` allows.
    """
    variables_used = sorted(set(_VARIABLE_PATTERN.findall(template_content)))
    try:
        compiled = _jinja_env.from_string(template_content)
        rendered = compiled.render(**variables)
    except UndefinedError as exc:
        available = ", ".join(sorted(variables.keys())) or "none"
        raise ValueError(
            f"Undefined variable in template: {exc}. Available variables: {available}"
        ) from exc
    except SecurityError as exc:
        raise ValueError(f"Template uses a disallowed construct: {exc}") from exc
    except TemplateSyntaxError as exc:
        raise ValueError(f"Template syntax error: {exc}") from exc
    except TemplateError as exc:
        raise ValueError(f"Template render failed: {exc}") from exc

    return {
        "rendered_content": rendered,
        "variables_used": variables_used,
        "warnings": [],
    }
```

### Steps

1. Replace the `JinjaTemplate` import/usage with the sandboxed env as above.
2. Add `backend/tests/test_templates_service_render.py`:
   - Happy path: `{{ name }}` with `{"name": "r1"}` → `"r1"`.
   - Undefined variable still raises `ValueError`.
   - A known sandbox-blocked construct (e.g. accessing a private type/attr that `SandboxedEnvironment` rejects) raises `ValueError` wrapping `SecurityError`.
3. Manually hit `POST /api/templates/render` (via proxy) with a simple template to confirm UI preview still works.
4. Run: `../.venv/bin/python -m pytest backend/tests/test_templates_service_render.py -q`

### Optional follow-up (same PR or later)

Extract `_jinja_env` + thin `render_sandboxed(template, variables) -> str` into `services/templates/sandboxed_jinja.py`. Have `workflow_steps/common/jinja_render.py` import that helper so there is one sandboxed env configuration. Do **not** reverse the dependency (services must not import workflow_steps).

---

## H1: TACACS shared secrets persist in workflow context

### Problem summary

Cleartext `tacacs.shared_secret` (and nested `ise.tacacsSettings.sharedSecret`) is written into `DeviceContext.attribute_bags`, returned in `StepOutcome.context`, and persisted via:

```572:578:backend/services/execution/step_runner.py
    def _serialize_outcomes(outcomes: list[StepOutcome]) -> dict[str, Any]:
        return {
            "outcomes": {
                outcome.name: outcome.context.model_dump(mode="json")
                for outcome in outcomes
            }
        }
```

Anyone with run-read permission can recover TACACS keys. `log-attributes` dumps `context.model_dump`, and `log-message` can interpolate `{tacacs.shared_secret}` into INFO logs and step metadata.

**Write sites today:**

| Location | Behaviour |
|----------|-----------|
| `get_ise_tacacs_key/executor.py` | `set_device_attribute(..., "tacacs.shared_secret", secret)` |
| `update_ise_tacacs_key/executor.py` | same after ISE PUT |
| `add_to_ise/executor.py` | bags `tacacs.shared_secret` after create |
| `device_builders.py` (`build_ise_device`) | copies `tacacsSettings.sharedSecret` into `tacacs` bag; full ISE dict (including `tacacsSettings`) also lands in `ise` bag |
| `update_attribute/executor.py` (regex mode, **after** H1-C ships) | not a write site today, but becomes one once `resolve_device_attribute` unwraps — can copy an already-sealed secret into an arbitrary plaintext bag path; closed by H1-C2 |

### Target architecture

```
┌─────────────────────┐     seal_secret()      ┌──────────────────────────┐
│ ISE / step writers  │ ─────────────────────► │ attribute_bags (sealed)  │
└─────────────────────┘                        └────────────┬─────────────┘
                                                            │
                    ┌───────────────────────────────────────┼───────────────────┐
                    ▼                                       ▼                   ▼
           resolve / Jinja                         StepRunner persist      log-attributes
        unwrap_secret() → cleartext              redact_secrets()       redact_secrets()
        (in-memory only)                         → "***REDACTED***"     → "***REDACTED***"
                                                 (never ciphertext in
                                                  API-facing dumps either)
```

- **Sealed value** (at rest in bags / in-memory between steps): Fernet envelope reusing `core.crypto.EncryptionService` (same key material as credentials).
- **Exported value** (DB step `output`, log-attributes files, log-message metadata, any run API): always the literal `***REDACTED***` — not even ciphertext.
- **Consumer value** (attribute resolution, Jinja namespace, ISE update payloads): unwrap to cleartext only in process memory for the duration of the call.

Presence checks (`route-on-attribute` on `tacacs.shared_secret`, “already had key” in get-ise-tacacs-key) must treat a sealed envelope as present.

> **Key management (no new infra needed):** `EncryptionService` (`backend/core/crypto.py`) derives its Fernet key via PBKDF2-HMAC-SHA256 from `CREDENTIAL_ENCRYPTION_KEY` (falls back to `SECRET_KEY` if unset), both read from `backend/.env` — the same mechanism already used to encrypt credential-table secrets at rest. This repo's `backend/.env` already sets a dedicated `CREDENTIAL_ENCRYPTION_KEY` distinct from `SECRET_KEY`, which is the recommended production posture (`backend/.env.example` documents the fallback). H1 reuses this key as-is; no new secret needs to be provisioned. **Decrypt-failure behavior:** if `CREDENTIAL_ENCRYPTION_KEY` is rotated, `unwrap_secret` raises `ValueError` (`Failed to decrypt stored credential`) for any sealed envelope written under the old key. `resolve_device_attribute` must let that propagate as a `RuntimeError` from the calling step (fail closed) rather than silently returning `None`/placeholder — a step that needs a TACACS key it can no longer decrypt should fail visibly, not proceed as if the key were absent. Document this as an operational note: rotating `CREDENTIAL_ENCRYPTION_KEY` invalidates in-flight sealed secrets the same way it would invalidate stored credentials.

---

### H1-A: Secret helpers

**New file:** `backend/services/workflow_context/secret_fields.py`

```python
"""Seal, unwrap, and redact sensitive workflow attribute values.

TACACS shared secrets (and similar) may ride in DeviceContext bags for
in-run use, but must never appear as cleartext in persisted step results,
log-attributes dumps, or INFO logs.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from core.crypto import EncryptionService

SEALED_MARKER = "__am_sealed__"
REDACTED_PLACEHOLDER = "***REDACTED***"

# Dotted paths relative to device.attribute_bags
SECRET_BAG_PATHS: tuple[tuple[str, ...], ...] = (
    ("tacacs", "shared_secret"),
    ("ise", "tacacsSettings", "sharedSecret"),
)


def seal_secret(plaintext: str, *, encryption: EncryptionService | None = None) -> dict[str, Any]:
    svc = encryption or EncryptionService()
    token = svc.encrypt(plaintext)  # bytes (Fernet token)
    return {SEALED_MARKER: True, "v": 1, "ct": token.decode("ascii")}


def is_sealed_secret(value: Any) -> bool:
    return isinstance(value, dict) and value.get(SEALED_MARKER) is True and "ct" in value


def unwrap_secret(value: Any, *, encryption: EncryptionService | None = None) -> str | None:
    """Return cleartext for a sealed envelope, passthrough legacy str, else None."""
    if value is None:
        return None
    if is_sealed_secret(value):
        svc = encryption or EncryptionService()
        return svc.decrypt(str(value["ct"]).encode("ascii"))
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def secret_is_present(value: Any) -> bool:
    """True when a bag leaf holds a usable secret (sealed or legacy cleartext)."""
    if is_sealed_secret(value):
        return True
    return bool(isinstance(value, str) and value.strip())


def redact_secrets_in_data(data: Any) -> Any:
    """Deep-copy ``data`` and replace known secret leaves / sealed envelopes."""
    cloned = deepcopy(data)
    _redact_inplace(cloned)
    return cloned


def _redact_inplace(node: Any) -> None:
    if isinstance(node, dict):
        if is_sealed_secret(node):
            # Caller should replace the parent key; handle if node is the leaf itself.
            node.clear()
            node[SEALED_MARKER] = False
            node["redacted"] = True
            return
        devices = node.get("devices")
        if isinstance(devices, dict):
            for device in devices.values():
                if isinstance(device, dict):
                    bags = device.get("attribute_bags")
                    if isinstance(bags, dict):
                        _redact_bag_paths(bags)
        # Also handle a bare attribute_bags dict
        if "tacacs" in node or "ise" in node:
            _redact_bag_paths(node)
        for key, value in list(node.items()):
            if is_sealed_secret(value):
                node[key] = REDACTED_PLACEHOLDER
            else:
                _redact_inplace(value)
    elif isinstance(node, list):
        for item in node:
            _redact_inplace(item)


def _redact_bag_paths(bags: dict[str, Any]) -> None:
    for path in SECRET_BAG_PATHS:
        cursor: Any = bags
        for part in path[:-1]:
            if not isinstance(cursor, dict):
                cursor = None
                break
            cursor = cursor.get(part)
        if isinstance(cursor, dict) and path[-1] in cursor:
            leaf = cursor[path[-1]]
            if secret_is_present(leaf) or is_sealed_secret(leaf):
                cursor[path[-1]] = REDACTED_PLACEHOLDER
```

Wire `redact_secrets_in_data` so it always ends with placeholder strings at secret leaves (not empty sealed stubs). Adjust `_redact_inplace` during implementation so a sealed leaf becomes `REDACTED_PLACEHOLDER` when replaced via the parent key (the sketch above covers both bag paths and generic sealed values).

> **Known limitation — redaction is shape-based, not content-based.** `redact_secrets_in_data` only finds secrets by (a) the `SEALED_MARKER` dict shape, wherever it appears, or (b) the fixed `SECRET_BAG_PATHS` dotted paths under `attribute_bags`. Once a value is *unwrapped* (H1-C) and copied by a step into a differently-shaped output — e.g. a diff entry, a filtered list, a free-text outcome message — it becomes a bare string that neither mechanism recognizes, and it will **not** be redacted at persist time. Verified against current code: `route-on-attribute` and `get_ise_tacacs_key`/`update_ise_tacacs_key`'s own logging never do this (they compare/log state or tier/device name, never the resolved value). `update-attribute` **does** — see H1-C2 below, the one confirmed exploitable instance of this limitation. Any *new* step added later that calls `resolve_device_attribute` with `reveal_secrets=True` and writes the result somewhere other than the same bag path must be reviewed against this limitation; document it in `doc/WORKFLOW-STEPS.md` (H1-E) so step authors don't reintroduce it.

### Code before (no helper — cleartext write)

```python
# backend/workflow_steps/get_ise_tacacs_key/executor.py  (~395-398)

if secret:
    updated_devices[device_id] = set_device_attribute(
        device, "tacacs.shared_secret", secret
    )
```

### Code after (seal at write)

```python
from services.workflow_context.secret_fields import seal_secret, secret_is_present

# presence check (was: if existing_secret:)
existing = (device.attribute_bags.get("tacacs") or {}).get("shared_secret")
if secret_is_present(existing):
    updated_devices[device_id] = device
    already_present_count += 1
    continue

# ...

if secret:
    updated_devices[device_id] = set_device_attribute(
        device, "tacacs.shared_secret", seal_secret(secret)
    )
```

Apply the same `seal_secret(...)` wrap in:

- `update_ise_tacacs_key/executor.py` (`set_device_attribute(..., new_key_value)` → `seal_secret(new_key_value)`)
- `add_to_ise/executor.py` (bag assignment of `shared_secret`)
- `device_builders.py` (see below)

---

### H1-B: Stop copying cleartext from ISE inventory builders

### Code before

```python
# backend/workflow_steps/common/device_builders.py  (~113-120)

# Surfaced as its own top-level Jinja variable (build_jinja_context flattens
# attribute_bags by name), so a template can use {{ tacacs.shared_secret }}
# directly instead of drilling into ise.tacacsSettings.sharedSecret.
tacacs_settings = device.get("tacacsSettings")
if isinstance(tacacs_settings, dict):
    shared_secret = tacacs_settings.get("sharedSecret")
    if shared_secret:
        attribute_bags["tacacs"] = {"shared_secret": shared_secret}
```

Also, `attribute_bags["ise"] = {**device, ...}` copies the full ERS payload including `tacacsSettings.sharedSecret`.

### Code after

```python
from services.workflow_context.secret_fields import seal_secret

tacacs_settings = device.get("tacacsSettings")
if isinstance(tacacs_settings, dict):
    shared_secret = tacacs_settings.get("sharedSecret")
    if shared_secret:
        attribute_bags["tacacs"] = {"shared_secret": seal_secret(str(shared_secret))}

# Scrub the nested ISE copy so the ise bag is not a second cleartext channel.
ise_bag = attribute_bags["ise"]
nested = ise_bag.get("tacacsSettings")
if isinstance(nested, dict) and nested.get("sharedSecret"):
    ise_bag["tacacsSettings"] = {
        **nested,
        "sharedSecret": seal_secret(str(nested["sharedSecret"])),
    }
```

---

### H1-C: Unwrap on read

#### `resolve_device_attribute` / presence helpers

### Code before (conceptual)

`resolve_device_attribute` returns the raw bag leaf (string secret). Callers that send the value to ISE or Jinja receive cleartext today only because the bag holds cleartext.

### Code after

In `workflow_steps/common/attribute_path.py`, after resolving the leaf:

```python
from services.workflow_context.secret_fields import is_sealed_secret, unwrap_secret

# when returning a concrete value for interpolation / expressions:
if is_sealed_secret(value):
    return unwrap_secret(value)
return value
```

For **presence** APIs (`resolve_device_attribute_state` empty/absent/present), treat sealed envelopes as **present** without decrypting (use `secret_is_present`).

#### Jinja context

### Code before

```python
# backend/workflow_steps/common/jinja_render.py

for bag_name, bag_value in device.attribute_bags.items():
    if bag_name not in context:
        context[bag_name] = dict(bag_value)
```

### Code after

```python
from services.workflow_context.secret_fields import is_sealed_secret, unwrap_secret

def _unwrap_bag(bag: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in bag.items():
        if is_sealed_secret(value):
            out[key] = unwrap_secret(value)
        elif isinstance(value, dict):
            out[key] = _unwrap_bag(value)
        else:
            out[key] = value
    return out

for bag_name, bag_value in device.attribute_bags.items():
    if bag_name not in context:
        context[bag_name] = _unwrap_bag(dict(bag_value))
```

This preserves `{{ tacacs.shared_secret }}` for intentional template use while bags stay sealed in the workflow envelope.

> **Product note:** Rendering a secret into a stored artifact (git/filesystem) remains an operator choice. That is separate from H1 (secrets in *workflow context / run DB*). Document that `render-jinja-template` + `store-artifact` can still materialize secrets if the template references them.

---

### H1-C2: Close the `update-attribute` sealing bypass (confirmed exploitable)

**Verified against code** (`backend/workflow_steps/update_attribute/executor.py`, regex mode):

```python
source_value = resolve_device_attribute(device, source_path)   # H1-C makes this unwrap sealed secrets
...
return set_device_attribute(device, destination_path, transformed)  # plain write — no seal_secret()
```

Once H1-C makes `resolve_device_attribute` transparently unwrap sealed values (required for legitimate Jinja/ISE-update consumers), a workflow author can configure `update-attribute` with `source_path: tacacs.shared_secret` and any `destination_path` (e.g. `backup.token`, or a regex pattern that just passes the value through). The result is a **cleartext copy of the secret at a bag path that is neither a `SECRET_BAG_PATHS` entry nor a sealed dict** — it bypasses `_redact_bag_paths` (wrong path) and the generic `is_sealed_secret` sweep (no longer sealed), and lands unredacted in `WorkflowStepResult.output`, log-attributes dumps, and log-message interpolation of the new path. Fixed mode is unaffected (writes to `destination_path` directly, still caught by `SECRET_BAG_PATHS` if that path is the canonical one) unless the operator picks a non-canonical destination for a literal secret value, which the same fix below also covers.

**Fix:** `update-attribute` is a generic, non-trusted consumer (unlike `render-jinja-template`/`update-ise-tacacs-key`, whose whole purpose is consuming the secret intentionally) — it must not silently rehydrate a sealed value into a new plaintext home.

### Code before

```python
# backend/workflow_steps/update_attribute/executor.py

source_value = resolve_device_attribute(device, source_path)
...
transformed = apply_regex_transform(
    source_text=source_value,
    pattern=pattern,
    destination_template=destination_template,
    flags=regex_flags,
)
...
return set_device_attribute(device, destination_path, transformed)
```

### Code after

```python
# backend/workflow_steps/update_attribute/executor.py

from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER

# update-attribute is a generic power-user step, not a trusted secret
# consumer — never rehydrate a sealed value here, regex mode or fixed mode.
source_value = resolve_device_attribute(device, source_path, reveal_secrets=False)
if source_value == REDACTED_PLACEHOLDER:
    raise ValueError(
        f"{_STEP_ID}: source_path '{source_path}' resolves to a sealed secret; "
        "update-attribute cannot read or copy secret values. Use "
        "render-jinja-template or the ISE-specific steps instead."
    )
...
transformed = apply_regex_transform(
    source_text=source_value,
    pattern=pattern,
    destination_template=destination_template,
    flags=regex_flags,
)
...
return set_device_attribute(device, destination_path, transformed)
```

Apply the same `reveal_secrets=False` guard to `_apply_fixed_update`'s destination check is unnecessary (fixed mode never reads a source secret), but add a symmetric guard on write: if `destination_path` matches a `SECRET_BAG_PATHS` entry, seal the fixed value before writing —

```python
from services.workflow_context.secret_fields import seal_secret
from services.workflow_context.secret_fields import path_is_known_secret  # new small helper, see H1-A

value = str(fixed_value)
if path_is_known_secret(destination_path):
    value = seal_secret(value)
return set_device_attribute(device, destination_path, value)
```

Add `path_is_known_secret(dotted_path: str) -> bool` to `secret_fields.py` alongside `SECRET_BAG_PATHS` (simple membership check against the same tuple) so this and any future write-site guard share one source of truth instead of re-deriving the path list.

Only `render-jinja-template`'s Jinja namespace and `update-ise-tacacs-key`/`add-to-ise`'s internal resolution (both intentional, documented secret consumers — H1-C's product note already covers the artifact-materialization risk for the Jinja path) should call `resolve_device_attribute` with the default `reveal_secrets=True`. Audit any other caller of `resolve_device_attribute`/`resolve_device_attribute_state` added in the future against this default.

---

### H1-D: Redact at persist / dump / log boundaries

#### StepRunner persistence

### Code before

```python
@staticmethod
def _serialize_outcomes(outcomes: list[StepOutcome]) -> dict[str, Any]:
    return {
        "outcomes": {
            outcome.name: outcome.context.model_dump(mode="json")
            for outcome in outcomes
        }
    }
```

### Code after

```python
from services.workflow_context.secret_fields import redact_secrets_in_data

@staticmethod
def _serialize_outcomes(outcomes: list[StepOutcome]) -> dict[str, Any]:
    return {
        "outcomes": {
            outcome.name: redact_secrets_in_data(
                outcome.context.model_dump(mode="json")
            )
            for outcome in outcomes
        }
    }
```

Apply the same redaction wherever fan-out / Hatchet child aggregation **persists** parent step results from context dicts (see `hatchet/workflows/workflow_run.py` merge path that writes `WorkflowStepResult.output`). In-memory `step_outcomes` used for the rest of the run keeps sealed (decryptable) values — only the JSON written to PostgreSQL is redacted.

> If a future resume path reloads context **from** `WorkflowStepResult.output`, sealed values will already be gone (`***REDACTED***`). Today the engine keeps live `WorkflowContext` objects in `step_outcomes` for the run, so redacting on persist does not break mid-run chaining. Document this invariant; if resume-from-DB is added later, persist **sealed ciphertext** instead of the placeholder and redact only in API response serializers.

**Recommended split (implement now):**

| Channel | Store |
|---------|-------|
| In-process `step_outcomes` | sealed envelope |
| `WorkflowStepResult.output` (DB) | `***REDACTED***` (safe for `workflow_runs:read`) |
| Future: encrypted resume blob | optional separate column / artifact — out of scope unless resume-from-DB exists |

#### log-attributes

### Code before

```python
def build_context_snapshot(context: WorkflowContext) -> dict[str, Any]:
    """Serialize the full workflow context envelope for inspection."""
    return context.model_dump(mode="json")
```

### Code after

```python
from services.workflow_context.secret_fields import redact_secrets_in_data

def build_context_snapshot(context: WorkflowContext) -> dict[str, Any]:
    """Serialize the workflow context for inspection with secrets redacted."""
    return redact_secrets_in_data(context.model_dump(mode="json"))
```

Pretty-text formatting then automatically shows `shared_secret: ***REDACTED***`.

#### log-message

### Code before

```python
rendered = render_message_template(message, device)
# ...
logger.info(
    "log-message node_id=%s device_id=%s message=%r",
    node_id,
    device_id,
    rendered,
)
```

`render_message_template` uses `resolve_device_attribute`, which after H1-C would unwrap secrets into the log line.

### Code after

Two complementary controls:

1. **Do not unwrap for log interpolation** — add `resolve_device_attribute(..., reveal_secrets=False)` (default `False` for log path) that returns `REDACTED_PLACEHOLDER` for sealed/secret paths.
2. **Change the UI placeholder** so examples do not teach secret logging.

```python
# log_message/executor.py

def render_message_template(template: str, device: DeviceContext) -> str:
    def _replace(match: re.Match[str]) -> str:
        value = resolve_device_attribute(
            device, match.group(1), reveal_secrets=False
        )
        if value is None:
            return ""
        return str(value)

    return _PLACEHOLDER_PATTERN.sub(_replace, template)
```

```python
# attribute_path.py (signature extension)

def resolve_device_attribute(
    device: DeviceContext,
    path: str,
    *,
    reveal_secrets: bool = True,
) -> Any:
    ...
    if _path_is_secret(path) or is_sealed_secret(raw):
        if not reveal_secrets:
            return REDACTED_PLACEHOLDER
        return unwrap_secret(raw) if is_sealed_secret(raw) else raw
```

Default `reveal_secrets=True` preserves ISE update / expression behaviour; log-message opts out.

---

### H1-E: Frontend / registry / spec doc copy

### Code before

```tsx
// frontend/.../log-message/index.tsx
placeholder="Tacacs key {tacacs.shared_secret} successfully read from ISE"
```

### Code after

```tsx
placeholder="Device {device.name} processed from ISE"
```

Update any `registry.yaml` examples or docs that interpolate `{tacacs.shared_secret}` in log-message samples. Keep attribute path `tacacs.shared_secret` as the supported in-run handle for steps that need it; do not advertise it as a log field.

**Also update `doc/WORKFLOW-STEPS.md`** (required per `CLAUDE.md`'s step-authoring rule — this doc must stay accurate for anyone adding/modifying a step). Add a short "Secret-valued attributes" subsection covering:
- Sealed-envelope contract: `seal_secret`/`unwrap_secret`/`secret_is_present`/`is_sealed_secret` in `services/workflow_context/secret_fields.py`, and which dotted paths (`SECRET_BAG_PATHS`) are currently treated as secret.
- `resolve_device_attribute(..., reveal_secrets=...)` default is `True` for trusted consumers (Jinja context, ISE-update expressions); generic/bulk steps (e.g. `update-attribute`) must pass `reveal_secrets=False` and fail closed on a redacted read (H1-C2).
- The shape-based-redaction limitation called out in H1-A: new steps must not copy an unwrapped secret value into a differently-shaped output (diff entries, filtered lists, free-text messages) without re-sealing it first, since `redact_secrets_in_data` will not catch it.
- Rendering a secret into a stored artifact via `render-jinja-template` → `store-artifact` remains an explicit operator choice, not a bug (H1-C product note).

---

## Test plan

### H2

| Test | Expect |
|------|--------|
| `TemplatesService.render` simple var | rendered string |
| undefined var | `ValueError` |
| sandbox-blocked attr/callable | `ValueError` (from `SecurityError`) |
| Existing template UI preview | unchanged UX |

### H1

| Test | Expect |
|------|--------|
| `seal_secret` / `unwrap_secret` round-trip | cleartext restored |
| `secret_is_present(sealed)` | `True` |
| `redact_secrets_in_data` on context dump | `tacacs.shared_secret == "***REDACTED***"` and nested ISE path redacted |
| `get_ise_tacacs_key` executor | bag leaf is sealed (`__am_sealed__`); unwrap returns key |
| `StepRunner._serialize_outcomes` | persisted JSON has placeholder, not cleartext/ciphertext |
| `build_context_snapshot` | redacted |
| `log-message` with `{tacacs.shared_secret}` | metadata + INFO contain `***REDACTED***` |
| `route-on-attribute` present/absent on sealed key | still routes correctly |
| `test_device_builders` | expects sealed envelope or redacted nested ISE field (update assertions) |
| Legacy cleartext string in bag | still unwraps / redacts (migration safety) |
| `update-attribute` regex mode, `source_path=tacacs.shared_secret` | raises `ValueError`, no plaintext copy written anywhere in the resulting device bags (H1-C2) |
| `update-attribute` fixed mode writing to a `SECRET_BAG_PATHS` destination | value stored sealed, not plaintext |
| `unwrap_secret` after simulated key rotation (decrypt with wrong key) | raises `ValueError`; calling step surfaces it as `RuntimeError`, does not proceed as if absent |

Run (from `backend/` with venv):

```bash
../.venv/bin/python -m pytest \
  tests/test_templates_service_render.py \
  tests/test_secret_fields.py \
  tests/test_get_ise_tacacs_key_executor.py \
  tests/test_update_attribute_executor.py \
  tests/test_device_builders.py \
  tests/test_log_attributes_executor.py \
  tests/test_attribute_path.py \
  -q
```

---

## Out of scope (explicit)

- Migrating historical `WorkflowStepResult.output` rows that already contain cleartext (optional one-shot scrub script later).
- Vault-as-a-service for TACACS keys (full credential-table entries per device key) — heavier than needed for H1.
- Preventing operators from embedding secrets in Jinja → artifact sinks (document only).
- M1/M2 path traversal and other GROK items.

---

## Acceptance criteria

- [ ] `TemplatesService.render` uses `SandboxedEnvironment`; unsafe constructs fail closed with `ValueError`.
- [ ] New TACACS writes store sealed envelopes in `attribute_bags`, never raw strings.
- [ ] `ise.tacacsSettings.sharedSecret` is sealed or stripped in device builders.
- [ ] Persisted step `output` and log-attributes dumps never contain TACACS cleartext.
- [ ] `log-message` does not write cleartext secrets to INFO or step metadata.
- [ ] In-run consumers (Jinja, ISE update expressions, presence routing) still function via unwrap.
- [ ] `update-attribute` cannot read or copy a sealed secret into a new plaintext location (H1-C2); fixed-mode writes to a known secret path are sealed, not plaintext.
- [ ] Simulated `CREDENTIAL_ENCRYPTION_KEY` rotation causes `unwrap_secret` to fail closed (`RuntimeError` from the calling step), not silent data loss.
- [ ] `doc/WORKFLOW-STEPS.md` documents the sealed-secret contract and the `reveal_secrets` default for future step authors.
- [ ] Unit tests above are green.
