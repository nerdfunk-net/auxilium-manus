export const SOURCES_KEY_PREFIX = "sources.";

export const SOURCE_KEY_PREFIXES = {
  nautobot: "sources.nautobot.",
  git: "sources.git.",
} as const;

/** User-defined reference ID: lowercase letter first, then letters, digits, _ - */
export const SOURCE_ID_REGEX = /^[a-z][a-z0-9_-]{0,63}$/;

export type SourceType = keyof typeof SOURCE_KEY_PREFIXES;

export function buildSourceSettingKey(
  sourceType: SourceType,
  sourceId: string,
): string {
  const normalized = sourceId.trim().toLowerCase();
  if (!SOURCE_ID_REGEX.test(normalized)) {
    throw new Error("Invalid source ID");
  }
  return `${SOURCE_KEY_PREFIXES[sourceType]}${normalized}`;
}

export function parseSourceSettingKey(
  key: string,
): { sourceType: SourceType; sourceId: string } | null {
  for (const sourceType of ["nautobot", "git"] as const) {
    const prefix = SOURCE_KEY_PREFIXES[sourceType];
    if (!key.startsWith(prefix)) {
      continue;
    }
    const sourceId = key.slice(prefix.length);
    if (!sourceId || !SOURCE_ID_REGEX.test(sourceId)) {
      return null;
    }
    return { sourceType, sourceId };
  }
  return null;
}
