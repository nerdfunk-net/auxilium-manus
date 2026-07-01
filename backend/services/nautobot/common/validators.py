"""
Pure validation functions for Nautobot operations.

This module contains stateless validation logic with zero service dependencies.
"""

import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def is_valid_uuid(uuid_str: str) -> bool:
    """
    Validate UUID format.

    Args:
        uuid_str: UUID string to validate

    Returns:
        True if valid UUID format, False otherwise

    Example:
        >>> is_valid_uuid("550e8400-e29b-41d4-a716-446655440000")
        True
        >>> is_valid_uuid("not-a-uuid")
        False
    """
    uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    return bool(re.match(uuid_pattern, uuid_str.lower()))


def validate_ip_address(ip: str) -> bool:
    """
    Validate IP address format (IPv4 or IPv6, with or without CIDR).

    Args:
        ip: IP address string to validate

    Returns:
        True if valid, False otherwise

    Example:
        >>> validate_ip_address("192.168.1.1")
        True
        >>> validate_ip_address("192.168.1.1/24")
        True
        >>> validate_ip_address("2001:db8::1")
        True
        >>> validate_ip_address("invalid")
        False
    """
    # Simple regex patterns for IPv4 and IPv6
    ipv4_pattern = r"^(\d{1,3}\.){3}\d{1,3}(\/\d{1,2})?$"
    ipv6_pattern = r"^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}(\/\d{1,3})?$"

    if re.match(ipv4_pattern, ip) or re.match(ipv6_pattern, ip):
        return True

    logger.warning("Invalid IP address format: %s", ip)
    return False


def validate_mac_address(mac: str) -> bool:
    """
    Validate MAC address format.

    Args:
        mac: MAC address string to validate

    Returns:
        True if valid, False otherwise

    Example:
        >>> validate_mac_address("00:1A:2B:3C:4D:5E")
        True
        >>> validate_mac_address("00-1A-2B-3C-4D-5E")
        True
        >>> validate_mac_address("invalid")
        False
    """
    # Common MAC address formats: XX:XX:XX:XX:XX:XX or XX-XX-XX-XX-XX-XX
    mac_pattern = r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$"

    if re.match(mac_pattern, mac):
        return True

    logger.warning("Invalid MAC address format: %s", mac)
    return False


def validate_cidr(cidr: str) -> bool:
    """
    Validate CIDR notation.

    Args:
        cidr: CIDR string to validate (e.g., "192.168.1.0/24")

    Returns:
        True if valid, False otherwise

    Example:
        >>> validate_cidr("192.168.1.0/24")
        True
        >>> validate_cidr("192.168.1.1")
        False
    """
    if "/" not in cidr:
        return False

    return validate_ip_address(cidr)


def validate_required_fields(data: Dict[str, Any], required_fields: List[str]) -> None:
    """
    Validate that all required fields are present in data.

    Args:
        data: Dictionary to validate
        required_fields: List of required field names

    Raises:
        ValueError: If any required field is missing or empty

    Example:
        >>> validate_required_fields({"name": "test", "status": "active"}, ["name", "status"])
        >>> validate_required_fields({"name": "test"}, ["name", "status"])
        Traceback (most recent call last):
        ...
        ValueError: Missing required fields: status
    """
    missing_fields = []
    for field in required_fields:
        if field not in data or not data[field]:
            missing_fields.append(field)

    if missing_fields:
        raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")
