import { Minus, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FieldHeader } from "@/components/features/workflow-steps/shared/field-header";

interface CommandListFieldProps {
  commands: string[];
  onChange: (index: number, value: string) => void;
  onAdd: () => void;
  onRemove: (index: number) => void;
}

export function CommandListField({ commands, onChange, onAdd, onRemove }: CommandListFieldProps) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <FieldHeader name="commands" type="string_list" />
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="size-7"
          onClick={onAdd}
          title="Add command"
        >
          <Plus className="size-3.5" />
        </Button>
      </div>

      <div className="space-y-2">
        {commands.map((command, index) => (
          <div key={`command-${index}`} className="flex items-center gap-2">
            <Input
              value={command}
              onChange={(event) => onChange(index, event.target.value)}
              placeholder="show version"
              className="h-8 font-mono text-xs"
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="size-8 shrink-0"
              onClick={() => onRemove(index)}
              disabled={commands.length <= 1}
              title="Remove command"
            >
              <Minus className="size-3.5" />
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}
