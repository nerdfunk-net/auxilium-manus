"use client";

import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { CheckboxField } from "../shared/checkbox-field";
import { OverwriteField } from "../shared/device-file-transfer-fields";
import { VERIFY_ALGORITHM_OPTIONS, type VerifyAlgorithm } from "./upload-config-config";

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
      <OverwriteField overwrite={overwrite} onChange={onOverwriteChange} />
      <CheckboxField
        id="inline-transfer"
        label="inline_transfer"
        checked={inlineTransfer}
        onCheckedChange={onInlineTransferChange}
        description="Use Netmiko's inline (non-SCP) transfer for text files instead of SCP/SFTP — useful when the device has no SCP server enabled."
      />
    </>
  );
}

export interface UploadConfigVerifyFieldsProps {
  verifyContent: boolean;
  verifyAlgorithm: VerifyAlgorithm;
  onVerifyContentChange: (checked: boolean) => void;
  onVerifyAlgorithmChange: (value: VerifyAlgorithm) => void;
}

export function UploadConfigVerifyFields({
  verifyContent,
  verifyAlgorithm,
  onVerifyContentChange,
  onVerifyAlgorithmChange,
}: UploadConfigVerifyFieldsProps) {
  return (
    <div className="space-y-2 border-t pt-3">
      <div className="flex items-center gap-2">
        <Checkbox
          id="verify-content"
          checked={verifyContent}
          onCheckedChange={(checked) => onVerifyContentChange(checked === true)}
        />
        <Label htmlFor="verify-content" className="font-mono text-xs font-medium">
          verify_content
        </Label>
      </div>
      <p className="text-[11px] text-muted-foreground">
        Compare a checksum of the uploaded content against the device&apos;s own{" "}
        <span className="font-mono">verify</span> command output after the transfer.
      </p>
      {verifyContent ? (
        <div className="space-y-1 pl-1">
          <Label className="text-[11px] text-muted-foreground">Algorithm</Label>
          <Select
            value={verifyAlgorithm}
            onValueChange={(value) => onVerifyAlgorithmChange(value as VerifyAlgorithm)}
          >
            <SelectTrigger className="h-7 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {VERIFY_ALGORITHM_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ) : null}
    </div>
  );
}
