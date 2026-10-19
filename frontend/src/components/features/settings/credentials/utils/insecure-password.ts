/**
 * Quality rules for application account passwords, mirrored from
 * `backend/core/password_policy.py` (length, common-password denylist, and
 * not equal to the username). SSH logins and Basic Auth secrets are judged
 * with the same rules, but only to warn — the remote system owns enforcement.
 */

export const ACCOUNT_PASSWORD_MIN_LENGTH = 12;

const COMMON_PASSWORDS = new Set([
  "password",
  "passw0rd",
  "admin",
  "changeme",
  "letmein",
  "welcome",
]);

/** Credential types whose secret signs in to another system. */
export function isRemoteLoginSecret(type: string): boolean {
  return type === "ssh" || type === "generic";
}

/**
 * Why a non-empty password fails the account password rules, or null when it
 * meets them. An empty value is "not set", not insecure.
 */
export function insecurePasswordReason(password: string, username: string): string | null {
  if (!password) {
    return null;
  }
  if (password.length < ACCOUNT_PASSWORD_MIN_LENGTH) {
    return `It is shorter than ${ACCOUNT_PASSWORD_MIN_LENGTH} characters.`;
  }
  const lowered = password.toLowerCase();
  if (COMMON_PASSWORDS.has(lowered)) {
    return "It is a very common password.";
  }
  const user = username.trim().toLowerCase();
  if (user && lowered === user) {
    return "It matches the username.";
  }
  return null;
}
