"use client";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { MAX_SOCKET_TIMEOUT, MIN_SOCKET_TIMEOUT } from "./upload-config-config";

export interface UploadConfigSocketTimeoutFieldsProps {
  socketTimeout: number;
  onSocketTimeoutChange: (value: string) => void;
}

export function UploadConfigSocketTimeoutFields({
  socketTimeout,
  onSocketTimeoutChange,
}: UploadConfigSocketTimeoutFieldsProps) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs font-medium">socket_timeout</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          integer
        </Badge>
      </div>
      <Input
        type="number"
        min={MIN_SOCKET_TIMEOUT}
        max={MAX_SOCKET_TIMEOUT}
        value={socketTimeout}
        onChange={(event) => onSocketTimeoutChange(event.target.value)}
        className="h-8 font-mono text-xs"
      />
      <p className="text-[11px] text-muted-foreground">
        SCP/SFTP socket timeout in seconds. Raise this for large config files or slow links.
      </p>
    </div>
  );
}

export interface UploadConfigTransferFieldsProps {
  overwrite: boolean;
  inlineTransfer: boolean;
  onOverwriteChange: (checked: boolean) => void;
  onInlineTransferChange: (checked: boolean) => void;
}

export function UploadConfigTransferFields({
  overwrite,
  inlineTransfer,
  onOverwriteChange,
  onInlineTransferChange,
}: UploadConfigTransferFieldsProps) {
  return (
    <>
      <div className="space-y-1.5">
        <div className="flex items-start gap-2">
          <input
            id="overwrite"
            type="checkbox"
            checked={overwrite}
            onChange={(event) => onOverwriteChange(event.target.checked)}
            className="mt-0.5 size-4 rounded border"
          />
          <div className="space-y-0.5">
            <Label htmlFor="overwrite" className="font-mono text-xs font-medium">
              overwrite
            </Label>
            <p className="text-[11px] text-muted-foreground">
              Replace the destination file if it already exists.
            </p>
          </div>
        </div>
        {overwrite ? (
          <p className="rounded-lg border border-warning-border bg-warning px-3 py-2 text-[11px] text-warning-foreground">
            This will replace the existing file on the device if one exists at this path.
          </p>
        ) : null}
      </div>

      <div className="flex items-start gap-2">
        <input
          id="inline-transfer"
          type="checkbox"
          checked={inlineTransfer}
          onChange={(event) => onInlineTransferChange(event.target.checked)}
          className="mt-0.5 size-4 rounded border"
        />
        <div className="space-y-0.5">
          <Label htmlFor="inline-transfer" className="font-mono text-xs font-medium">
            inline_transfer
          </Label>
          <p className="text-[11px] text-muted-foreground">
            Use Netmiko&apos;s inline (non-SCP) transfer for text files instead of SCP/SFTP —
            useful when the device has no SCP server enabled.
          </p>
        </div>
      </div>
    </>
  );
}
