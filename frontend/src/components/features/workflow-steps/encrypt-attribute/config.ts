export interface EncryptAttributeConfig {
  source_path: string;
  destination_path: string;
  credential_reference: string;
  /** Blank = use the shared-secret credential's configured algorithm. */
  algorithm: string;
}

export const DEFAULT_ENCRYPT_ATTRIBUTE_CONFIG: EncryptAttributeConfig = {
  source_path: "",
  destination_path: "",
  credential_reference: "",
  algorithm: "",
};

function stringField(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

export function parseEncryptAttributeConfig(
  config: Record<string, unknown>,
): EncryptAttributeConfig {
  return {
    source_path: stringField(config, "source_path"),
    destination_path: stringField(config, "destination_path"),
    credential_reference: stringField(config, "credential_reference"),
    algorithm: stringField(config, "algorithm"),
  };
}

export function buildEncryptAttributeConfig(
  config: Record<string, unknown>,
  patch: Partial<EncryptAttributeConfig>,
): Record<string, unknown> {
  return { ...config, ...parseEncryptAttributeConfig(config), ...patch };
}
