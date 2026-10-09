"""Every expensive route carries its rate_limited dependency (S9, SM10, B3).

Inspecting the dependant tree avoids sleeping through real budgets.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from routers.git.operations import router as git_operations_router
from routers.netmiko import router as netmiko_router
from routers.secret_manager import router as secret_manager_router
from routers.sources.batfish.query import router as batfish_query_router
from routers.sources.ise.ops import router as ise_ops_router
from routers.sources.nautobot.ops import router as nautobot_ops_router
from routers.templates import router as templates_router


def _dependency_names(route: APIRoute) -> set[str]:
    names: set[str] = set()

    def walk(dependant) -> None:
        for sub in dependant.dependencies:
            names.add(getattr(sub.call, "__name__", ""))
            walk(sub)

    walk(route.dependant)
    return names


def _route(router, path_suffix: str, method: str) -> APIRoute:
    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path.endswith(path_suffix) and method in route.methods:
            return route
    raise AssertionError(f"no {method} route ending with {path_suffix}")


@pytest.mark.parametrize(
    ("router", "suffix", "method", "bucket"),
    [
        (git_operations_router, "/sync", "POST", "git-sync"),
        (git_operations_router, "/remove-and-sync", "POST", "git-sync"),
        (templates_router, "/render", "POST", "template-render"),
        (nautobot_ops_router, "/analyze", "GET", "nautobot-analyze"),
        (secret_manager_router, "/test", "POST", "secret-manager-test"),
    ],
)
def test_route_is_rate_limited(router, suffix: str, method: str, bucket: str) -> None:
    assert f"rate_limited_{bucket}" in _dependency_names(_route(router, suffix, method))


@pytest.mark.parametrize(
    ("router", "bucket"),
    [
        (netmiko_router, "netmiko"),
        (ise_ops_router, "ise-ops"),
        (batfish_query_router, "batfish-query"),
    ],
)
def test_every_route_of_router_is_rate_limited(router, bucket: str) -> None:
    routes = [r for r in router.routes if isinstance(r, APIRoute)]
    assert routes
    for route in routes:
        assert f"rate_limited_{bucket}" in _dependency_names(route), route.path
