/**
 * Config handling shared by the steps that copy a file to a device over SCP
 * (`upload-config`, `upload-binary`): the common keys and the socket-timeout bounds, which
 * mirror `workflow_steps/common/device_file_upload.py`.
 */
import { boolField, numberField, stringField, type ConfigRecord } from "./config-field-helpers";

export const DEFAULT_SOCKET_TIMEOUT = 10;
export const MIN_SOCKET_TIMEOUT = 5;
export const MAX_SOCKET_TIMEOUT = 300;

/** Parse the number input's text and keep it inside the bounds the backend enforces. */
export function clampSocketTimeout(value: string): number {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed)
    ? Math.min(MAX_SOCKET_TIMEOUT, Math.max(MIN_SOCKET_TIMEOUT, parsed))
    : MIN_SOCKET_TIMEOUT;
}

/** The keys both file-upload steps store, normalised (a missing key gets its default). */
export function deviceFileTransferConfig(config: ConfigRecord): ConfigRecord {
  return {
    credential_reference: stringField(config, "credential_reference"),
    credential_source: config.credential_source === "run_param" ? "run_param" : "fixed",
    credential_param: stringField(config, "credential_param"),
    destination_filename: stringField(config, "destination_filename"),
    file_system: stringField(config, "file_system"),
    overwrite: boolField(config, "overwrite"),
    network_driver_override: stringField(config, "network_driver_override"),
    socket_timeout: numberField(config, "socket_timeout", DEFAULT_SOCKET_TIMEOUT),
  };
}
