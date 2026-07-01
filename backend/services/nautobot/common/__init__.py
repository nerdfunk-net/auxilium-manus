"""
Common utilities for Nautobot operations.

This package contains pure functions and exception classes used across
Nautobot service modules.
"""

from .exceptions import (
    NautobotAPIError,
    NautobotDuplicateResourceError,
    NautobotError,
    NautobotResourceNotFoundError,
    NautobotValidationError,
    handle_already_exists_error,
    is_duplicate_error,
)
from .interface_types import (
    VALID_INTERFACE_TYPES,
    normalize_interface_type,
)
from .utils import (
    extract_id_from_url,
    extract_nested_value,
    flatten_nested_fields,
    normalize_tags,
    prepare_update_data,
)
from .validators import (
    is_valid_uuid,
    validate_cidr,
    validate_ip_address,
    validate_mac_address,
    validate_required_fields,
)

__all__ = [
    # Validators
    "is_valid_uuid",
    "validate_ip_address",
    "validate_mac_address",
    "validate_cidr",
    "validate_required_fields",
    # Utils
    "flatten_nested_fields",
    "extract_nested_value",
    "normalize_tags",
    "prepare_update_data",
    "extract_id_from_url",
    # Exceptions
    "NautobotError",
    "NautobotValidationError",
    "NautobotResourceNotFoundError",
    "NautobotDuplicateResourceError",
    "NautobotAPIError",
    "is_duplicate_error",
    "handle_already_exists_error",
    # Interface types
    "VALID_INTERFACE_TYPES",
    "normalize_interface_type",
]
