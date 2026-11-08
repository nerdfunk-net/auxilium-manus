export const MIN_DNS_TIMEOUT_SECONDS = 0.1;
export const MAX_DNS_TIMEOUT_SECONDS = 30;
export const DEFAULT_DNS_TIMEOUT_SECONDS = 2;
export const MIN_DNS_CONCURRENCY = 1;
export const MAX_DNS_CONCURRENCY = 100;
export const DEFAULT_DNS_CONCURRENCY = 20;

export function clampDnsTimeout(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && value.trim() !== ""
    ? Math.min(MAX_DNS_TIMEOUT_SECONDS, Math.max(MIN_DNS_TIMEOUT_SECONDS, parsed))
    : DEFAULT_DNS_TIMEOUT_SECONDS;
}

export function clampDnsConcurrency(value: string): number {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed)
    ? Math.min(MAX_DNS_CONCURRENCY, Math.max(MIN_DNS_CONCURRENCY, parsed))
    : DEFAULT_DNS_CONCURRENCY;
}

function flag(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

/**
 * Merge a partial change into the step config and keep it valid for the backend
 * (backend/workflow_steps/collect_client_data/options.py): at least one of IP / MAC is
 * collected, and hostnames (which resolve the ARP addresses) need IP collection.
 */
export function buildCollectClientDataConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  const next: Record<string, unknown> = { ...config, ...patch };
  let collectIp = flag(next.collect_ip_address, true);
  let collectMac = flag(next.collect_mac_address, true);

  if (!collectIp && !collectMac) {
    // The user just switched the last table off: keep the one they did not touch.
    if ("collect_ip_address" in patch) collectMac = true;
    else collectIp = true;
  }

  next.collect_ip_address = collectIp;
  next.collect_mac_address = collectMac;
  next.collect_vrfs = collectIp && flag(next.collect_vrfs, true);
  next.collect_hostname = collectIp && flag(next.collect_hostname, false);
  next.collect_neighbors = flag(next.collect_neighbors, false);
  return next;
}
