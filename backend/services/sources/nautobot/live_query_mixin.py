"""Live Nautobot GraphQL queries for location / CIDR / custom-field filters.

Extracted from query_service.py to keep the cache-first query service under
the project file-size limit. Mixed into NautobotSourceQueryService.
"""

from __future__ import annotations

import logging

from models.sources_nautobot import DeviceInfo

logger = logging.getLogger(__name__)


class NautobotLiveQueryMixin:
    """Mixin providing live GraphQL query helpers used by NautobotSourceQueryService."""

    async def _query_devices_by_location(
        self,
        location_filter: str,
        use_contains: bool = False,
        use_negation: bool = False,
    ) -> list[DeviceInfo]:
        """Query devices by location using GraphQL.

        Intentionally kept as a live Nautobot call: Nautobot resolves the full
        child-location hierarchy server-side.  Replicating that logic in Python
        would require fetching and traversing the entire location tree, which is
        more expensive than a single filtered GraphQL query.

        Args:
            location_filter: Location name or ID to filter by
            use_contains: Use case-insensitive contains matching
            use_negation: Use negation (location__n) to exclude devices from this location
        """
        if not location_filter or location_filter.strip() == "":
            logger.warning("Empty location_filter provided, returning empty result")
            return []

        if use_negation:
            query = """
            query devices_by_location ($location_filter: [String]) {
                devices (location__n: $location_filter) {
                    id
                    name
                    serial
                    role {
                        name
                    }
                    location {
                        name
                    }
                    primary_ip4 {
                        address
                    }
                    status {
                        name
                    }
                    device_type {
                        model
                        manufacturer {
                            name
                        }
                    }
                    tags {
                        name
                    }
                    platform {
                        name
                        network_driver
                    }
                }
            }
            """
        elif use_contains:
            query = """
            query devices_by_location ($location_filter: [String]) {
                devices (location__name__ic: $location_filter) {
                    id
                    name
                    serial
                    role {
                        name
                    }
                    location {
                        name
                    }
                    primary_ip4 {
                        address
                    }
                    status {
                        name
                    }
                    device_type {
                        model
                        manufacturer {
                            name
                        }
                    }
                    tags {
                        name
                    }
                    platform {
                        name
                        network_driver
                    }
                }
            }
            """
        else:
            query = """
            query devices_by_location ($location_filter: [String]) {
                devices (location: $location_filter) {
                    id
                    name
                    serial
                    role {
                        name
                    }
                    location {
                        name
                    }
                    primary_ip4 {
                        address
                    }
                    status {
                        name
                    }
                    device_type {
                        model
                        manufacturer {
                            name
                        }
                    }
                    tags {
                        name
                    }
                    platform {
                        name
                        network_driver
                    }
                }
            }
            """

        variables = {"location_filter": [location_filter]}
        result = await self._nautobot.graphql_query(query, variables, self._credentials)

        logger.info(
            "GraphQL result for location query '%s': Found %s devices",
            location_filter,
            len(result.get("data", {}).get("devices", [])),
        )

        devices_data = result.get("data", {}).get("devices", [])
        return self._parse_device_data(devices_data)

    async def _query_devices_by_ip_prefix(
        self, prefix_filter: str, operator: str = "within_include"
    ) -> list[DeviceInfo]:
        """Query devices by IP prefix using GraphQL.

        Intentionally kept as a live Nautobot call: CIDR containment filtering
        (within_include / within / exact) requires server-side evaluation.

        Traverses: prefixes → ip_addresses → interface_assignments → interface → device.
        IP addresses without interface assignments are ignored.
        Devices are deduplicated by ID.

        The value may optionally include a namespace name after the CIDR, separated by
        a space (e.g. "192.168.183.0/24 Global"). When present, the namespace is added
        as an additional filter to the GraphQL query.

        Args:
            prefix_filter: CIDR notation with optional namespace
                           (e.g., "192.168.183.0/24" or "192.168.183.0/24 Global")
            operator: One of "within_include", "within", "exact"
        """
        if not prefix_filter or prefix_filter.strip() == "":
            logger.warning("Empty prefix_filter provided, returning empty result")
            return []

        # Split optional namespace: "192.168.183.0/24 Global" -> cidr + namespace
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

        logger.info(
            "ip_prefix query: cidr='%s', namespace=%s, operator=%s",
            cidr,
            namespace,
            operator,
        )

        query = f"""
        query devices_by_ip_prefix {{
            prefixes({prefix_arg}) {{
                ip_addresses {{
                    interface_assignments {{
                        interface {{
                            device {{
                                id
                                name
                                serial
                                primary_ip4 {{ address }}
                                status {{ name }}
                                device_type {{ model manufacturer {{ name }} }}
                                role {{ name }}
                                location {{ name }}
                                tags {{ name }}
                                platform {{ name network_driver }}
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """

        result = await self._nautobot.graphql_query(query, {}, self._credentials)

        if "errors" in result:
            logger.error("GraphQL errors in ip_prefix query: %s", result["errors"])
            return []

        prefixes_data = result.get("data", {}).get("prefixes", [])
        seen_ids: dict[str, DeviceInfo] = {}

        for prefix in prefixes_data:
            for ip_addr in prefix.get("ip_addresses", []):
                for assignment in ip_addr.get("interface_assignments", []):
                    interface = assignment.get("interface") or {}
                    device_data = interface.get("device") or {}
                    device_id = device_data.get("id")
                    if device_id and device_id not in seen_ids:
                        parsed = self._parse_device_data([device_data])
                        if parsed:
                            seen_ids[device_id] = parsed[0]

        devices = list(seen_ids.values())
        logger.info(
            "ip_prefix query '%s' namespace=%s (operator=%s) returned %s unique devices",
            cidr,
            namespace,
            operator,
            len(devices),
        )
        return devices

    async def _query_devices_by_custom_field(
        self,
        custom_field_name: str,
        custom_field_value: str,
        use_contains: bool = False,
    ) -> list[DeviceInfo]:
        """
        Query devices by custom field value.

        Intentionally kept as a live Nautobot call: custom fields are dynamic
        and not stored in the bulk device cache.

        Args:
            custom_field_name: Name of the custom field (with cf_ prefix)
            custom_field_value: Value to search for
            use_contains: Whether to use contains (icontains) or exact match

        Returns:
            List of matching devices
        """
        try:
            if (
                not custom_field_name
                or not custom_field_value
                or (isinstance(custom_field_value, str) and custom_field_value.strip() == "")
            ):
                logger.warning(
                    "Empty custom_field_name or custom_field_value provided, returning empty result"
                )
                return []

            custom_field_types = await self._get_custom_field_types()

            cf_key = custom_field_name.replace("cf_", "")
            cf_type = custom_field_types.get(cf_key)

            if cf_type == "select":
                graphql_var_type = "[String]"
            elif use_contains:
                graphql_var_type = "[String]"
            else:
                graphql_var_type = "String"

            logger.info(
                "Custom field '%s' type='%s', use_contains=%s, GraphQL type='%s'",
                cf_key,
                cf_type,
                use_contains,
                graphql_var_type,
            )

            filter_field = custom_field_name

            if use_contains:
                query = f"""
                query devices_by_custom_field($field_value: {graphql_var_type}) {{
                  devices({filter_field}__ic: $field_value) {{
                    id
                    name
                    serial
                    role {{
                      name
                    }}
                    location {{
                      name
                    }}
                    primary_ip4 {{
                      address
                    }}
                    status {{
                      name
                    }}
                    device_type {{
                      model
                      manufacturer {{
                        name
                      }}
                    }}
                    tags {{
                      name
                    }}
                    platform {{
                      name
                      network_driver
                    }}
                  }}
                }}
                """
            else:
                query = f"""
                query devices_by_custom_field($field_value: {graphql_var_type}) {{
                  devices({filter_field}: $field_value) {{
                    id
                    name
                    serial
                    role {{
                      name
                    }}
                    location {{
                      name
                    }}
                    primary_ip4 {{
                      address
                    }}
                    status {{
                      name
                    }}
                    device_type {{
                      model
                      manufacturer {{
                        name
                      }}
                    }}
                    tags {{
                      name
                    }}
                    platform {{
                      name
                      network_driver
                    }}
                  }}
                }}
                """

            if graphql_var_type == "[String]":
                variables = {"field_value": [custom_field_value]}
            else:
                variables = {"field_value": custom_field_value}

            logger.debug("Custom field '%s' GraphQL query:\n%s", cf_key, query)
            logger.debug("Custom field '%s' variables: %s", cf_key, variables)
            logger.info(
                "Custom field '%s' filter: %s, type: %s, graphql_var_type: %s",
                cf_key,
                filter_field,
                cf_type,
                graphql_var_type,
            )

            result = await self._nautobot.graphql_query(query, variables, self._credentials)

            if "errors" in result:
                logger.error("GraphQL errors in custom field query: %s", result["errors"])
                return []

            return self._parse_device_data(result.get("data", {}).get("devices", []))

        except Exception as e:
            logger.error("Error querying devices by custom field '%s': %s", custom_field_name, e)
            return []

