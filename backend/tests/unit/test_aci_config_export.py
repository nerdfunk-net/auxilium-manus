"""AciConfigExportService: tenant and access-policy configuration as stable JSON files."""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any

from services.aci.common.exceptions import AciAPIError, AciValidationError
from services.aci.config_export_service import (
    MAX_PARALLEL_READS,
    AciConfigExportService,
    normalize_mo,
)
from services.aci.credentials import AciCredentials

CREDS = AciCredentials(base_url="https://10.10.20.14", username="admin", password="pw")


def _tenant(name: str, children: list | None = None) -> dict:
    return {
        "fvTenant": {
            "attributes": {
                "dn": f"uni/tn-{name}",
                "name": name,
                "descr": "",
                "modTs": "2026-01-01",
            },
            "children": children if children is not None else [],
        }
    }


def _body(*objects: dict) -> dict:
    return {"totalCount": str(len(objects)), "imdata": list(objects)}


class FakeClient:
    def __init__(self, tenants=("Heroes", "SnV"), bodies=None, errors=None) -> None:
        self.tenants = list(tenants)
        self.bodies = bodies or {}
        self.errors = errors or {}
        self.gets: list[tuple[str, dict[str, Any]]] = []
        self.queries: list[str] = []
        self.active = 0
        self.peak = 0

    async def query_class(self, credentials, class_name, **kwargs):
        self.queries.append(class_name)
        return [{"dn": f"uni/tn-{t}", "name": t} for t in self.tenants]

    async def get(self, credentials, path, *, params=None):
        self.gets.append((path, params or {}))
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(0)
            if path in self.errors:
                raise self.errors[path]
            if path in self.bodies:
                return self.bodies[path]
            name = path.removeprefix("/api/mo/uni/tn-").removesuffix(".json")
            if path.endswith("/uni/infra.json"):
                return _body({"infraInfra": {"attributes": {"dn": "uni/infra"}, "children": []}})
            return _body(_tenant(name))
        finally:
            self.active -= 1


def service(client: FakeClient) -> AciConfigExportService:
    return AciConfigExportService(client, CREDS)  # type: ignore[arg-type]


class NormalizeTests(unittest.TestCase):
    def test_volatile_attributes_are_removed_at_every_level(self) -> None:
        mo = {
            "fvTenant": {
                "attributes": {"name": "T", "modTs": "x", "lcOwn": "local", "uid": "1"},
                "children": [
                    {"fvAp": {"attributes": {"name": "A", "createTs": "y", "childAction": "z"}}}
                ],
            }
        }
        out = normalize_mo(mo)
        self.assertEqual(out["fvTenant"]["attributes"], {"name": "T"})
        self.assertEqual(out["fvTenant"]["children"][0]["fvAp"]["attributes"], {"name": "A"})

    def test_children_are_sorted_so_the_apic_order_does_not_matter(self) -> None:
        def child(cls: str, rn: str) -> dict:
            return {cls: {"attributes": {"rn": rn}}}

        a = {
            "fvTenant": {
                "attributes": {},
                "children": [child("fvAp", "ap-B"), child("fvBD", "BD-A"), child("fvAp", "ap-A")],
            }
        }
        b = {
            "fvTenant": {
                "attributes": {},
                "children": [child("fvAp", "ap-A"), child("fvAp", "ap-B"), child("fvBD", "BD-A")],
            }
        }
        self.assertEqual(normalize_mo(a), normalize_mo(b))
        self.assertEqual(
            [next(iter(c)) for c in normalize_mo(a)["fvTenant"]["children"]],
            ["fvAp", "fvAp", "fvBD"],
        )

    def test_children_without_a_name_or_rn_still_sort_deterministically(self) -> None:
        x = {"fvRsCtx": {"attributes": {"tnFvCtxName": "b"}}}
        y = {"fvRsCtx": {"attributes": {"tnFvCtxName": "a"}}}
        one = normalize_mo({"fvBD": {"attributes": {}, "children": [x, y]}})
        two = normalize_mo({"fvBD": {"attributes": {}, "children": [y, x]}})
        self.assertEqual(one, two)

    def test_the_input_is_not_modified(self) -> None:
        mo = _tenant("T", [{"fvAp": {"attributes": {"name": "A", "modTs": "x"}}}])
        before = json.dumps(mo)
        normalize_mo(mo)
        self.assertEqual(json.dumps(mo), before)

    def test_an_object_that_is_not_a_mo_is_returned_unchanged_in_shape(self) -> None:
        self.assertEqual(normalize_mo({"x": 1}), {"x": 1})


class ExportTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_file_per_tenant_and_one_for_the_access_policies(self) -> None:
        export = await service(FakeClient()).export()
        self.assertEqual(
            sorted(export.files),
            ["access-policies.json", "tenants/Heroes.json", "tenants/SnV.json"],
        )
        self.assertEqual(export.errors, {})
        self.assertEqual(export.tenants, ("Heroes", "SnV"))

    async def test_a_file_is_stable_json_with_a_trailing_newline(self) -> None:
        export = await service(FakeClient(tenants=("Heroes",))).export()
        text = export.files["tenants/Heroes.json"]
        self.assertTrue(text.endswith("}\n"))
        self.assertEqual(
            json.loads(text)["fvTenant"]["attributes"],
            {"dn": "uni/tn-Heroes", "name": "Heroes", "descr": ""},
        )
        self.assertEqual(text, json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n")

    async def test_the_requests_ask_for_the_full_configuration_subtree(self) -> None:
        client = FakeClient(tenants=("Heroes",))
        await service(client).export()
        paths = {p: params for p, params in client.gets}
        self.assertEqual(set(paths), {"/api/mo/uni/tn-Heroes.json", "/api/mo/uni/infra.json"})
        for params in paths.values():
            self.assertEqual(params, {"rsp-subtree": "full", "rsp-prop-include": "config-only"})

    async def test_a_tenant_filter_exports_only_those_tenants(self) -> None:
        client = FakeClient()
        export = await service(client).export(tenants=("SnV",))
        self.assertEqual(sorted(export.files), ["access-policies.json", "tenants/SnV.json"])
        self.assertEqual(export.tenants, ("SnV",))

    async def test_an_unknown_tenant_in_the_filter_is_a_validation_error(self) -> None:
        with self.assertRaises(AciValidationError) as caught:
            await service(FakeClient()).export(tenants=("SnV", "Nope"))
        self.assertIn("Nope", str(caught.exception))

    async def test_access_policies_can_be_left_out(self) -> None:
        client = FakeClient(tenants=("Heroes",))
        export = await service(client).export(include_access_policies=False)
        self.assertEqual(list(export.files), ["tenants/Heroes.json"])
        self.assertNotIn("/api/mo/uni/infra.json", [p for p, _ in client.gets])

    async def test_nothing_to_export_is_a_validation_error(self) -> None:
        with self.assertRaises(AciValidationError):
            await service(FakeClient(tenants=())).export(include_access_policies=False)

    async def test_a_failed_read_is_reported_and_the_other_files_are_still_produced(self) -> None:
        client = FakeClient(
            errors={"/api/mo/uni/tn-SnV.json": AciAPIError("too big", http_status=400)}
        )
        export = await service(client).export()
        self.assertEqual(sorted(export.files), ["access-policies.json", "tenants/Heroes.json"])
        self.assertEqual(list(export.errors), ["tenants/SnV.json"])
        self.assertIn("too big", export.errors["tenants/SnV.json"])

    async def test_an_empty_answer_is_an_error_not_an_empty_file(self) -> None:
        client = FakeClient(tenants=("Heroes",), bodies={"/api/mo/uni/tn-Heroes.json": _body()})
        export = await service(client).export(include_access_policies=False)
        self.assertEqual(export.files, {})
        self.assertIn("tenants/Heroes.json", export.errors)

    async def test_a_body_that_is_not_an_apic_answer_is_an_error(self) -> None:
        client = FakeClient(
            tenants=("Heroes",), bodies={"/api/mo/uni/tn-Heroes.json": {"imdata": "x"}}
        )
        export = await service(client).export(include_access_policies=False)
        self.assertIn("tenants/Heroes.json", export.errors)

    async def test_a_tenant_name_that_is_not_safe_for_a_path_is_never_requested(self) -> None:
        client = FakeClient(tenants=("good", "../evil", "a/b", 'x"y'))
        export = await service(client).export(include_access_policies=False)
        self.assertEqual(list(export.files), ["tenants/good.json"])
        self.assertEqual(len(export.errors), 3)
        self.assertEqual([p for p, _ in client.gets], ["/api/mo/uni/tn-good.json"])

    async def test_a_name_the_path_sanitizer_would_rewrite_is_never_requested(self) -> None:
        # ``.hidden`` and ``hidden`` would become one file, ``a..b`` would become ``a_b``.
        names = (".hidden", "hidden", "a..b", "trail.", "my.tenant", "-x")
        client = FakeClient(tenants=names)
        export = await service(client).export(include_access_policies=False)
        self.assertEqual(
            sorted(export.files),
            ["tenants/-x.json", "tenants/hidden.json", "tenants/my.tenant.json"],
        )
        self.assertEqual(
            sorted(export.errors),
            ["tenants/.hidden.json", "tenants/a..b.json", "tenants/trail..json"],
        )

    async def test_every_exported_path_survives_the_sink_sanitizer_unchanged(self) -> None:
        from services.workflow_context.device_template import sanitize_relative_path

        client = FakeClient(tenants=("common", "my.tenant", "a_b-c", "T1"))
        export = await service(client).export()
        for path in export.files:
            self.assertEqual(sanitize_relative_path(path), path)

    async def test_secret_attributes_with_a_value_are_replaced_empty_ones_stay(self) -> None:
        from services.aci.config_export_service import SECRET_REMOVED, normalize_mo

        body = {
            "fvTenant": {
                "attributes": {"name": "T", "key": "", "community": "public", "ownerKey": "x"},
                "children": [
                    {"bgpPeerP": {"attributes": {"addr": "10.0.0.1", "password": "hunter2"}}},
                    {"ospfIfP": {"attributes": {"authKey": "k3y", "authKeyId": "1"}}},
                ],
            }
        }
        out = normalize_mo(body)["fvTenant"]
        self.assertEqual(out["attributes"]["community"], SECRET_REMOVED)
        self.assertEqual(out["attributes"]["key"], "")  # empty stays empty
        self.assertEqual(out["attributes"]["ownerKey"], "x")  # not a secret
        peer = next(c for c in out["children"] if "bgpPeerP" in c)["bgpPeerP"]["attributes"]
        ospf = next(c for c in out["children"] if "ospfIfP" in c)["ospfIfP"]["attributes"]
        self.assertEqual(peer, {"addr": "10.0.0.1", "password": SECRET_REMOVED})
        self.assertEqual(ospf, {"authKey": SECRET_REMOVED, "authKeyId": "1"})
        self.assertNotIn("hunter2", json.dumps(out))

    async def test_reads_run_in_parallel_but_never_more_than_the_limit(self) -> None:
        client = FakeClient(tenants=tuple(f"t{i}" for i in range(12)))
        await service(client).export()
        self.assertGreater(client.peak, 1)
        self.assertLessEqual(client.peak, MAX_PARALLEL_READS)

    async def test_the_tenant_list_error_propagates(self) -> None:
        class Failing(FakeClient):
            async def query_class(self, *a, **k):
                raise AciAPIError("down", http_status=503)

        with self.assertRaises(AciAPIError):
            await service(Failing()).export()
