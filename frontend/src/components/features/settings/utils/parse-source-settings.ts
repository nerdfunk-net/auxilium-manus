import { parseSourceSettingKey } from "../constants/setting-keys";
import type { NautobotSourceConfig, SettingRecord } from "../types/settings-api";

function parseNautobotValue(
  sourceId: string,
  value: Record<string, unknown>,
  record: SettingRecord,
): NautobotSourceConfig | null {
  if (typeof value.url !== "string" || !value.url) {
    return null;
  }
  return {
    sourceId,
    key: record.key,
    url: value.url,
    tokenConfigured: Boolean(value.token_configured),
    verifySsl: resolveVerifySsl(value),
    description: record.description,
    updatedAt: record.updated_at,
  };
}

function resolveVerifySsl(value: Record<string, unknown>): boolean {
  if (typeof value.verify_ssl === "boolean") {
    return value.verify_ssl;
  }
  if (typeof value.verifySsl === "boolean") {
    return value.verifySsl;
  }
  return true;
}

export function groupSourceSettings(settings: SettingRecord[]): {
  nautobot: NautobotSourceConfig[];
} {
  const nautobot: NautobotSourceConfig[] = [];

  for (const record of settings) {
    const parsed = parseSourceSettingKey(record.key);
    if (!parsed || parsed.sourceType !== "nautobot") {
      continue;
    }
    const config = parseNautobotValue(parsed.sourceId, record.value, record);
    if (config) {
      nautobot.push(config);
    }
  }

  const byId = (a: { sourceId: string }, b: { sourceId: string }) =>
    a.sourceId.localeCompare(b.sourceId);

  return {
    nautobot: nautobot.sort(byId),
  };
}

export function collectExistingSourceIds(
  settings: SettingRecord[],
  sourceType: "nautobot",
): string[] {
  return settings
    .map((record) => parseSourceSettingKey(record.key))
    .filter(
      (parsed): parsed is { sourceType: typeof sourceType; sourceId: string } =>
        parsed !== null && parsed.sourceType === sourceType,
    )
    .map((parsed) => parsed.sourceId);
}
