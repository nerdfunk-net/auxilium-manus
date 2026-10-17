const PROVIDER_ID_RE = /^[a-z][a-z0-9_-]{0,63}$/;

export function parseAndVerifyOidcState(
  storedState: string | null,
  incomingState: string | null,
): { ok: true; providerId: string } | { ok: false; error: string } {
  if (!incomingState || !storedState) {
    return { ok: false, error: "Missing state parameter — possible CSRF attempt" };
  }
  if (storedState !== incomingState) {
    return { ok: false, error: "Invalid state parameter — possible CSRF attempt" };
  }
  const providerId = incomingState.includes(":")
    ? incomingState.split(":", 2)[0]
    : null;
  if (!providerId || !PROVIDER_ID_RE.test(providerId)) {
    return { ok: false, error: "Invalid state parameter" };
  }
  return { ok: true, providerId };
}
