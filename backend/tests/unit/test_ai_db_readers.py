"""The DB-backed readers behind the assistant tools re-check RBAC as the calling user.

No database: ``SessionLocal`` is replaced by a dummy session and the services they delegate to by
fakes, so only the readers' own permission and visibility rules are under test.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from core.domain_exceptions import AccessDeniedError, NotFoundError
from services.ai_assistant import (
    inventory_reader,
    run_reader,
    template_reader,
    workflow_reader,
)
from services.ai_assistant.exceptions import AiSettingsValidationError
from services.ai_assistant.providers.anthropic_provider import AnthropicProvider
from services.ai_assistant.providers.gemini_provider import GeminiProvider
from services.ai_assistant.providers.openai_compat_provider import OpenAiCompatProvider
from services.ai_assistant.providers.registry import build_provider
from services.ai_assistant.tools.inventory_tools import (
    InventoryAccessError,
    InventoryNotFoundError,
)
from services.ai_assistant.tools.run_tools import RunAccessError
from services.ai_assistant.tools.template_tools import TemplatePermissionError
from services.ai_assistant.tools.workflow_tools import ReferencePermissionError
from services.auth.rbac_service import RBACService
from services.templates.exceptions import TemplateNotFoundError


def run(coro: Any) -> Any:
    return asyncio.run(coro)


@contextmanager
def _dummy_session():
    yield object()


@pytest.fixture(autouse=True)
def _no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    for module in (inventory_reader, run_reader, template_reader, workflow_reader):
        monkeypatch.setattr(module, "SessionLocal", _dummy_session)


@pytest.fixture
def permissions(monkeypatch: pytest.MonkeyPatch) -> set[tuple[str, str]]:
    """The (resource, action) pairs the calling user holds."""
    granted: set[tuple[str, str]] = set()
    monkeypatch.setattr(
        RBACService,
        "has_permission",
        lambda self, _uid, resource, action: (resource, action) in granted,
    )
    monkeypatch.setattr(RBACService, "__init__", lambda self, _db: None)
    return granted


# -- runs ------------------------------------------------------------------------------------


class _RunServiceStub:
    behaviour: Callable[[], Any] = staticmethod(lambda: SimpleNamespace(workflow_id=1))

    def __init__(self, _db: Any) -> None: ...

    def get_run(self, run_id: int, user_id: int) -> Any:
        return type(self).behaviour()

    def list_events(self, run_id: int, user_id: int, limit: int) -> Any:
        type(self).behaviour()
        return SimpleNamespace(events=[])

    def get_run_artifact(self, run_id: int, artifact_id: str, user_id: int) -> Any:
        raise NotFoundError("artifact")


@pytest.fixture
def run_service(monkeypatch: pytest.MonkeyPatch) -> type[_RunServiceStub]:
    monkeypatch.setattr(run_reader, "RunService", _RunServiceStub)
    _RunServiceStub.behaviour = staticmethod(lambda: SimpleNamespace(workflow_id=1))
    return _RunServiceStub


def _every_run_call(reader: run_reader.DbRunReader) -> list[Callable[[], Any]]:
    return [
        lambda: run(reader.get_run(1)),
        lambda: run(reader.list_events(1, 10, None)),
        lambda: run(reader.get_artifact(1, "a")),
        lambda: run(reader.get_workflow(1)),
    ]


def test_run_reader_requires_workflow_runs_read(
    permissions: set, run_service: type[_RunServiceStub]
) -> None:
    for call in _every_run_call(run_reader.DbRunReader(5)):
        with pytest.raises(RunAccessError):
            call()


@pytest.mark.parametrize("error", [NotFoundError("run"), AccessDeniedError("private")])
def test_a_missing_or_private_run_is_indistinguishable(
    permissions: set, run_service: type[_RunServiceStub], error: Exception
) -> None:
    permissions.add(("workflow_runs", "read"))

    def boom() -> Any:
        raise error

    run_service.behaviour = staticmethod(boom)

    for call in _every_run_call(run_reader.DbRunReader(5)):
        with pytest.raises(RunAccessError):
            call()


def test_an_unknown_artifact_is_none_and_the_workflow_needs_workflows_read(
    permissions: set, run_service: type[_RunServiceStub]
) -> None:
    permissions.add(("workflow_runs", "read"))
    reader = run_reader.DbRunReader(5)

    assert run(reader.get_artifact(1, "missing")) is None
    assert run(reader.get_workflow(1)) is None  # no workflows:read


# -- templates -------------------------------------------------------------------------------


def test_template_reader_requires_templates_read(permissions: set) -> None:
    reader = template_reader.DbTemplateReader(5)

    with pytest.raises(TemplatePermissionError):
        run(reader.list_templates(None, 10))
    with pytest.raises(TemplatePermissionError):
        run(reader.get_template(1))


def test_template_reader_maps_not_found_to_none(
    permissions: set, monkeypatch: pytest.MonkeyPatch
) -> None:
    permissions.add(("templates", "read"))

    class Service:
        def __init__(self, _db: Any) -> None: ...

        def get_template(self, template_id: int) -> Any:
            raise TemplateNotFoundError(template_id)

        def list_templates(self, search: str | None = None) -> list[dict[str, Any]]:
            return [{"id": i} for i in range(5)]

    monkeypatch.setattr(template_reader, "TemplatesService", Service)
    reader = template_reader.DbTemplateReader(5)

    assert run(reader.get_template(9)) is None
    assert run(reader.list_templates(None, 2)) == [{"id": 0}, {"id": 1}]


# -- workflow references ---------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["credentials", "git_repositories", "inventories"])
def test_reference_kinds_each_need_their_own_read_permission(permissions: set, kind: str) -> None:
    with pytest.raises(ReferencePermissionError):
        run(workflow_reader.DbReferenceReader(5, "tester").list_references(kind))


def test_sources_listing_skips_source_types_the_user_cannot_read(
    permissions: set, monkeypatch: pytest.MonkeyPatch
) -> None:
    permissions.add(("sources.nautobot", "read"))

    class Settings:
        def __init__(self, _db: Any) -> None: ...

        def list_all(self, key_prefix: str) -> list[Any]:
            return [SimpleNamespace(key=f"{key_prefix}main")]

    monkeypatch.setattr(workflow_reader, "SettingsRepository", Settings)

    found = run(workflow_reader.DbReferenceReader(5, "tester").list_references("sources"))

    assert [row["type"] for row in found] == ["nautobot"]


def test_unknown_reference_kind_lists_nothing(permissions: set) -> None:
    assert run(workflow_reader.DbReferenceReader(5, "t").list_references("nope")) == []


# -- inventory -------------------------------------------------------------------------------


def test_inventory_reader_requires_nautobot_read(permissions: set) -> None:
    reader = inventory_reader.DbInventoryReader(5, "tester", "nautobot")

    for call in (
        lambda: run(reader.list_inventories()),
        lambda: run(reader.resolve_inventory(1)),
        lambda: run(reader.search_devices("sw", 5)),
        lambda: run(reader.get_device_attributes("d", None)),
    ):
        with pytest.raises(InventoryAccessError):
            call()


def test_an_unknown_nautobot_source_is_an_access_error(
    permissions: set, monkeypatch: pytest.MonkeyPatch
) -> None:
    permissions.add(("sources.nautobot", "read"))

    def unknown(_source_id: str, _db: Any) -> Any:
        raise ValueError("no such source")

    monkeypatch.setattr(inventory_reader, "nautobot_credentials_from_source_id", unknown)

    with pytest.raises(InventoryAccessError):
        run(inventory_reader.DbInventoryReader(5, "tester", "nope").list_inventories())


def test_another_users_private_inventory_looks_like_a_missing_one(
    permissions: set, monkeypatch: pytest.MonkeyPatch
) -> None:
    permissions.add(("sources.nautobot", "read"))
    monkeypatch.setattr(
        inventory_reader, "nautobot_credentials_from_source_id", lambda *_a: object()
    )

    class Inventories:
        def get_inventory(self, inventory_id: int, username: str) -> Any:
            if inventory_id == 1:
                raise PermissionError
            return {"id": inventory_id, "is_active": inventory_id != 3}

    monkeypatch.setattr(
        inventory_reader.service_factory,
        "build_inventory_service",
        lambda _db: Inventories(),
    )
    reader = inventory_reader.DbInventoryReader(5, "tester", "nautobot")

    for inventory_id in (1, 3):  # private to someone else, inactive
        with pytest.raises(InventoryNotFoundError):
            run(reader.resolve_inventory(inventory_id))


# -- provider registry -----------------------------------------------------------------------


def test_registry_builds_each_provider_and_rejects_the_rest() -> None:
    assert isinstance(build_provider("anthropic", api_key="k", base_url=None), AnthropicProvider)
    assert isinstance(build_provider("gemini", api_key="k", base_url=None), GeminiProvider)
    assert isinstance(
        build_provider("openai_compat", api_key="", base_url="http://10.0.0.5/v1"),
        OpenAiCompatProvider,
    )
    with pytest.raises(AiSettingsValidationError):
        build_provider("openai_compat", api_key="", base_url=None)
    with pytest.raises(AiSettingsValidationError):
        build_provider("nonsense", api_key="k", base_url=None)
