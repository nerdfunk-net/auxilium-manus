"use client";

import { X } from "lucide-react";

import { Button } from "@/components/ui/button";

import type { ConditionItem as ConditionItemType } from "../types/device-selector";

interface ConditionItemProps {
  item: ConditionItemType;
  onRemove: (id: string) => void;
  getFieldLabel: (field: string) => string;
}

export function ConditionItem({ item, onRemove, getFieldLabel }: ConditionItemProps) {
  return (
    <div className="flex items-center gap-2">
      <div className="inline-flex items-center space-x-2 rounded bg-blue-100 px-3 py-1.5 text-sm text-blue-800">
        <span className="font-medium">{getFieldLabel(item.field)}</span>
        <span className="text-gray-600">{item.operator}</span>
        <span className="font-medium">&quot;{item.value}&quot;</span>
        <Button
          className="h-4 w-4 p-0 hover:bg-blue-200"
          onClick={() => onRemove(item.id)}
          size="sm"
          title="Delete condition"
          type="button"
          variant="ghost"
        >
          <X className="h-3 w-3" />
        </Button>
      </div>
    </div>
  );
}
