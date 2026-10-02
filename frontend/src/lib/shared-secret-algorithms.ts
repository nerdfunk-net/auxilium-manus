/**
 * Symmetric algorithms available for `shared_secret` credentials and the
 * Encrypt/Decrypt Attribute workflow steps.
 *
 * Keep in sync with `SUPPORTED_ALGORITHMS` / `ALGORITHM_LABELS` in
 * `backend/core/passphrase_cipher.py`.
 */
export interface SharedSecretAlgorithmOption {
  value: string;
  label: string;
}

export const SHARED_SECRET_ALGORITHMS: readonly SharedSecretAlgorithmOption[] = [
  { value: "aes-256-gcm", label: "AES-256-GCM (PBKDF2-SHA256)" },
];

/**
 * Algorithms selectable on the Encrypt/Decrypt Attribute steps. Superset of the
 * credential algorithms: the keyless Cisco formats need no shared secret.
 *
 * Keep in sync with `backend/core/cisco_secret.py` (`CISCO_ALGORITHMS`).
 */
export const CISCO_TYPE7 = "cisco-type7";

export const ENCRYPT_STEP_ALGORITHMS: readonly SharedSecretAlgorithmOption[] = [
  ...SHARED_SECRET_ALGORITHMS,
  { value: CISCO_TYPE7, label: "Cisco type 7 (reversible obfuscation)" },
  { value: "cisco-type8", label: "Cisco type 8 (PBKDF2-SHA256, one-way)" },
  { value: "cisco-type9", label: "Cisco type 9 (scrypt, one-way)" },
];

/** Type 8/9 are one-way hashes, so only type 7 can be decrypted. */
export const DECRYPT_STEP_ALGORITHMS: readonly SharedSecretAlgorithmOption[] = [
  ...SHARED_SECRET_ALGORITHMS,
  { value: CISCO_TYPE7, label: "Cisco type 7 (reversible obfuscation)" },
];

/** True for the Cisco formats, which use no shared-secret credential. */
export function isKeylessAlgorithm(value: string | null | undefined): boolean {
  return typeof value === "string" && value.startsWith("cisco-type");
}

export const DEFAULT_SHARED_SECRET_ALGORITHM = "aes-256-gcm";

export function sharedSecretAlgorithmLabel(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  return (
    SHARED_SECRET_ALGORITHMS.find((option) => option.value === value)?.label ?? value
  );
}
