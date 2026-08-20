"use client";

import { useCallback } from "react";
import { Loader2, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";

interface ManageInventoryImportExportProps {
  isImporting: boolean;
  onImport: (file: File) => Promise<void>;
  onClose: () => void;
}

export function ManageInventoryImportExport({
  isImporting,
  onImport,
  onClose,
}: ManageInventoryImportExportProps) {
  const handleImportClick = useCallback(() => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json";
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (file) {
        await onImport(file);
      }
    };
    input.click();
  }, [onImport]);

  return (
    <div className="flex items-center justify-between w-full">
      <Button
        variant="outline"
        onClick={handleImportClick}
        disabled={isImporting}
        className="flex items-center gap-2"
      >
        {isImporting ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Upload className="h-4 w-4" />
        )}
        Import Inventory
      </Button>
      <Button variant="outline" onClick={onClose}>
        Close
      </Button>
    </div>
  );
}
