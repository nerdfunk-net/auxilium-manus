"""Tenant and access-policy configuration of a Cisco ACI fabric as stable JSON (read-only).

One file per tenant (``tenants/<name>.json``, ``GET /api/mo/uni/tn-<name>.json``) and one for the
fabric's access policies (``access-policies.json``, ``GET /api/mo/uni/infra.json``), each read with
``rsp-subtree=full&rsp-prop-include=config-only`` (the configuration only, not state). Two reads of
an unchanged fabric must give identical text, otherwise every backup would be a git diff: volatile
attributes are removed and the children of every object are sorted. The names follow the documented
APIC REST API and could not be checked on the DevNet sandbox in this session.

Not exported: fabric policies (``uni/fabric``), the APIC's own settings, and anything outside
``uni/tn-*`` and ``uni/infra``. What the APIC leaves out of a configuration export is not our call:
review a repository before pushing it somewhere shared. Attributes that hold a secret (``key``,
``password``, ``authKey``, ``community``, ...) are replaced by ``<secret removed>`` when the APIC
returns a value for them (it normally returns them empty), so a restore from these files never
carries a key, and a changed secret does not show in a diff.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from services.aci.common.coerce import text
from services.aci.common.exceptions import AciError, AciValidationError
from services.aci.credentials import AciCredentials

# The tenants of one fabric are read at most this many at a time.
MAX_PARALLEL_READS = 4
MAX_TENANTS = 1_000

ACCESS_POLICIES_FILE = "access-policies.json"
_SUBTREE_PARAMS = {"rsp-subtree": "full", "rsp-prop-include": "config-only"}
# Attributes that change without a configuration change.
_VOLATILE = frozenset({"modTs", "createTs", "childAction", "lcOwn", "uid"})
# ACI names are letters, digits and ``_.-``; anything else never reaches a URL or a file path. A
# name also must survive ``sanitize_relative_path`` unchanged (it rewrites ``..`` and strips leading
# and trailing dots), otherwise two tenants could share one file: no ``..``, no edge dots.
_SAFE_NAME = re.compile(r"^(?!.*\.\.)[A-Za-z0-9_\-](?:[A-Za-z0-9_.\-]{0,62}[A-Za-z0-9_\-])?$")
# Attributes that hold a secret (a protocol password or key, an SNMP community, a VMM password).
# The APIC returns them empty for most objects; one that arrives with a value is replaced, so a
# backup repository never becomes a store of keys. Compared case-insensitively, whole name.
_SECRET_ATTRIBUTE = re.compile(
    r"^(password|passwd|passphrase|pwd|secret|sharedsecret|key|authkey|privkey|keypassword"
    r"|community|token|psk|bgppassword|ospfkey)$",
    re.IGNORECASE,
)
SECRET_REMOVED = "<secret removed>"


class AciExportClient(Protocol):
    async def get(
        self, credentials: AciCredentials, path: str, *, params: dict[str, Any] | None = None
    ) -> Any: ...

    async def query_class(
        self,
        credentials: AciCredentials,
        class_name: str,
        *,
        query_filter: str | None = None,
        max_objects: int = ...,
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class AciConfigExport:
    """``files`` by relative path, ``errors`` by the path they would have had."""

    files: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    tenants: tuple[str, ...] = ()


def normalize_mo(mo: dict[str, Any]) -> dict[str, Any]:
    """A copy of one managed-object tree without volatile attributes, children sorted."""
    result: dict[str, Any] = {}
    for class_name, body in mo.items():
        if not isinstance(body, dict):
            result[class_name] = body
            continue
        normalized = dict(body)
        attributes = body.get("attributes")
        if isinstance(attributes, dict):
            normalized["attributes"] = {
                k: (SECRET_REMOVED if v and _SECRET_ATTRIBUTE.match(k) else v)
                for k, v in attributes.items()
                if k not in _VOLATILE
            }
        children = body.get("children")
        if isinstance(children, list):
            normalized["children"] = sorted(
                (normalize_mo(c) if isinstance(c, dict) else c for c in children), key=_child_key
            )
        result[class_name] = normalized
    return result


def _child_key(child: Any) -> tuple[str, str]:
    if not isinstance(child, dict) or not child:
        return ("", json.dumps(child, sort_keys=True, default=str))
    class_name = next(iter(child))
    body = child[class_name]
    attributes = body.get("attributes") if isinstance(body, dict) else None
    attributes = attributes if isinstance(attributes, dict) else {}
    ident = text(attributes.get("rn")) or text(attributes.get("dn")) or text(attributes.get("name"))
    return (class_name, ident or json.dumps(child, sort_keys=True, default=str))


class AciConfigExportService:
    """Read-only configuration export for one APIC source (credentials already resolved)."""

    def __init__(self, client: AciExportClient, credentials: AciCredentials) -> None:
        self._client = client
        self._credentials = credentials

    async def export(
        self,
        *,
        tenants: tuple[str, ...] | None = None,
        include_access_policies: bool = True,
    ) -> AciConfigExport:
        """Read the selected tenants (``None`` = all) and optionally the access policies."""
        available = sorted(
            name
            for row in await self._client.query_class(
                self._credentials, "fvTenant", max_objects=MAX_TENANTS
            )
            if (name := text(row.get("name")))
        )
        if tenants is not None:
            unknown = sorted(set(tenants) - set(available))
            if unknown:
                raise AciValidationError(f"Tenant(s) not found on the APIC: {', '.join(unknown)}")
            selected = [name for name in available if name in set(tenants)]
        else:
            selected = available
        if not selected and not include_access_policies:
            raise AciValidationError("Nothing to export: no tenant selected and no access policies")

        gate = asyncio.Semaphore(MAX_PARALLEL_READS)
        jobs: list[tuple[str, str | None, str]] = [
            (f"tenants/{name}.json", name, f"/api/mo/uni/tn-{name}.json") for name in selected
        ]
        if include_access_policies:
            jobs.append((ACCESS_POLICIES_FILE, None, "/api/mo/uni/infra.json"))

        async def read(
            label: str, name: str | None, path: str
        ) -> tuple[str, str | None, str | None]:
            if name is not None and not _SAFE_NAME.match(name):
                return label, None, "the tenant name is not safe to use as a file name"
            async with gate:
                try:
                    body = await self._client.get(
                        self._credentials, path, params=dict(_SUBTREE_PARAMS)
                    )
                except AciError as exc:
                    return label, None, str(exc)
            return (label, *_render(body))

        files: dict[str, str] = {}
        errors: dict[str, str] = {}
        for label, content, error in await asyncio.gather(*[read(*job) for job in jobs]):
            if content is not None:
                files[label] = content
            else:
                errors[label] = error or "unknown error"
        return AciConfigExport(files=files, errors=errors, tenants=tuple(selected))


def _render(body: Any) -> tuple[str | None, str | None]:
    """``(json text, None)`` for an APIC answer holding one object, else ``(None, reason)``."""
    imdata = body.get("imdata") if isinstance(body, dict) else None
    if not isinstance(imdata, list):
        return None, "the APIC answered without an object list"
    if not imdata or not isinstance(imdata[0], dict):
        return None, "the APIC returned no object (does it exist, and may this user read it?)"
    return json.dumps(normalize_mo(imdata[0]), indent=2, sort_keys=True) + "\n", None
