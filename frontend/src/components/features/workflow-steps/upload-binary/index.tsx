"use client";

import { useCallback } from "react";

import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { GitSourceConfigPanel } from "@/components/features/workflow-steps/shared/git-source-config-panel";
import { SshCredentialField } from "@/components/features/workflow-steps/shared/ssh-credential-field";

import { boolField, numberField, stringField } from "../shared/config-field-helpers";
import { DEFAULT_SOCKET_TIMEOUT, clampSocketTimeout } from "../shared/device-file-transfer";
import { FieldHeader } from "../shared/field-header";
import { Input } from "@/components/ui/input";
import {
  NetworkDriverOverrideField,
  OverwriteField,
  SocketTimeoutField,
  TransferTextField,
} from "../shared/device-file-transfer-fields";
import { UploadBinaryHelpPanel } from "./help-panel";
import {
  DEFAULT_READ_TIMEOUT,
  MAX_READ_TIMEOUT,
  MIN_READ_TIMEOUT,
  buildUploadBinaryConfig,
  clampReadTimeout,
  hasWhitespace,
  isValidExpectedMd5,
} from "./upload-binary-config";

function UploadBinaryConfigPanel(props: PluginConfigPanelProps) {
  const { config, onChange } = props;

  const sourcePath = stringField(config, "source_path");
  const destinationFilename = stringField(config, "destination_filename");
  const fileSystem = stringField(config, "file_system");
  const expectedMd5 = stringField(config, "expected_md5");

  const patch = useCallback(
    (values: Record<string, unknown>) => onChange(buildUploadBinaryConfig(config, values)),
    [config, onChange],
  );
  const handleSourcePath = useCallback((value: string) => patch({ source_path: value }), [patch]);
  const handleExpectedMd5 = useCallback(
    (value: string) => patch({ expected_md5: value }),
    [patch],
  );
  const handleDestination = useCallback(
    (value: string) => patch({ destination_filename: value }),
    [patch],
  );
  const handleFileSystem = useCallback((value: string) => patch({ file_system: value }), [patch]);
  const handleOverwrite = useCallback((checked: boolean) => patch({ overwrite: checked }), [patch]);
  const handleDriver = useCallback(
    (value: string) => patch({ network_driver_override: value }),
    [patch],
  );
  const handleReadTimeout = useCallback(
    (value: string) => patch({ read_timeout: clampReadTimeout(value) }),
    [patch],
  );
  const handleSocketTimeout = useCallback(
    (value: string) => patch({ socket_timeout: clampSocketTimeout(value) }),
    [patch],
  );

  return (
    <div className="flex flex-col gap-4">
      <SshCredentialField config={config} onChange={onChange} />

      <GitSourceConfigPanel
        {...props}
        description="The repository holding the binary (Settings → Git Repositories). Git LFS pointer files are refused."
        showAllowStaleToggle
      />

      <TransferTextField
        name="source_path"
        value={sourcePath}
        onChange={handleSourcePath}
        placeholder="images/cat9k_iosxe.17.09.04a.SPA.bin"
        hint="Path of the file inside the repository."
      />
      {sourcePath.trim() === "" ? (
        <p className="text-[11px] text-warning-foreground">source_path is not set.</p>
      ) : null}

      <TransferTextField
        name="expected_md5"
        value={expectedMd5}
        onChange={handleExpectedMd5}
        placeholder="32 hex characters (optional)"
        hint="MD5 published by the vendor. When set, the file must match it before any device is contacted."
      />
      {!isValidExpectedMd5(expectedMd5) ? (
        <p className="text-[11px] text-warning-foreground">
          expected_md5 must be 32 hexadecimal characters.
        </p>
      ) : null}

      <TransferTextField
        name="destination_filename"
        value={destinationFilename}
        onChange={handleDestination}
        placeholder="same as the source file name"
        hint="Target filename on the device. Empty uses the file name of source_path."
      />
      {hasWhitespace(destinationFilename) ? (
        <p className="text-[11px] text-warning-foreground">
          destination_filename must not contain spaces or line breaks.
        </p>
      ) : null}

      <TransferTextField
        name="file_system"
        value={fileSystem}
        onChange={handleFileSystem}
        placeholder="flash:"
        hint="Destination filesystem on the device, e.g. flash: or bootflash:."
      />
      {fileSystem.trim() === "" ? (
        <p className="text-[11px] text-warning-foreground">file_system is not set.</p>
      ) : null}
      {hasWhitespace(fileSystem) ? (
        <p className="text-[11px] text-warning-foreground">
          file_system must not contain spaces or line breaks.
        </p>
      ) : null}

      <OverwriteField
        overwrite={boolField(config, "overwrite")}
        onChange={handleOverwrite}
        description="Replace the destination file if it already exists. An identical file (same MD5) is never copied again."
      />

      <NetworkDriverOverrideField
        value={stringField(config, "network_driver_override")}
        onChange={handleDriver}
      />

      <div className="space-y-1.5">
        <FieldHeader name="read_timeout" type="integer" />
        <Input
          type="number"
          min={MIN_READ_TIMEOUT}
          max={MAX_READ_TIMEOUT}
          value={numberField(config, "read_timeout", DEFAULT_READ_TIMEOUT)}
          onChange={(event) => handleReadTimeout(event.target.value)}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Seconds to wait for the device&apos;s md5 check. A large image on slow flash needs
          minutes.
        </p>
      </div>

      <SocketTimeoutField
        socketTimeout={numberField(config, "socket_timeout", DEFAULT_SOCKET_TIMEOUT)}
        onChange={handleSocketTimeout}
        hint="SCP socket timeout in seconds per operation, not for the whole copy."
      />
    </div>
  );
}

export const UploadBinaryPlugin: PluginUIComponent = {
  ConfigPanel: UploadBinaryConfigPanel,
  HelpPanel: UploadBinaryHelpPanel,
};
