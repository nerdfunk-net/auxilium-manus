import { parseSourceSettingKey } from "../constants/setting-keys";
import type {
  GitSourceConfig,
  NautobotSourceConfig,
  SettingRecord,
} from "../types/settings-api";

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
    token: typeof value.token === "string" ? value.token : "",
    description: record.description,
    updatedAt: record.updated_at,
  };
}

function parseGitValue(
  sourceId: string,
  value: Record<string, unknown>,
  record: SettingRecord,
): GitSourceConfig | null {
  if (typeof value.url !== "string" || !value.url) {
    return null;
  }
  return {
    sourceId,
    key: record.key,
    url: value.url,
    branch: typeof value.branch === "string" ? value.branch : "main",
    token: typeof value.token === "string" ? value.token : "",
    username: typeof value.username === "string" ? value.username : "",
    repository_path:
      typeof value.repository_path === "string" ? value.repository_path : "",
    description: record.description,
    updatedAt: record.updated_at,
  };
}

export function groupSourceSettings(settings: SettingRecord[]): {
  nautobot: NautobotSourceConfig[];
  git: GitSourceConfig[];
} {
  const nautobot: NautobotSourceConfig[] = [];
  const git: GitSourceConfig[] = [];

  for (const record of settings) {
    const parsed = parseSourceSettingKey(record.key);
    if (!parsed) {
      continue;
    }
    if (parsed.sourceType === "nautobot") {
      const config = parseNautobotValue(
        parsed.sourceId,
        record.value,
        record,
      );
      if (config) {
        nautobot.push(config);
      }
    } else {
      const config = parseGitValue(parsed.sourceId, record.value, record);
      if (config) {
        git.push(config);
      }
    }
  }

  const byId = (a: { sourceId: string }, b: { sourceId: string }) =>
    a.sourceId.localeCompare(b.sourceId);

  return {
    nautobot: nautobot.sort(byId),
    git: git.sort(byId),
  };
}

export function collectExistingSourceIds(
  settings: SettingRecord[],
  sourceType: "nautobot" | "git",
): string[] {
  return settings
    .map((record) => parseSourceSettingKey(record.key))
    .filter(
      (parsed): parsed is { sourceType: typeof sourceType; sourceId: string } =>
        parsed !== null && parsed.sourceType === sourceType,
    )
    .map((parsed) => parsed.sourceId);
}
