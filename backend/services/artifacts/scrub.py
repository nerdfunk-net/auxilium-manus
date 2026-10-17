"""Scrub known secrets out of diagnostic artifacts before they are stored (S3-05)."""

from __future__ import annotations

from services.workflow_context.secret_fields import scrub_known_secrets

# Diagnostics that are read by anyone holding ``workflow_runs:read``. A Netmiko session log records
# every character sent to the device, so a freshly generated secret that was pushed in the same run
# would otherwise sit there in cleartext.
#
# Deliberately NOT scrubbed: ``rendered_template`` (the deploy step reads it back), and the
# ``running_config`` / ``startup_config`` / ``command_output`` content kinds. A configuration
# backup that silently replaces a deployed key by ``***REDACTED***`` would restore a broken
# device, so those stay verbatim (rendering a secret into a file is the documented author choice).
DIAGNOSTIC_KINDS = frozenset({"netmiko_session_log"})


def scrub_for_storage(kind: str, text: str) -> str:
    """Exact-match scrub of every secret the run has unwrapped or resolved.

    Only secrets that passed ``unwrap_secret`` / ``CredentialsService.get_decrypted_*`` in this
    run segment are known; a transformed value (reversed, base64) is not."""
    if kind not in DIAGNOSTIC_KINDS:
        return text
    scrubbed = scrub_known_secrets(text)
    return scrubbed if isinstance(scrubbed, str) else text
