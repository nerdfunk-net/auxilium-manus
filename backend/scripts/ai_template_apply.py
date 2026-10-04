#!/usr/bin/env python3
"""Apply an AI-authored create/update to a template — the only way the
ai-assistant service account touches the `templates` table. See
doc/ai_collaboration/PROCESS.md.

Deliberately dumb infrastructure: identity, gating, persistence, reporting.
It does not choose a category or template content. The policy itself lives in
services/templates/ai_template_service.py: the AI may create only templates
named "[AI Draft] ..." and may update only templates it created itself.

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

Gates (enforced in AiTemplateService, before anything is written): the
ai-assistant user must be active (an admin flips this on in Settings -> Users —
the global kill-switch, shared with backend/scripts/ai_workflow_apply.py); a
created or renamed template must be named "[AI Draft] ..."; an update may only
target a template whose created_by is the ai-assistant. There is no per-item
session/consent row — templates have no ownership, folder, or visibility
concept to scope a session to (see PROCESS.md's "The template apply
mechanism"), so the AI is confined to its own drafts instead. A human promotes
a draft by renaming it.

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
    from core.domain_exceptions import DomainError
    from services.templates.ai_template_service import AiTemplateService
    from services.templates.exceptions import (
        TemplateCredentialNotFoundError,
        TemplateNameConflictError,
        TemplateNotFoundError,
    )

    with SessionLocal() as db:
        service = AiTemplateService(db)
        try:
            if args.template_id is None:
                result = service.create(patch)
                operation = "created"
            else:
                result = service.update(args.template_id, patch)
                operation = "updated"
        except DomainError as exc:
            return _fail(exc.detail)
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
