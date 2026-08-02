"""Domain exceptions for the settings service.

``SourceConfigError`` is a ``ValueError`` subclass specifically so
worker-side callers (workflow-step executors) can let it propagate directly
per the step contract in doc/WORKFLOW-STEPS.md (ValueError = configuration
problem) without ever importing FastAPI. See doc/FABLE-ANALYSIS.md §3.1.
"""

from __future__ import annotations


class SourceConfigError(ValueError):
    """Raised by SettingsService.get_source_config_for_step when a source_type/
    source_id pair cannot be resolved to a setting."""
