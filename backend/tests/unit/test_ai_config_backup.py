"""Config backups from git for Ask the Net (doc/plans/AI_CONFIG_FROM_GIT.md)."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from git import Repo

from services.ai_assistant import config_backup as cb
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.device_access import DeviceNotFoundError, ResolvedDevice
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore
from services.ai_assistant.surfaces import build_general_session
from services.ai_assistant.tools import config_backup_tools as tools
from services.ai_assistant.tools.base import ToolContext
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY

DEVICE = ResolvedDevice("nb1", "dev-1", "LAB", "10.1.2.3", "cisco_ios", "cisco_ios")
BAG = {"location": {"name": "Berlin"}}
RUNNING = "{nautobot.location.name}/{device.name}.running.cfg"
REPO = {
    "name": "backups",
    "branch": "main",
    "is_active": True,
    "last_sync": None,
    "config_path_running": RUNNING,
    "config_path_startup": "{nautobot.location.name}/{device.name}.startup.cfg",
}


class Resolver:
    def __init__(self, error=None) -> None:
        self.error = error

    async def resolve_without_address(self, name):
        if self.error:
            raise self.error
        return DEVICE


def _reader(root: Path, repos=None, bag=BAG, perm=None):
    @asynccontextmanager
    async def checkout(_repo):
        yield root

    async def attributes(_device):
        return bag

    return cb.DbConfigBackupReader(
        7,
        Resolver(),
        fetch_attributes=attributes,
        checkout=checkout,
        load_repositories=lambda: [REPO] if repos is None else repos,
        check_permission=perm or (lambda: None),
        check_rate=lambda: None,
    )


def _git_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = Repo.init(tmp_path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "t")
        cw.set_value("user", "email", "t@example.com")
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    repo.index.add(list(files))
    repo.index.commit("backup")
    return tmp_path


def _read(reader, device="LAB", kind="running", repo=None):
    return asyncio.run(reader.read(device, kind, repo))


# -- pure parts ---------------------------------------------------------------------------------


def test_render_path_uses_the_nautobot_location() -> None:
    ctx = cb.build_device_context(DEVICE, BAG)

    assert cb.render_path(RUNNING, ctx) == "Berlin/LAB.running.cfg"


def test_render_path_error_names_the_placeholder_not_values() -> None:
    ctx = cb.build_device_context(DEVICE, {"location": None})

    with pytest.raises(cb.ConfigBackupError) as err:
        cb.render_path(RUNNING, ctx)

    assert "{nautobot.location.name}" in str(err.value)
    assert "LAB" not in str(err.value)


def test_a_location_name_cannot_escape_the_repository(tmp_path: Path) -> None:
    ctx = cb.build_device_context(DEVICE, {"location": {"name": "../../etc"}})

    with pytest.raises(cb.ConfigBackupError):
        cb.render_path(RUNNING, ctx)
    # a harmless-looking name with a separator stays below the template's own directory
    ok = cb.build_device_context(DEVICE, {"location": {"name": "a/b"}})
    cb.contain(tmp_path, cb.render_path(RUNNING, ok))


@pytest.mark.parametrize("relative", ["../x", "/etc/passwd", ".git/config", "a/../../x"])
def test_contain_refuses_escapes(tmp_path: Path, relative: str) -> None:
    with pytest.raises(cb.ConfigBackupError):
        cb.contain(tmp_path, relative)


def test_contain_refuses_a_symlinked_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(outside, root / "link")

    with pytest.raises(cb.ConfigBackupError):
        cb.contain(root, "link/x.cfg")


def test_read_refuses_symlink_directory_and_bad_utf8(tmp_path: Path) -> None:
    real = tmp_path / "real.cfg"
    real.write_text("hostname LAB")
    os.symlink(real, tmp_path / "link.cfg")
    (tmp_path / "dir").mkdir()
    (tmp_path / "bad.cfg").write_bytes(b"\xff\xfe\x00bad")

    for name in ("link.cfg", "dir", "bad.cfg", "missing.cfg"):
        with pytest.raises(cb.ConfigBackupError):
            cb.read_backup_text(tmp_path / name)
    assert cb.read_backup_text(real) == ("hostname LAB", False)


def test_select_repository_rules() -> None:
    other = {**REPO, "name": "other"}
    no_startup = {**REPO, "config_path_startup": None, "name": "n"}

    assert cb.select_repository([REPO], "running", None) is REPO
    assert cb.select_repository([REPO, other], "running", "other") is other
    with pytest.raises(cb.ConfigBackupError, match="More than one"):
        cb.select_repository([REPO, other], "running", None)
    with pytest.raises(cb.ConfigBackupError, match="No git repository"):
        cb.select_repository([no_startup], "startup", None)
    with pytest.raises(cb.ConfigBackupError, match="named 'zzz'"):
        cb.select_repository([REPO], "running", "zzz")
    with pytest.raises(cb.ConfigBackupError):
        cb.select_repository([{**REPO, "is_active": False}], "running", None)


# -- the reader ---------------------------------------------------------------------------------


def test_reads_the_file_with_its_commit_time(tmp_path: Path) -> None:
    root = _git_repo(tmp_path, {"Berlin/LAB.running.cfg": "hostname LAB\n"})

    backup = _read(_reader(root))

    assert backup.text == "hostname LAB\n"
    assert backup.repository == "backups"
    assert backup.relative_path == "Berlin/LAB.running.cfg"
    assert backup.committed_at is not None


def test_a_missing_file_is_a_clear_error(tmp_path: Path) -> None:
    root = _git_repo(tmp_path, {"Berlin/other.running.cfg": "x"})

    with pytest.raises(cb.ConfigBackupError, match="No backup file"):
        _read(_reader(root))


def test_no_template_means_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(cb.ConfigBackupError, match="No git repository"):
        _read(_reader(tmp_path, repos=[{**REPO, "config_path_running": None}]))


def test_device_without_location_names_the_placeholder(tmp_path: Path) -> None:
    with pytest.raises(cb.ConfigBackupError, match="location"):
        _read(_reader(tmp_path, bag={}))


def test_unknown_device_message_passes_through(tmp_path: Path) -> None:
    reader = _reader(tmp_path)
    reader._resolver = Resolver(DeviceNotFoundError())

    with pytest.raises(cb.ConfigBackupError, match="No device"):
        _read(reader)


def test_permission_is_checked_on_every_call(tmp_path: Path) -> None:
    def deny() -> None:
        raise cb.ConfigBackupDeniedError

    reader = _reader(tmp_path, perm=deny)

    with pytest.raises(cb.ConfigBackupDeniedError):
        _read(reader)
    with pytest.raises(cb.ConfigBackupDeniedError):
        asyncio.run(reader.list_repositories())


def test_checkout_failure_hides_the_cause(tmp_path: Path) -> None:
    @asynccontextmanager
    async def boom(_repo):
        raise RuntimeError("https://user:token@git.example/x.git failed")
        yield

    reader = _reader(tmp_path)
    reader._checkout = boom

    with pytest.raises(cb.ConfigBackupError) as err:
        _read(reader)

    assert "token" not in str(err.value) and "example" not in str(err.value)


def test_list_repositories_omits_paths_and_urls(tmp_path: Path) -> None:
    repos = asyncio.run(_reader(tmp_path).list_repositories())

    assert repos == [cb.BackupRepository("backups", "main", ("running", "startup"), None)]


# -- tools --------------------------------------------------------------------------------------


class FakeReader:
    def __init__(self, backup=None, error=None) -> None:
        self.backup, self.error, self.calls = backup, error, []

    async def list_repositories(self):
        return [cb.BackupRepository("backups", "main", ("running",), None)]

    async def read(self, device, kind, repository):
        self.calls.append((device, kind, repository))
        if self.error:
            raise self.error
        return self.backup


def _ctx(reader, *, content=True, secrets=("hunter2hunter2",)):
    redactor = Redactor()
    redactor.add_known_secrets(secrets)
    return ToolContext(
        user_id=7,
        redactor=redactor,
        extras={
            tools.CONFIG_READER_KEY: reader,
            RESULT_STORE_KEY: ResultStore(InMemoryResultBackend()),
        },
        sharing=SharingPolicy(inventory=True, content=content),
    )


def _call(name, ctx, **kwargs):
    tool = next(t for t in tools.build_config_backup_tools() if t.name == name)
    return asyncio.run(tool.handler(ctx, tool.input_model(**kwargs)))


BACKUP = cb.ConfigBackup(
    "enable secret hunter2hunter2\n" + "interface x\n" * 1000,
    "backups",
    "Berlin/LAB.running.cfg",
    "2026-10-30T10:00:00+00:00",
)


def test_get_config_backup_redacts_stores_and_reports_age() -> None:
    ctx = _ctx(FakeReader(BACKUP))

    out = _call("get_config_backup", ctx, device="LAB", kind="startup")
    data = json.loads(out.content)

    assert "hunter2hunter2" not in out.content
    assert data["handle"].startswith("res_")
    assert data["age"] and data["committed_at"] == BACKUP.committed_at
    assert "not the live device" in data["source"]
    stored = asyncio.run(ctx.extras[RESULT_STORE_KEY].get(7, data["handle"]))
    assert "hunter2hunter2" not in (stored.text or "") and stored.text
    assert "config:LAB" in ctx.audit_refs
    assert ctx.extras[tools.CONFIG_READER_KEY].calls == [("LAB", "startup", None)]


def test_get_config_backup_needs_the_content_opt_in() -> None:
    reader = FakeReader(BACKUP)

    out = _call("get_config_backup", _ctx(reader, content=False), device="LAB")

    assert json.loads(out.content)["not_shared"] == "content_data"
    assert reader.calls == []


def test_get_config_backup_error_is_the_fixed_message() -> None:
    out = _call(
        "get_config_backup",
        _ctx(FakeReader(error=cb.ConfigBackupError("No backup file exists for this device"))),
        device="LAB",
    )

    assert out.is_error and out.content == "No backup file exists for this device"


@pytest.mark.parametrize("device", ["../x", "a b", "", "x" * 101])
def test_device_name_is_pattern_checked(device: str) -> None:
    with pytest.raises(ValueError):
        tools.GetConfigBackupInput(device=device)


def test_the_model_has_no_path_or_ref_parameter() -> None:
    assert set(tools.GetConfigBackupInput.model_fields) == {"device", "kind", "repository"}
    with pytest.raises(ValueError):
        tools.GetConfigBackupInput(device="LAB", path="/etc/passwd")


def test_list_config_backups_shows_names_only() -> None:
    out = _call("list_config_backups", _ctx(FakeReader()))

    assert json.loads(out.content) == {
        "repositories": [
            {"name": "backups", "branch": "main", "kinds": ["running"], "last_sync": None}
        ]
    }


# -- surface ------------------------------------------------------------------------------------


def _session(**overrides):
    base = {
        "user_id": 7,
        "reader": object(),
        "store": ResultStore(InMemoryResultBackend()),
        "sharing": SharingPolicy(inventory=True, content=True),
        "may_query_batfish": True,
    }
    base.update(overrides)
    return build_general_session(**base)


def test_tools_and_prompt_are_absent_without_a_reader() -> None:
    session = _session()

    assert not {s.name for s in session.toolbox.specs()} & {
        "list_config_backups",
        "get_config_backup",
    }
    assert "get_config_backup" not in session.system


def test_tools_and_prompt_are_offered_with_a_reader() -> None:
    session = _session(config_reader=FakeReader())

    names = {s.name for s in session.toolbox.specs()}

    assert {"list_config_backups", "get_config_backup"} <= names
    assert "get_config_backup" in session.system
    assert not [n for n in names if n.startswith("propose")]


# -- review findings (doc/analysis/REVIEW.md) ---------------------------------------------------


def test_contain_refuses_a_symlink_to_another_file_in_the_same_repository(tmp_path: Path) -> None:
    (tmp_path / "Berlin").mkdir()
    (tmp_path / "Berlin" / "OTHER.running.cfg").write_text("hostname OTHER")
    os.symlink(tmp_path / "Berlin" / "OTHER.running.cfg", tmp_path / "Berlin" / "LAB.running.cfg")

    with pytest.raises(cb.ConfigBackupError, match="symbolic link"):
        cb.contain(tmp_path, "Berlin/LAB.running.cfg")


def test_contain_refuses_a_symlinked_directory_inside_the_repository(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "LAB.cfg").write_text("x")
    os.symlink(tmp_path / "real", tmp_path / "Berlin")

    with pytest.raises(cb.ConfigBackupError, match="symbolic link"):
        cb.contain(tmp_path, "Berlin/LAB.cfg")


def test_reader_does_not_return_another_devices_file_through_a_link(tmp_path: Path) -> None:
    root = _git_repo(tmp_path, {"Berlin/OTHER.running.cfg": "hostname OTHER\n"})
    os.symlink(root / "Berlin" / "OTHER.running.cfg", root / "Berlin" / "LAB.running.cfg")

    with pytest.raises(cb.ConfigBackupError):
        _read(_reader(root))


def test_a_file_over_the_cap_is_cut_on_a_line_and_flagged(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cb, "MAX_CONFIG_CHARS", 100)
    path = tmp_path / "big.cfg"
    path.write_text("line of text\n" * 20, encoding="utf-8")

    text, truncated = cb.read_backup_text(path)

    assert truncated and len(text) <= 100
    assert text.endswith("line of text")


def test_the_read_is_not_kept_in_the_knowledge_cache(tmp_path: Path) -> None:
    from services.ai_assistant import knowledge_loader

    path = tmp_path / "x.cfg"
    path.write_text("hostname LAB")
    before = dict(knowledge_loader._cache)

    cb.read_backup_text(path)

    assert knowledge_loader._cache == before


def test_a_device_without_a_management_address_still_resolves_for_a_backup() -> None:
    from models.sources_nautobot import DeviceInfo
    from services.ai_assistant.device_access import select_device

    found = [("nb1", DeviceInfo(id="d1", name="LAB", primary_ip4=None))]

    device = select_device("LAB", found, require_address=False)

    assert device.host == "" and device.name == "LAB"
    with pytest.raises(Exception, match="management address"):
        select_device("LAB", found)
    assert cb.build_device_context(device, BAG).primary_ip4 is None


def test_a_secret_straddling_the_preview_cut_does_not_reach_the_model() -> None:
    secret = "hunter2hunter2"
    # the secret starts 5 characters before the preview limit
    text = "x" * (tools.PREVIEW_CHARS - 5) + secret + "\nend\n"
    backup = cb.ConfigBackup(text, "backups", "p", None)
    ctx = _ctx(FakeReader(backup), secrets=(secret,))

    out = _call("get_config_backup", ctx, device="LAB")

    assert secret not in out.content and secret[:5] not in out.content


def test_a_truncated_backup_says_so_in_the_answer_and_the_stored_text() -> None:
    backup = cb.ConfigBackup("hostname LAB\n", "backups", "p", None, truncated=True)
    ctx = _ctx(FakeReader(backup))

    out = _call("get_config_backup", ctx, device="LAB")
    data = json.loads(out.content)

    assert "longer than the size limit" in data["truncated"]
    stored = asyncio.run(ctx.extras[RESULT_STORE_KEY].get(7, data["handle"]))
    assert "backup truncated" in (stored.text or "")
