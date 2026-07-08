"use client";

import { Minus, Play, Plus, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface ConfigureCommandsDialogProps {
  open: boolean;
  commands: string[];
  useTextfsm: boolean;
  canExecute: boolean;
  isExecuting: boolean;
  executeHint?: string;
  onOpenChange: (open: boolean) => void;
  onCommandsChange: (commands: string[]) => void;
  onUseTextfsmChange: (value: boolean) => void;
  onExecute: () => void;
}

export function ConfigureCommandsDialog({
  open,
  commands,
  useTextfsm,
  canExecute,
  isExecuting,
  executeHint,
  onOpenChange,
  onCommandsChange,
  onUseTextfsmChange,
  onExecute,
}: ConfigureCommandsDialogProps) {
  // Always render at least one editable row.
  const rows = commands.length > 0 ? commands : [""];

  const handleChange = (index: number, value: string) => {
    const next = [...rows];
    next[index] = value;
    onCommandsChange(next);
  };

  const handleAdd = () => {
    onCommandsChange([...rows, ""]);
  };

  const handleRemove = (index: number) => {
    if (rows.length <= 1) {
      onCommandsChange([""]);
      return;
    }
    onCommandsChange(rows.filter((_, itemIndex) => itemIndex !== index));
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Configure commands</DialogTitle>
          <DialogDescription>
            Commands run against the test device in the order below. Their output
            populates <code>command</code>, <code>commands</code> and{" "}
            <code>commands_by_name</code> — the same variables the &quot;Render Jinja
            Template&quot; workflow step provides.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <Label className="font-mono text-xs font-medium">commands</Label>
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="size-7"
                onClick={handleAdd}
                title="Add command"
              >
                <Plus className="size-3.5" />
              </Button>
            </div>

            <div className="space-y-2">
              {rows.map((command, index) => (
                <div key={`command-${index}`} className="flex items-center gap-2">
                  <span className="w-5 shrink-0 text-right font-mono text-xs text-muted-foreground">
                    {index + 1}
                  </span>
                  <Input
                    value={command}
                    onChange={(event) => handleChange(index, event.target.value)}
                    placeholder="show version"
                    className="h-8 font-mono text-xs"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className="size-8 shrink-0"
                    onClick={() => handleRemove(index)}
                    disabled={rows.length <= 1 && !rows[0]}
                    title="Remove command"
                  >
                    <Minus className="size-3.5" />
                  </Button>
                </div>
              ))}
            </div>
          </div>

          <div className="flex items-start gap-2">
            <input
              id="template-use-textfsm"
              type="checkbox"
              checked={useTextfsm}
              onChange={(event) => onUseTextfsmChange(event.target.checked)}
              className="mt-0.5 size-4 rounded border"
            />
            <div className="space-y-0.5">
              <Label htmlFor="template-use-textfsm" className="font-mono text-xs font-medium">
                use_textfsm
              </Label>
              <p className="text-[11px] text-muted-foreground">
                Parse each command&apos;s output with TextFSM when a template is
                available. When off, <code>parsed</code> stays null and you use{" "}
                <code>raw</code>.
              </p>
            </div>
          </div>

          {executeHint && !canExecute ? (
            <p className="text-[11px] text-amber-600">{executeHint}</p>
          ) : null}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button
            type="button"
            disabled={!canExecute || isExecuting}
            onClick={onExecute}
          >
            {isExecuting ? (
              <RefreshCw className="size-4 animate-spin" />
            ) : (
              <Play className="size-4" />
            )}
            Execute commands
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
