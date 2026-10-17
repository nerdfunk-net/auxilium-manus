/** Config key for the Mattermost source reference stored on workflow step nodes. */
export const MATTERMOST_SOURCE_ID_KEY = "mattermost_source_id";

export function mattermostSourceIdFromConfig(config: Record<string, unknown>): string {
  const raw = config[MATTERMOST_SOURCE_ID_KEY];
  if (typeof raw === "string" && raw.trim()) {
    return raw.trim();
  }
  return "";
}

export function isMattermostSourceConfigured(config: Record<string, unknown>): boolean {
  return Boolean(mattermostSourceIdFromConfig(config));
}
