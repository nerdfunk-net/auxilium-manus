"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { InventoryHelpContent } from "../components/inventory-help";

interface HelpModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function HelpModal({ isOpen, onClose }: HelpModalProps) {
  return (
    <Dialog onOpenChange={(open) => !open && onClose()} open={isOpen}>
      <DialogContent className="flex !h-[95vh] !max-h-[95vh] !w-[95vw] !max-w-[95vw] flex-col overflow-hidden p-0">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle className="text-xl">Device Filter - Help &amp; Examples</DialogTitle>
        </DialogHeader>
        <div className="flex-1 overflow-y-auto px-6 py-6">
          <InventoryHelpContent />
        </div>
        <div className="flex justify-end border-t bg-muted/30 px-6 py-4">
          <Button onClick={onClose} type="button">
            Close
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
