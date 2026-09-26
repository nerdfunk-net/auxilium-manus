#!/usr/bin/env python3
"""Apply an AI-authored create/update to a template — the only way the
ai-assistant service account touches the `templates` table. See
doc/ai_collaboration/PROCESS.md.

Deliberately dumb infrastructure: identity, gating, persistence, reporting.
It does not choose a name prefix, a category, or template content — that
reasoning belongs to whatever calls this script (see AI_DEFAULTS.md's
"[AI Draft] " naming convention, which this script has no knowledge of).

Usage (from backend/, with the project venv)::

    python scripts/ai_template_apply.py --patch-file patch.json
    python scripts/ai_template_apply.py --template-id 7 --patch-file patch.json

Omitting --template-id creates a new template (patch.json is validated as
TemplateCreate); passing --template-id updates that existing template
(patch.json is validated as TemplateUpdate, a partial update — only fields
present in the patch are changed). patch.json is a JSON object with any of:
"name", "description", "notes", "template_type", "category", "content",
"variables", "pre_run_commands", "pre_run_use_textfsm", "nautobot_attributes",
"credential_id", "batfish_config".

One gate must pass before anything is written: the ai-assistant user must be
active (an admin flips this on in Settings -> Users — the global kill-switch,
shared with backend/scripts/ai_workflow_apply.py). Unlike that script, there
is no per-item session/consent row here — templates have no ownership,
folder, or visibility concept to scope a session to (see PROCESS.md's
"The template apply mechanism" for why this is deliberately simpler than the
workflow feature's two-gate model).

Prints a JSON report to stdout: the resulting template row plus an
"operation" field ("created" or "updated").
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

_ALLOWED_FIELDS = {
    "name",
    "description",
    "notes",
    "template_type",
    "category",
    "content",
    "variables",
    "pre_run_commands",
    "pre_run_use_textfsm",
    "nautobot_attributes",
    "credential_id",
    "batfish_config",
}


def _load_patch(patch_file: Path) -> dict[str, Any]:
    data = json.loads(patch_file.read_text())
    if not isinstance(data, dict):
        raise ValueError("Patch file must contain a JSON object")
    unknown = set(data) - _ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"Patch file has unsupported field(s): {sorted(unknown)}")
    return data


def _fail(message: str) -> int:
    print(json.dumps({"error": message}))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template-id", type=int, default=None)
    parser.add_argument("--patch-file", type=Path, required=True)
    args = parser.parse_args()

    try:
        patch = _load_patch(args.patch_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _fail(f"Could not read patch file: {exc}")

    from core.database import SessionLocal
    from models.templates import TemplateCreate, TemplateUpdate
    from repositories.user_repository import UserRepository
    from services.auth.rbac_seed import AI_ASSISTANT_USERNAME
    from services.templates.exceptions import (
        TemplateCredentialNotFoundError,
        TemplateNameConflictError,
        TemplateNotFoundError,
    )
    from services.templates.templates_service import TemplatesService

    with SessionLocal() as db:
        ai_user = UserRepository(db).get_by_username(AI_ASSISTANT_USERNAME)
        if ai_user is None:
            return _fail(
                f"'{AI_ASSISTANT_USERNAME}' user does not exist — has the app been started "
                f"at least once since this feature was deployed?"
            )
        if not ai_user.is_active:
            return _fail(
                f"'{AI_ASSISTANT_USERNAME}' is disabled — an admin must activate it in "
                f"Settings -> Users before this script can run."
            )

        service = TemplatesService(db)

        try:
            if args.template_id is None:
                data = TemplateCreate(**patch)
                result = service.create_template(
                    name=data.name,
                    description=data.description,
                    notes=data.notes,
                    template_type=data.template_type,
                    category=data.category,
                    content=data.content,
                    variables={k: v.model_dump() for k, v in data.variables.items()},
                    pre_run_commands=data.pre_run_commands,
                    pre_run_use_textfsm=data.pre_run_use_textfsm,
                    nautobot_attributes=data.nautobot_attributes,
                    credential_id=data.credential_id,
                    batfish_config=(
                        data.batfish_config.model_dump() if data.batfish_config else None
                    ),
                    created_by=AI_ASSISTANT_USERNAME,
                    acting_user_id=ai_user.id,
                )
                operation = "created"
            else:
                data = TemplateUpdate(**patch)
                variables = (
                    {k: v.model_dump() for k, v in data.variables.items()}
                    if data.variables is not None
                    else None
                )
                result = service.update_template(
                    args.template_id,
                    name=data.name,
                    description=data.description,
                    notes=data.notes,
                    template_type=data.template_type,
                    category=data.category,
                    content=data.content,
                    variables=variables,
                    pre_run_commands=data.pre_run_commands,
                    pre_run_use_textfsm=data.pre_run_use_textfsm,
                    nautobot_attributes=data.nautobot_attributes,
                    credential_id=data.credential_id,
                    batfish_config=(
                        data.batfish_config.model_dump() if data.batfish_config else None
                    ),
                    acting_user_id=ai_user.id,
                )
                operation = "updated"
        except (
            TemplateNotFoundError,
            TemplateNameConflictError,
            TemplateCredentialNotFoundError,
        ) as exc:
            return _fail(str(exc))
        except Exception as exc:
            return _fail(f"Failed to apply patch: {exc}")

        print(json.dumps({"operation": operation, **result}, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
