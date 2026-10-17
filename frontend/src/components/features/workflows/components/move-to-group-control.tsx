"use client";

import { LogOut } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export interface MoveTargetGroup {
  id: string;
  title: string;
}

interface MoveToGroupControlProps {
  nodeIds: string[];
  /** Groups a step can be moved into (shown on the root canvas). */
  groups: MoveTargetGroup[];
  /** True while viewing inside a group — the selected steps are its members. */
  isInsideGroup: boolean;
  onMoveToGroup?: (nodeIds: string[], groupId: string) => void;
  onMoveOutOfGroup?: (nodeIds: string[]) => void;
}

/** "Move to group…" on the root canvas, "Move out of group" inside a group. */
export function MoveToGroupControl({
  nodeIds,
  groups,
  isInsideGroup,
  onMoveToGroup,
  onMoveOutOfGroup,
}: MoveToGroupControlProps) {
  if (isInsideGroup) {
    return (
      <Button
        className="mt-2 w-full gap-1.5"
        onClick={() => onMoveOutOfGroup?.(nodeIds)}
        size="sm"
        variant="outline"
      >
        <LogOut className="size-3.5" aria-hidden />
        Move out of group
      </Button>
    );
  }

  if (groups.length === 0) return null;

  return (
    <div className="mt-2">
      <Select
        // Controlled at "" so the placeholder returns after each move.
        value=""
        onValueChange={(groupId) => onMoveToGroup?.(nodeIds, groupId)}
      >
        <SelectTrigger aria-label="Move to group" className="w-full" size="sm">
          <SelectValue placeholder="Move to group…" />
        </SelectTrigger>
        <SelectContent>
          {groups.map((group) => (
            <SelectItem key={group.id} value={group.id}>
              {group.title}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
