"""Device query service — live Nautobot GraphQL queries, no caching.

Each method queries Nautobot directly using the per-step credentials.
An instance-level device cache avoids repeated calls within one preview request.
"""

from __future__ import annotations

import logging
from typing import Any

from workflow_steps.get_nautobot_devices.models import DeviceInfo
from workflow_steps.get_nautobot_devices.nautobot.client import graphql_query

logger = logging.getLogger(__name__)

_ALL_DEVICES_QUERY = """
query all_devices {
    devices {
        id name serial
        primary_ip4 { address }
        status { name }
        device_type { model manufacturer { name } }
        role { name }
        location { name }
        tags { name }
        platform { name }
    }
}
"""


class NautobotQueryService:
    def __init__(self, nautobot_url: str, nautobot_token: str) -> None:
        self._url = nautobot_url
        self._token = nautobot_token
        self._devices_cache: list[DeviceInfo] | None = None

    async def _gql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return await graphql_query(self._url, self._token, query, variables)

    async def _get_all_devices(self) -> list[DeviceInfo]:
        if self._devices_cache is not None:
            return self._devices_cache
        result = await self._gql(_ALL_DEVICES_QUERY, {})
        raw = result.get("data", {}).get("devices", [])
        self._devices_cache = self._parse_devices(raw)
        logger.info("Fetched %s devices from Nautobot", len(self._devices_cache))
        return self._devices_cache

    # ------------------------------------------------------------------
    # Cache-based filters
    # ------------------------------------------------------------------

    async def _query_devices_by_name(
        self, name_filter: str, use_contains: bool = False
    ) -> list[DeviceInfo]:
        all_devices = await self._get_all_devices()
        if use_contains:
            needle = name_filter.lower()
            return [d for d in all_devices if d.name and needle in d.name.lower()]
        return [d for d in all_devices if d.name == name_filter]

    async def _query_devices_by_role(
        self, role_filter: str, use_negation: bool = False
    ) -> list[DeviceInfo]:
        all_devices = await self._get_all_devices()
        if use_negation:
            return [d for d in all_devices if d.role != role_filter]
        return [d for d in all_devices if d.role == role_filter]

    async def _query_devices_by_status(self, status_filter: str) -> list[DeviceInfo]:
        all_devices = await self._get_all_devices()
        return [d for d in all_devices if d.status == status_filter]

    async def _query_devices_by_tag(self, tag_filter: str) -> list[DeviceInfo]:
        all_devices = await self._get_all_devices()
        return [d for d in all_devices if tag_filter in (d.tags or [])]

    async def _query_devices_by_devicetype(
        self, devicetype_filter: str, use_negation: bool = False
    ) -> list[DeviceInfo]:
        all_devices = await self._get_all_devices()
        if use_negation:
            return [d for d in all_devices if d.device_type != devicetype_filter]
        return [d for d in all_devices if d.device_type == devicetype_filter]

    async def _query_devices_by_manufacturer(
        self, manufacturer_filter: str, use_negation: bool = False
    ) -> list[DeviceInfo]:
        all_devices = await self._get_all_devices()
        if use_negation:
            return [d for d in all_devices if d.manufacturer != manufacturer_filter]
        return [d for d in all_devices if d.manufacturer == manufacturer_filter]

    async def _query_devices_by_platform(self, platform_filter: str) -> list[DeviceInfo]:
        all_devices = await self._get_all_devices()
        return [d for d in all_devices if d.platform == platform_filter]

    async def _query_devices_by_has_primary(self, has_primary_filter: str) -> list[DeviceInfo]:
        has_primary = has_primary_filter.lower() == "true"
        all_devices = await self._get_all_devices()
        if has_primary:
            return [d for d in all_devices if d.primary_ip4]
        return [d for d in all_devices if not d.primary_ip4]

    # ------------------------------------------------------------------
    # Live GraphQL queries (location hierarchy / CIDR)
    # ------------------------------------------------------------------

    async def _query_devices_by_location(
        self,
        location_filter: str,
        use_contains: bool = False,
        use_negation: bool = False,
    ) -> list[DeviceInfo]:
        if use_negation:
            query = """
            query devices_by_location($f: [String]) {
                devices(location__n: $f) {
                    id name serial
                    primary_ip4 { address }
                    status { name }
                    device_type { model manufacturer { name } }
                    role { name }
                    location { name }
                    tags { name }
                    platform { name }
                }
            }
            """
        elif use_contains:
            query = """
            query devices_by_location($f: [String]) {
                devices(location__name__ic: $f) {
                    id name serial
                    primary_ip4 { address }
                    status { name }
                    device_type { model manufacturer { name } }
                    role { name }
                    location { name }
                    tags { name }
                    platform { name }
                }
            }
            """
        else:
            query = """
            query devices_by_location($f: [String]) {
                devices(location: $f) {
                    id name serial
                    primary_ip4 { address }
                    status { name }
                    device_type { model manufacturer { name } }
                    role { name }
                    location { name }
                    tags { name }
                    platform { name }
                }
            }
            """
        result = await self._gql(query, {"f": [location_filter]})
        return self._parse_devices(result.get("data", {}).get("devices", []))

    async def _query_devices_by_ip_prefix(
        self, prefix_filter: str, operator: str = "within_include"
    ) -> list[DeviceInfo]:
        parts = prefix_filter.strip().split(None, 1)
        cidr = parts[0]
        namespace = parts[1].strip() if len(parts) > 1 else None
        namespace_arg = f', namespace: "{namespace}"' if namespace else ""

        if operator == "within":
            prefix_arg = f'within: "{cidr}"{namespace_arg}'
        elif operator == "exact":
            prefix_arg = f'prefix: "{cidr}"{namespace_arg}'
        else:
            prefix_arg = f'within_include: "{cidr}"{namespace_arg}'

        query = f"""
        query devices_by_ip_prefix {{
            prefixes({prefix_arg}) {{
                ip_addresses {{
                    interface_assignments {{
                        interface {{
                            device {{
                                id name serial
                                primary_ip4 {{ address }}
                                status {{ name }}
                                device_type {{ model manufacturer {{ name }} }}
                                role {{ name }}
                                location {{ name }}
                                tags {{ name }}
                                platform {{ name }}
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """
        result = await self._gql(query, {})
        if "errors" in result:
            logger.error("GraphQL errors in ip_prefix query: %s", result["errors"])
            return []

        seen: dict[str, DeviceInfo] = {}
        for prefix in result.get("data", {}).get("prefixes", []):
            for ip_addr in prefix.get("ip_addresses", []):
                for assignment in ip_addr.get("interface_assignments", []):
                    device_data = (assignment.get("interface") or {}).get("device") or {}
                    device_id = device_data.get("id")
                    if device_id and device_id not in seen:
                        parsed = self._parse_devices([device_data])
                        if parsed:
                            seen[device_id] = parsed[0]
        return list(seen.values())

    async def _query_all_devices(self) -> list[DeviceInfo]:
        return await self._get_all_devices()

    # ------------------------------------------------------------------
    # Field value discovery
    # ------------------------------------------------------------------

    async def get_field_values(self, field: str) -> list[str]:
        """Return distinct values for the given field by querying Nautobot."""
        queries: dict[str, tuple[str, str]] = {
            "role": ("{ roles { name } }", "roles"),
            "status": ("{ statuses { name } }", "statuses"),
            "location": ("{ locations { name } }", "locations"),
            "tag": ("{ tags { name } }", "tags"),
            "device_type": ("{ device_types { model } }", "device_types"),
            "manufacturer": ("{ manufacturers { name } }", "manufacturers"),
            "platform": ("{ platforms { name } }", "platforms"),
        }
        if field == "has_primary":
            return ["true", "false"]
        if field in ("name", "ip_prefix"):
            return []
        if field not in queries:
            return []

        query_str, data_key = queries[field]
        result = await self._gql(query_str, {})
        items = result.get("data", {}).get(data_key, [])

        name_field = "model" if field == "device_type" else "name"
        return [item[name_field] for item in items if item.get(name_field)]

    # ------------------------------------------------------------------
    # Shared parser
    # ------------------------------------------------------------------

    def _parse_devices(self, raw: list[dict[str, Any]]) -> list[DeviceInfo]:
        result = []
        for d in raw:
            primary_ip4 = None
            if d.get("primary_ip4"):
                primary_ip4 = d["primary_ip4"].get("address")

            status = None
            if d.get("status"):
                status = d["status"].get("name")

            device_type = None
            manufacturer = None
            if d.get("device_type"):
                device_type = d["device_type"].get("model")
                if d["device_type"].get("manufacturer"):
                    manufacturer = d["device_type"]["manufacturer"].get("name")

            role = None
            if d.get("role"):
                role = d["role"].get("name")

            location = None
            if d.get("location"):
                location = d["location"].get("name")

            platform = None
            if d.get("platform"):
                platform = d["platform"].get("name")

            tags = [t["name"] for t in (d.get("tags") or []) if t.get("name")]

            result.append(
                DeviceInfo(
                    id=d.get("id", ""),
                    name=d.get("name"),
                    serial=d.get("serial"),
                    primary_ip4=primary_ip4,
                    status=status,
                    device_type=device_type,
                    manufacturer=manufacturer,
                    role=role,
                    location=location,
                    platform=platform,
                    tags=tags,
                )
            )
        return result
