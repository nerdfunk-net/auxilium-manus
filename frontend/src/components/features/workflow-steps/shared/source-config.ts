/** The three helpers every source-bound step shares: where the source id lives in the step
 * config, how it is read, and whether one is set. `lowercase` is for Nautobot, whose source ids
 * are matched case-insensitively. */
export interface SourceConfig {
  key: string;
  idFromConfig: (config: Record<string, unknown>) => string;
  isConfigured: (config: Record<string, unknown>) => boolean;
}

export function makeSourceConfig(key: string, options: { lowercase?: boolean } = {}): SourceConfig {
  const idFromConfig = (config: Record<string, unknown>): string => {
    const raw = config[key];
    if (typeof raw !== "string" || !raw.trim()) return "";
    return options.lowercase ? raw.trim().toLowerCase() : raw.trim();
  };
  return { key, idFromConfig, isConfigured: (config) => Boolean(idFromConfig(config)) };
}
