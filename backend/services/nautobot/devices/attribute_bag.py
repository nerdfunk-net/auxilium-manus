"""Shared Nautobot device attribute-bag query and builder.

Single source of truth for the ``nautobot`` attribute bag exposed to Jinja
templates. Both the ``get-nautobot-attributes`` workflow step and the template
editor preview endpoint use this module so a template author sees identical
``nautobot.*`` fields in both places.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from services.nautobot.version import detect_nautobot_version

if TYPE_CHECKING:
    from services.nautobot.client import NautobotService
    from services.nautobot.credentials import NautobotCredentials

# Attribute group config key -> GraphQL boolean variable used by @include.
ATTR_TO_VAR: dict[str, str] = {
    "interfaces": "get_interfaces",
    "custom_fields": "get_custom_fields",
    "tags": "get_tags",
    "config_context": "get_config_context",
    "secret_groups": "get_secret_groups",
    "console_ports": "get_console_port",
    "power_ports": "get_power_port",
    "cables": "get_cables",
}

# Valid attribute group keys (order matches the frontend selector).
ATTRIBUTE_GROUP_KEYS: tuple[str, ...] = (
    "interfaces",
    "custom_fields",
    "tags",
    "config_context",
    "secret_groups",
    "console_ports",
    "power_ports",
    "cables",
)

_DEVICE_FIELDS = """
    id
    name
    hostname: name
    asset_tag
    serial
    position
    face
    config_context @include(if: $get_config_context)
    local_config_context_data @include(if: $get_config_context)
    _custom_field_data @include(if: $get_custom_fields)
    primary_ip4 @include(if: $get_primary_ipv4) {
      id
      address
      description
      ip_version
      host
      mask_length
      dns_name
      status {
        id
        name
      }
      parent {
        id
        prefix
      }
    }
    role {
      id
      name
    }
    device_type {
      id
      model
      manufacturer {
        id
        name
      }
    }
    platform {
      id
      name
      network_driver
      manufacturer {
        id
        name
      }
    }
    location {
      id
      name
      description
      parent {
        id
        name
      }
    }
    status {
      id
      name
    }
    interfaces @include(if: $get_interfaces) {
      id
      name
      type
      enabled
      mtu
      mac_address
      description
      status {
        id
        name
      }
      ip_addresses {
        id
        address
        ip_version
        status {
          id
          name
        }
      }
      tagged_vlans {
        id
        name
        vid
      }
      untagged_vlan {
        id
        name
        vid
      }
    }
    console_ports @include(if: $get_console_port) {
      id
      name
      type
      description
    }
    console_server_ports @include(if: $get_console_port) {
      id
      name
      type
      description
    }
    power_ports @include(if: $get_power_port) {
      id
      name
      type
      description
    }
    power_outlets @include(if: $get_power_port) {
      id
      name
      type
      description
    }
    secrets_group @include(if: $get_secret_groups) {
      id
      name
    }
    tags @include(if: $get_tags) {
      id
      name
      color
    }
"""

_QUERY_VARIABLES = """
  $get_primary_ipv4: Boolean = false,
  $get_interfaces: Boolean = false,
  $get_config_context: Boolean = false,
  $get_custom_fields: Boolean = false,
  $get_tags: Boolean = false,
  $get_secret_groups: Boolean = false,
  $get_console_port: Boolean = false,
  $get_power_port: Boolean = false
"""

# Cable selections, one per Nautobot layout. They are NOT part of the static query:
# GraphQL validates the whole document before ``@include`` is evaluated, so a field the
# server does not know (``CableType.interfaces`` on 3.1) would fail every query, even
# with ``get_cables=false``. The matching fragment is appended only when the ``cables``
# group is requested. GraphQL merges the same-named ``interfaces`` selections, so with
# both groups selected ``interfaces[]`` carries the union.
#
# Nautobot < 3.2: verified against 3.1.1 (cable type, tags and status included).
_CABLES_FRAGMENT_LEGACY = """
    interfaces @include(if: $get_cables) {
      id
      name
      cable {
        id
        type
        label
        tags {
          id
          name
        }
        status {
          id
          name
        }
      }
      connected_endpoint {
        __typename
        ... on InterfaceType {
          id
          name
          device {
            id
            name
          }
        }
      }
    }
"""

# Nautobot >= 3.2 (multi-connector cables): from the maintainer's query, not yet run
# against a 3.2 server.
_CABLES_FRAGMENT_V32 = """
    interfaces @include(if: $get_cables) {
      id
      name
      cable {
        id
        type
        label
        tags {
          id
          name
        }
        status {
          id
          name
        }
        interfaces {
          id
          name
          device {
            id
            name
          }
        }
      }
    }
"""

CABLES_LAYOUT_LEGACY = "legacy"
CABLES_LAYOUT_V32 = "v32"
_CABLES_FRAGMENTS: dict[str, str] = {
    CABLES_LAYOUT_LEGACY: _CABLES_FRAGMENT_LEGACY,
    CABLES_LAYOUT_V32: _CABLES_FRAGMENT_V32,
}


def build_device_attributes_query(cables_layout: str | None = None) -> str:
    """Build the device query; ``cables_layout`` adds that layout's cable selection.

    ``None`` (the default) yields a query that works on every Nautobot version.
    """
    fragment = ""
    variables = _QUERY_VARIABLES
    if cables_layout is not None:
        fragment = _CABLES_FRAGMENTS[cables_layout]
        variables = _QUERY_VARIABLES.rstrip("\n") + ",\n  $get_cables: Boolean = false\n"
    return (
        "query DeviceDetails(\n  $deviceId: ID!,\n"
        + variables
        + ") {\n  device(id: $deviceId) {"
        + _DEVICE_FIELDS
        + fragment
        + "  }\n}"
    )


# Version-independent query (no cables); used where cables are never requested.
DEVICE_ATTRIBUTES_QUERY = build_device_attributes_query()


def cables_layout_for_version(version: tuple[int, int] | None) -> str:
    """3.2+ uses the multi-connector cable layout; older or unknown, the legacy one."""
    if version is not None and version >= (3, 2):
        return CABLES_LAYOUT_V32
    return CABLES_LAYOUT_LEGACY


async def cables_layout_for_groups(
    service: NautobotService,
    credentials: NautobotCredentials,
    groups: list[str],
) -> str | None:
    """The cable layout to query, or ``None`` when ``cables`` is not requested.

    Reads the server version only when ``cables`` is requested.
    """
    if "cables" not in groups:
        return None
    return cables_layout_for_version(await detect_nautobot_version(service, credentials))


async def device_query_for_groups(
    service: NautobotService,
    credentials: NautobotCredentials,
    groups: list[str],
) -> str:
    """The device query for ``groups``; reads the server version only for ``cables``."""
    return build_device_attributes_query(
        await cables_layout_for_groups(service, credentials, groups)
    )


def normalize_attribute_groups(list_of_attributes: list[str] | None) -> list[str]:
    """Keep only recognised attribute group keys, preserving order."""
    if not list_of_attributes:
        return []
    return [key for key in list_of_attributes if key in ATTR_TO_VAR]


def build_attribute_variables(list_of_attributes: list[str] | None) -> dict[str, Any]:
    """Build GraphQL @include toggles; the primary IPv4 is always requested."""
    variables: dict[str, Any] = {"get_primary_ipv4": True}
    for attr_key in normalize_attribute_groups(list_of_attributes):
        variables[ATTR_TO_VAR[attr_key]] = True
    return variables


def attributes_from_detail(detail: dict[str, Any]) -> dict[str, Any]:
    """Turn a raw GraphQL device object into the ``nautobot`` bag.

    Renames ``_custom_field_data`` to ``custom_fields``; everything else is
    passed through verbatim so the bag matches the GraphQL response shape.
    """
    attributes = dict(detail)
    custom_fields = attributes.pop("_custom_field_data", None)
    if custom_fields is not None:
        attributes["custom_fields"] = custom_fields
    return attributes
