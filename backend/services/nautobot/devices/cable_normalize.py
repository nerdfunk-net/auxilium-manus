"""Give polled cables one shape on every Nautobot version.

Nautobot >= 3.2 returns ``cable.interfaces`` (the interfaces at the cable's ends).
Before 3.2 that field does not exist; the far end is ``connected_endpoint``. With
normalization on, both versions end up with ``interfaces[].cable.interfaces`` and a
derived ``interfaces[].cable.far_end``. Nothing existing is changed or removed
(``connected_endpoint`` stays); the function returns a new bag.

Known difference: before 3.2 the far end is ``connected_endpoint``, where the cable
*path* ends; from 3.2 ``cable.interfaces`` holds only what the cable touches. They agree
for direct interface-to-interface cables. Through a patch panel or circuit, 3.1 names the
interface at the end of the path and 3.2 gives ``far_end = None``.
"""

from __future__ import annotations

from typing import Any


def _end(iface: dict[str, Any]) -> dict[str, Any] | None:
    """``{id, name, device}`` of an interface-like dict, or ``None`` if it is not one."""
    if not iface.get("name"):
        return None
    device = iface.get("device")
    return {"id": iface.get("id"), "name": iface["name"], "device": device}


def _cable_ends(
    iface: dict[str, Any], cable: dict[str, Any], device_ref: dict[str, Any]
) -> list[dict[str, Any]]:
    existing = cable.get("interfaces")
    if isinstance(existing, list):  # Nautobot >= 3.2 already provides the ends
        return existing
    ends = [{"id": iface.get("id"), "name": iface.get("name"), "device": device_ref}]
    endpoint = iface.get("connected_endpoint")
    if isinstance(endpoint, dict) and endpoint.get("__typename") in (None, "InterfaceType"):
        far = _end(endpoint)
        if far is not None:
            ends.append(far)
    return ends


def _far_end(iface: dict[str, Any], ends: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The one end that is not this interface; ``None`` if there is none or several."""
    others = [e for e in ends if isinstance(e, dict) and e.get("id") != iface.get("id")]
    return others[0] if len(others) == 1 else None


def normalize_cables(bag: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the ``nautobot`` bag with ``cable.interfaces`` and ``cable.far_end``."""
    interfaces = bag.get("interfaces")
    if not isinstance(interfaces, list):
        return bag
    device_ref = {"id": bag.get("id"), "name": bag.get("name")}
    result: list[Any] = []
    for iface in interfaces:
        cable = iface.get("cable") if isinstance(iface, dict) else None
        if not isinstance(cable, dict):
            result.append(iface)
            continue
        ends = _cable_ends(iface, cable, device_ref)
        result.append(
            {**iface, "cable": {**cable, "interfaces": ends, "far_end": _far_end(iface, ends)}}
        )
    return {**bag, "interfaces": result}
