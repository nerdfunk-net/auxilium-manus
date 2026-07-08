"""Shared Nautobot device attribute-bag query and builder.

Single source of truth for the ``nautobot`` attribute bag exposed to Jinja
templates. Both the ``get-nautobot-attributes`` workflow step and the template
editor preview endpoint use this module so a template author sees identical
``nautobot.*`` fields in both places.
"""

from __future__ import annotations

from typing import Any

# Attribute group config key -> GraphQL boolean variable used by @include.
ATTR_TO_VAR: dict[str, str] = {
    "interfaces": "get_interfaces",
    "custom_fields": "get_custom_fields",
    "tags": "get_tags",
    "config_context": "get_config_context",
    "secret_groups": "get_secret_groups",
    "console_ports": "get_console_port",
    "power_ports": "get_power_port",
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
      connected_interface {
        id
        name
        device {
          id
          name
        }
      }
      cable {
        id
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

DEVICE_ATTRIBUTES_QUERY = (
    "query DeviceDetails(\n  $deviceId: ID!,\n"
    + _QUERY_VARIABLES
    + ") {\n  device(id: $deviceId) {"
    + _DEVICE_FIELDS
    + "  }\n}"
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
