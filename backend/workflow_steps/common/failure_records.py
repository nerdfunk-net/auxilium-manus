"""Ready-made closed-vocabulary failure records for the causes most steps share.

``FailureInfo`` is what the AI assistant may read without the content opt-in
(``models/failure.py``), so a failure that names a code should name its cause too. These are the
records for "the step's input or config cannot be used", "the object is not in the remote system"
and "what the step reads is missing"; a cause with more facts (an HTTP status, a transport kind)
builds its own.
"""

from __future__ import annotations

from models.failure import FailureInfo

# The step's own input or configuration cannot be used (a value that does not resolve, a name
# that is not allowed, a required field that is empty).
INVALID_INPUT = FailureInfo(phase="config", kind="bad_request", hint="check_request")

# The object the step was asked to act on is not in the remote system (a device, an address).
NOT_FOUND = FailureInfo(phase="api", kind="not_found", hint="check_request")

# What the step reads is missing: an upstream step did not produce it (no running config, no
# parsed data, no content for the selected source).
MISSING_DATA = FailureInfo(phase="config", kind="not_found", hint="check_request")

# The remote API answered, but with something the step cannot use (no result, no parsed data).
INVALID_RESPONSE = FailureInfo(phase="api", kind="invalid_response", hint="check_controller")

# A command or session failed after the connection was made.
COMMAND_FAILED = FailureInfo(phase="command", kind="command_error")

# A notification (mail, chat post) could not be delivered and the cause was not classified.
TRANSPORT_FAILED = FailureInfo(phase="api", kind="unknown", hint="check_reachability")

# The author's template or regular expression ran in the isolated worker and was stopped: it used
# more than its time or memory, or produced more than the size cap (S4-07). Never a "no match".
TEMPLATE_STOPPED = FailureInfo(phase="render", kind="resource_limit", hint="fix_template")
REGEX_STOPPED = FailureInfo(phase="config", kind="resource_limit", hint="check_request")
