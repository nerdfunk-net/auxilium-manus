"""
Pure data transformation and normalization functions.

This module contains stateless utility logic with zero service dependencies.
"""

from typing import Any, Dict, List, Optional, Tuple


def flatten_nested_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flatten nested fields in data.

    For example, converts {"platform.name": "ios"} to {"platform": "ios"}

    Args:
        data: Dictionary with potentially nested field names

    Returns:
        Dictionary with flattened field names

    Example:
        >>> flatten_nested_fields({"platform.name": "ios", "status": "active"})
        {'platform': 'ios', 'status': 'active'}
    """
    flattened = {}

    for key, value in data.items():
        if "." in key:
            # Extract base field from nested notation
            base_field = key.split(".")[0]
            flattened[base_field] = value
        else:
            flattened[key] = value

    return flattened


def extract_nested_value(data: Dict[str, Any], path: str) -> Any:
    """
    Extract value from nested dictionary using dot notation path.

    Args:
        data: Dictionary to extract from
        path: Dot-notation path (e.g., "platform.name")

    Returns:
        Extracted value or None if not found

    Example:
        >>> extract_nested_value({"platform": {"name": "ios"}}, "platform.name")
        'ios'
        >>> extract_nested_value({"platform": {"name": "ios"}}, "platform.version")
        None
    """
    keys = path.split(".")
    current = data

    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None

    return current


def normalize_tags(tags: Any) -> List[str]:
    """
    Normalize tags to a list of strings.

    Handles:
    - Comma-separated string: "tag1,tag2,tag3"
    - List: ["tag1", "tag2", "tag3"]
    - Single string: "tag1"

    Args:
        tags: Tags in various formats

    Returns:
        List of tag strings

    Example:
        >>> normalize_tags("tag1,tag2,tag3")
        ['tag1', 'tag2', 'tag3']
        >>> normalize_tags(["tag1", "tag2"])
        ['tag1', 'tag2']
        >>> normalize_tags("single-tag")
        ['single-tag']
        >>> normalize_tags(None)
        []
    """
    if not tags:
        return []

    if isinstance(tags, list):
        return [str(tag).strip() for tag in tags if str(tag).strip()]

    if isinstance(tags, str):
        # Check if comma-separated
        if "," in tags:
            return [tag.strip() for tag in tags.split(",") if tag.strip()]
        else:
            return [tags.strip()] if tags.strip() else []

    # Fallback: convert to string
    return [str(tags).strip()] if str(tags).strip() else []


def prepare_update_data(
    row: Dict[str, str],
    headers: List[str],
    excluded_fields: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], Optional[Dict[str, str]], Optional[str]]:
    """
    Prepare update data from CSV row.

    Filters out empty values and excluded fields.
    Handles special fields like tags (converts to list).
    Handles nested fields like 'platform.name' by extracting just the nested value.
    Extracts interface configuration if present.

    Args:
        row: CSV row as dictionary
        headers: List of column headers
        excluded_fields: Optional list of fields to exclude (default: id, name, ip_address)

    Returns:
        Tuple of (update_data dict, interface_config dict or None, ip_namespace str or None)

    Example:
        >>> row = {"name": "device1", "status": "active", "tags": "tag1,tag2", "interface_name": "eth0"}
        >>> headers = ["name", "status", "tags", "interface_name"]
        >>> data, iface, ns = prepare_update_data(row, headers)
        >>> data
        {'status': 'active', 'tags': ['tag1', 'tag2']}
        >>> iface
        {'name': 'eth0', 'type': 'virtual', 'status': 'active'}
    """
    update_data = {}
    interface_config = None
    ip_namespace = None

    # Default excluded fields (identifiers)
    if excluded_fields is None:
        excluded_fields = ["id", "name", "ip_address"]
    excluded_set = set(excluded_fields)

    # Interface configuration fields
    interface_fields = {
        "interface_name",
        "interface_type",
        "interface_status",
        "ip_namespace",
    }

    # Extract interface configuration if present
    if any(
        f in headers for f in ["interface_name", "interface_type", "interface_status"]
    ):
        interface_config = {
            "name": row.get("interface_name", "").strip() or "Loopback",
            "type": row.get("interface_type", "").strip() or "virtual",
            "status": row.get("interface_status", "").strip() or "active",
        }

    # Extract IP namespace if present
    if "ip_namespace" in headers:
        ip_namespace = row.get("ip_namespace", "").strip() or "Global"

    for field in headers:
        if field in excluded_set or field in interface_fields:
            continue

        value = row.get(field, "").strip()

        # Skip empty values
        if not value:
            continue

        # Handle special fields
        if field == "tags":
            # Tags should be a list
            update_data[field] = normalize_tags(value)
        # Handle nested fields (e.g., "platform.name" -> extract just the name)
        elif "." in field:
            base_field, nested_field = field.rsplit(".", 1)
            update_data[base_field] = value
        else:
            update_data[field] = value

    return update_data, interface_config, ip_namespace


def extract_id_from_url(url: str) -> Optional[str]:
    """
    Extract UUID from Nautobot REST API URL.

    Args:
        url: REST API URL (e.g., "/api/dcim/devices/550e8400-e29b-41d4-a716-446655440000/")

    Returns:
        Extracted UUID or None if not found

    Example:
        >>> extract_id_from_url("/api/dcim/devices/550e8400-e29b-41d4-a716-446655440000/")
        '550e8400-e29b-41d4-a716-446655440000'
        >>> extract_id_from_url("/api/dcim/devices/")
        None
    """
    import re

    uuid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    match = re.search(uuid_pattern, url, re.IGNORECASE)
    return match.group(0) if match else None
