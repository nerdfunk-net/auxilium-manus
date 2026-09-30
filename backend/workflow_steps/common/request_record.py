"""Record an outbound API call on a device for the run's detail view.

Records live in ``DeviceContext.requests[node_id]`` — deliberately *not* in
``attribute_bags`` — so they are display-only: other steps and ``{path}``
expressions cannot read them. Anything a workflow needs from an API response
belongs in an attribute bag instead; put only the debug-only request (and,
optionally, a response that is not needed elsewhere) here.
"""

from __future__ import annotations

from typing import Any

from models.workflow_context import DeviceContext, RequestRecord
from services.workflow_context.secret_fields import redact_secrets_in_data


def append_request_record(
    device: DeviceContext,
    *,
    node_id: str,
    target: str,
    method: str,
    endpoint: str,
    request: dict[str, Any] | None = None,
    response: dict[str, Any] | None = None,
    ok: bool = True,
) -> DeviceContext:
    """Return *device* with a redacted ``RequestRecord`` appended for *node_id*.

    Redaction is marker-based (sealed secrets and known secret field names), so
    callers holding a cleartext secret must seal it in *request* first.
    """
    redacted = redact_secrets_in_data({"request": request, "response": response})
    record = RequestRecord(
        target=target,
        method=method,
        endpoint=endpoint,
        request=redacted["request"],
        response=redacted["response"],
        ok=ok,
    )
    return device.model_copy(
        update={
            "requests": {**device.requests, node_id: [*device.requests.get(node_id, []), record]}
        }
    )
