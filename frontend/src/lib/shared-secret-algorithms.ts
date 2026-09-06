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

export const DEFAULT_SHARED_SECRET_ALGORITHM = "aes-256-gcm";

export function sharedSecretAlgorithmLabel(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  return (
    SHARED_SECRET_ALGORITHMS.find((option) => option.value === value)?.label ?? value
  );
}
