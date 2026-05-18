"use client";

import { useCallback, useState } from "react";
import { Eye, EyeOff } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export interface InventorySource {
  url: string;
  token: string;
}

interface InventorySourceDialogProps {
  open: boolean;
  onClose: () => void;
  value: InventorySource;
  onChange: (source: InventorySource) => void;
}

export function InventorySourceDialog({
  open,
  onClose,
  value,
  onChange,
}: InventorySourceDialogProps) {
  const [url, setUrl] = useState(value.url);
  const [token, setToken] = useState(value.token);
  const [showToken, setShowToken] = useState(false);

  const handleOpen = useCallback(() => {
    setUrl(value.url);
    setToken(value.token);
  }, [value]);

  const handleSave = useCallback(() => {
    onChange({ url: url.trim(), token: token.trim() });
    onClose();
  }, [url, token, onChange, onClose]);

  return (
    <Dialog
      open={open}
      onOpenChange={(isOpen) => {
        if (isOpen) handleOpen();
        else onClose();
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Configure Nautobot Source</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <label className="text-xs font-medium" htmlFor="nautobot-url">
              Nautobot URL
            </label>
            <input
              id="nautobot-url"
              className="w-full rounded border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              placeholder="https://nautobot.example.com"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-medium" htmlFor="nautobot-token">
              API Token
            </label>
            <div className="relative">
              <input
                id="nautobot-token"
                type={showToken ? "text" : "password"}
                className="w-full rounded border bg-background px-3 py-1.5 pr-9 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                placeholder="aaabbbccc..."
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
              <button
                type="button"
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                onClick={() => setShowToken((s) => !s)}
                aria-label={showToken ? "Hide token" : "Show token"}
              >
                {showToken ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
            <p className="text-[11px] text-muted-foreground">
              Generate a token in Nautobot under your user profile.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={onClose} type="button">
            Cancel
          </Button>
          <Button size="sm" onClick={handleSave} type="button" disabled={!url.trim()}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
