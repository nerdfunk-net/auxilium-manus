import {
  boolField,
  numberField,
  stringField,
  type ConfigRecord,
} from "../shared/config-field-helpers";
import { deviceFileTransferConfig } from "../shared/device-file-transfer";

export const DEFAULT_READ_TIMEOUT = 600;
export const MIN_READ_TIMEOUT = 5;
export const MAX_READ_TIMEOUT = 600;

/** Parse the number input's text and keep it inside the bounds the backend enforces. */
export function clampReadTimeout(value: string): number {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed)
    ? Math.min(MAX_READ_TIMEOUT, Math.max(MIN_READ_TIMEOUT, parsed))
    : MIN_READ_TIMEOUT;
}

/** The device filesystem and file name are pasted into CLI commands: one token, no spaces. */
export function hasWhitespace(value: string): boolean {
  return /\s/.test(value.trim());
}

/**
 * Normalised `upload-binary` config. Every key is kept on each edit, including the two the
 * shared Git source panel writes (`git_repository_id`, `allow_stale_repository`): a builder that
 * dropped them would reset the repository on the next edit.
 */
export function buildUploadBinaryConfig(
  config: ConfigRecord,
  patch: ConfigRecord = {},
): ConfigRecord {
  return {
    ...deviceFileTransferConfig(config),
    git_repository_id:
      typeof config.git_repository_id === "number" ? config.git_repository_id : null,
    allow_stale_repository: boolField(config, "allow_stale_repository"),
    source_path: stringField(config, "source_path"),
    expected_md5: stringField(config, "expected_md5"),
    read_timeout: numberField(config, "read_timeout", DEFAULT_READ_TIMEOUT),
    ...patch,
  };
}

const MD5_PATTERN = /^[0-9a-fA-F]{32}$/;

/** True for an empty value (the checksum is optional) or 32 hexadecimal characters. */
export function isValidExpectedMd5(value: string): boolean {
  const trimmed = value.trim();
  return trimmed === "" || MD5_PATTERN.test(trimmed);
}
