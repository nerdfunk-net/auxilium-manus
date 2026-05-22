"""Validates workflow step output dicts against their declared data types.

Usage in step_runner:
    result = _validator.validate("device_list", output)
    if not result.valid:
        raise ValueError(f"Output validation failed: {'; '.join(result.errors)}")

To add a new data type:
  1. Define a Pydantic model in models/workflow_data_types.py
  2. Add an entry to _VALIDATORS below
  3. Add the step → data_type mapping to STEP_OUTPUT_TYPES in step_registry.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from models.workflow_data_types import DeviceList

_VALIDATORS: dict[str, type[BaseModel]] = {
    "device_list": DeviceList,
}


@dataclass
class ValidationResult:
    valid: bool
    data_type: str
    errors: list[str] = field(default_factory=list)


class StepOutputValidator:
    def validate(self, data_type: str, data: dict[str, Any]) -> ValidationResult:
        """Validate *data* against the schema registered for *data_type*.

        Returns a passing result for unknown types so new steps are not blocked
        before their schema is registered.
        """
        model = _VALIDATORS.get(data_type)
        if model is None:
            return ValidationResult(valid=True, data_type=data_type)
        try:
            model.model_validate(data)
            return ValidationResult(valid=True, data_type=data_type)
        except ValidationError as exc:
            errors = [f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()]
            return ValidationResult(valid=False, data_type=data_type, errors=errors)
