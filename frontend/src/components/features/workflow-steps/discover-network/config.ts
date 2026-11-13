export const DEFAULT_MAX_DEVICES = 50;
export const MIN_MAX_DEVICES = 1;
export const MAX_MAX_DEVICES = 500;
export const DEFAULT_MAX_DEPTH = 5;
export const MIN_MAX_DEPTH = 1;
export const MAX_MAX_DEPTH = 20;
export const DEFAULT_CONCURRENCY = 5;
export const MIN_CONCURRENCY = 1;
export const MAX_CONCURRENCY = 20;
export const MAX_PREFIXES = 50;
/** A permitted prefix must be at least this specific (backend scope.py MIN_PREFIX_LENGTH). */
export const MIN_PREFIX_LENGTH = 8;

const EMPTY_PREFIXES: string[] = [];

// [network address, prefix length] ranges the backend never allows (loopback, link-local, ...).
const BLOCKED_RANGES: ReadonlyArray<readonly [number, number]> = [
  [0x00000000, 8], // 0.0.0.0/8
  [0x7f000000, 8], // 127.0.0.0/8
  [0xa9fe0000, 16], // 169.254.0.0/16
  [0xe0000000, 4], // 224.0.0.0/4
  [0xf0000000, 4], // 240.0.0.0/4
];

const CIDR_PATTERN = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\/(\d{1,2})$/;

function clampInt(value: string, min: number, max: number, fallback: number): number {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? Math.min(max, Math.max(min, parsed)) : fallback;
}

export function clampMaxDevices(value: string): number {
  return clampInt(value, MIN_MAX_DEVICES, MAX_MAX_DEVICES, DEFAULT_MAX_DEVICES);
}

export function clampMaxDepth(value: string): number {
  return clampInt(value, MIN_MAX_DEPTH, MAX_MAX_DEPTH, DEFAULT_MAX_DEPTH);
}

export function clampConcurrency(value: string): number {
  return clampInt(value, MIN_CONCURRENCY, MAX_CONCURRENCY, DEFAULT_CONCURRENCY);
}

/** Prefixes typed one per line (or comma separated): trimmed, without blanks and duplicates. */
export function parsePrefixText(text: string): string[] {
  const seen = new Set<string>();
  for (const part of text.split(/[\n,]/)) {
    const trimmed = part.trim();
    if (trimmed) seen.add(trimmed);
  }
  return [...seen];
}

function overlaps(start: number, length: number, otherStart: number, otherLength: number): boolean {
  const shortest = Math.min(length, otherLength);
  const mask = shortest === 0 ? 0 : (0xffffffff << (32 - shortest)) >>> 0;
  return ((start & mask) >>> 0) === ((otherStart & mask) >>> 0);
}

/** The reason a prefix is not allowed (mirrors backend scope.py), or null when it is fine. */
export function validatePrefix(value: string): string | null {
  if (value.includes(":")) return "Only IPv4 prefixes are supported.";
  const match = CIDR_PATTERN.exec(value);
  if (!match) return "Not a prefix in CIDR form (for example 10.1.0.0/16).";
  const octets = match.slice(1, 5).map(Number);
  const length = Number(match[5]);
  if (octets.some((octet) => octet > 255) || length > 32) {
    return "Not a prefix in CIDR form (for example 10.1.0.0/16).";
  }
  if (length < MIN_PREFIX_LENGTH) {
    return `Too broad: use /${MIN_PREFIX_LENGTH} or more specific.`;
  }
  const address = ((octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]) >>> 0;
  const hostMask = length === 32 ? 0 : 0xffffffff >>> length;
  if ((address & hostMask) !== 0) return "Has host bits set; use the network address.";
  if (BLOCKED_RANGES.some(([start, len]) => overlaps(address, length, start, len))) {
    return "Contains addresses that are never allowed (loopback, link-local, multicast).";
  }
  return null;
}

function flag(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function numberOr(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function prefixList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : EMPTY_PREFIXES;
}

/**
 * Merge a partial change into the step config and keep every value the type the backend
 * (backend/workflow_steps/discover_network/options.py) expects. The prefixes are kept when
 * following is switched off, so ticking the box again does not lose them.
 */
export function buildDiscoverNetworkConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  const next: Record<string, unknown> = { ...config, ...patch };
  next.follow_neighbors = flag(next.follow_neighbors, false);
  next.permitted_prefixes = [...prefixList(next.permitted_prefixes)];
  next.follow_only_infrastructure = flag(next.follow_only_infrastructure, true);
  next.resolve_management_ip = flag(next.resolve_management_ip, true);
  next.nautobot_source_id =
    typeof next.nautobot_source_id === "string" ? next.nautobot_source_id : "";
  next.max_devices = numberOr(next.max_devices, DEFAULT_MAX_DEVICES);
  next.max_depth = numberOr(next.max_depth, DEFAULT_MAX_DEPTH);
  next.concurrency = numberOr(next.concurrency, DEFAULT_CONCURRENCY);
  return next;
}

/** Problems the backend would reject at run time, as messages for the panel. */
export function configIssues(config: Record<string, unknown>): string[] {
  const prefixes = prefixList(config.permitted_prefixes);
  const issues: string[] = [];
  if (config.follow_neighbors === true && prefixes.length === 0) {
    issues.push("Add at least one permitted prefix to log into discovered devices.");
  }
  if (prefixes.length > MAX_PREFIXES) {
    issues.push(`At most ${MAX_PREFIXES} permitted prefixes are allowed.`);
  }
  for (const prefix of prefixes) {
    const problem = validatePrefix(prefix);
    if (problem) issues.push(`${prefix}: ${problem}`);
  }
  return issues;
}

/**
 * A hint (not an error: the step still runs on the CDP addresses) when the management IP
 * lookup is on but no Nautobot source was chosen.
 */
export function managementIpHint(config: Record<string, unknown>): string | null {
  const lookupOn = config.follow_neighbors === true && config.resolve_management_ip !== false;
  const source = typeof config.nautobot_source_id === "string" ? config.nautobot_source_id : "";
  return lookupOn && !source.trim()
    ? "No Nautobot source chosen: discovered devices are logged into at the address CDP reports."
    : null;
}
