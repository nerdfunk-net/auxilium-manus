"""Template categories. A category decides which part of the app uses a template."""

from __future__ import annotations

# Rendered once per device by workflow steps and the template editor (the original use).
CATEGORY_NETMIKO = "netmiko"
# Rendered once per generated report snapshot (doc/REPORTS.md). Jinja2 only, no device options.
CATEGORY_REPORT = "report"
