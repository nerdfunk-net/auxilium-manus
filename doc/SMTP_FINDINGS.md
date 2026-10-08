# SMTP send-mail — authentication review

Review of the uncommitted `send-mail` step (`backend/workflow_steps/send_mail/`,
frontend `send-mail` panel, registry entry). Focus is SMTP authentication:
how the vault password is resolved, when it is sent, and whether TLS actually
protects it. Checked against aiosmtplib 5.1.3
(`.venv/lib/python3.14/site-packages/aiosmtplib/smtp.py`).

The password is not stored on the step, and it is not written to logs or the
failure summary. The gaps below are about where that password is sent.

## Findings

### 1. Medium — `verify_tls: false` still authenticates

`backend/workflow_steps/send_mail/executor.py` passes `validate_certs=verify_tls`
into `aiosmtplib.send()` (around line 198). Verification stays on unless the
config value is exactly `False` (`config.get("verify_tls") is not False`).

When it is `False`, aiosmtplib builds the client context with
`check_hostname = False` and `verify_mode = ssl.CERT_NONE`
(`smtp.py` `_build_tls_context`). Login still runs after the handshake.
There is no `cert_bundle` argument and no restriction to loopback, so a
private CA cannot be trusted without turning identity checks off entirely.
A workflow can set `smtp_server` to any host, disable verification, and the
vault password is sent to whoever completes the TLS handshake.

The config panel warns. The executor does not enforce the warning.

### 2. Medium — an SSH password can be sent to any SMTP host

`resolve_generic_credential()` accepts both `ssh` and `generic` credentials
(`backend/workflow_steps/common/credential_resolver.py`). The send-mail panel
lists both (`SMTP_CREDENTIAL_TYPES` in
`frontend/src/components/features/workflow-steps/send-mail/index.tsx`).
`smtp_server` is a free-form hostname in the step config.

On a run, the executor decrypts that credential with
`acting_user_id=run.triggered_by_id` and submits the password as SMTP AUTH.
That path does not require `credentials:reveal`. A global device password can
therefore be delivered to a host the workflow author chooses. Another user's
private credential does not resolve: private entries stay limited to the user
who triggered the run, and a run with no user (`triggered_by_id` is `None`)
sees global credentials only.

### 3. Medium — plaintext AUTH is allowed

With `security: none`, the executor sets both `start_tls=False` and
`use_tls=False` (`executor.py` around line 196) and still passes `username`
and `password` when `credential_reference` is set. aiosmtplib then calls
`login()` on the cleartext connection. AUTH PLAIN and AUTH LOGIN only
base64-encode the password.

The executor and `WorkflowValidationService` both allow this pair. The Help
tab says not to log in over plain SMTP. The config panel does not flag the
combination when a credential is selected and security is None.

`security: starttls` does not have this problem: aiosmtplib upgrades before
`login()`, and `start_tls=True` raises if the server does not advertise
STARTTLS, so a stripped-STARTTLS banner does not receive the password.
`security: ssl` wraps the socket before any SMTP command.

## What holds

- The canvas stores `credential_reference` (a vault name) only. The password
  never lives in the step config.
- Resolution uses `CredentialManager.generic()` scoped to the runner. A
  private credential wins over a global one of the same name. Validation
  checks name, type, and expiry without decrypting
  (`workflow_validation_service.py`, `send-mail` is in `_GENERIC_STEP_KINDS`).
- Preferred AUTH order in aiosmtplib is CRAM-MD5, then PLAIN, then LOGIN.
  CRAM-MD5 does not send the password.
- Failure handling keeps server text out of the step summary and the log
  line. `_failure_summary()` records the exception class and the SMTP status
  code only, so a 535 response that echoes the password is dropped.
- Certificate verification is on when `verify_tls` is missing, which covers
  workflows saved before the option existed.
- CR/LF in From, To, and Subject is rejected after placeholder rendering, so
  a device attribute cannot inject a header such as `Bcc`.
- aiosmtplib does not log the AUTH exchange.
