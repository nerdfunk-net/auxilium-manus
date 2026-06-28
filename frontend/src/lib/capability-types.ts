/** Capability tokens — keep in sync with backend Capability enum. */

export type Capability =
  | "identity"
  | "attributes"
  | "running_config"
  | "startup_config"
  | "parsed"
  | "pending_commands";

export const ALL_CAPABILITIES: Capability[] = [
  "identity",
  "attributes",
  "running_config",
  "startup_config",
  "parsed",
  "pending_commands",
];

export interface Provided {
  capabilities: Capability[];
  parsedKeys: string[];
}

export interface Required {
  capabilities: Capability[];
  parsedKeys: string[];
}

export function isCompatible(provided: Provided, required: Required): boolean {
  const haveCaps = new Set(provided.capabilities);
  const haveKeys = new Set(provided.parsedKeys);
  const capsOk = required.capabilities.every((cap) => haveCaps.has(cap));
  const keysOk = required.parsedKeys.every((key) => haveKeys.has(key));
  return capsOk && keysOk;
}
