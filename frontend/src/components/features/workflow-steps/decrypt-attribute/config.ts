export interface DecryptAttributeConfig {
  source_path: string;
  destination_path: string;
  credential_reference: string;
  /** Blank = trust the token header / the credential's configured algorithm. */
  algorithm: string;
  /**
   * Blank = scalar mode (source_path is one token).
   * Set to a field name = list mode: source_path resolves to a list and this
   * field is decrypted on every entry, sealed, rewriting the list in place
   * (or at destination_path when set).
   */
  item_field: string;
}

export const DEFAULT_DECRYPT_ATTRIBUTE_CONFIG: DecryptAttributeConfig = {
  source_path: "",
  destination_path: "",
  credential_reference: "",
  algorithm: "",
  item_field: "",
};

function stringField(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

export function parseDecryptAttributeConfig(
  config: Record<string, unknown>,
): DecryptAttributeConfig {
  return {
    source_path: stringField(config, "source_path"),
    destination_path: stringField(config, "destination_path"),
    credential_reference: stringField(config, "credential_reference"),
    algorithm: stringField(config, "algorithm"),
    item_field: stringField(config, "item_field"),
  };
}

export function buildDecryptAttributeConfig(
  config: Record<string, unknown>,
  patch: Partial<DecryptAttributeConfig>,
): Record<string, unknown> {
  return { ...config, ...parseDecryptAttributeConfig(config), ...patch };
}
