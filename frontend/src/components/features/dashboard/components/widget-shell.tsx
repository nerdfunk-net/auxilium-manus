"use client";

import { GripVertical, X } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { WidgetDefinition } from "@/components/features/dashboard/types/dashboard";

interface WidgetShellProps {
  definition: WidgetDefinition;
  isEditing: boolean;
  onRemove: () => void;
  children: ReactNode;
}

export function WidgetShell({ definition, isEditing, onRemove, children }: WidgetShellProps) {
  return (
    <Card className="flex h-full flex-col overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0 p-4">
        <div className="flex min-w-0 items-center gap-2">
          {isEditing ? (
            <GripVertical className="drag-handle size-4 shrink-0 cursor-grab text-muted-foreground" />
          ) : null}
          <definition.icon className="size-4 shrink-0 text-muted-foreground" />
          <CardTitle className="truncate text-sm">{definition.title}</CardTitle>
        </div>
        {isEditing ? (
          <Button
            aria-label={`Remove ${definition.title} card`}
            className="size-6 shrink-0"
            onClick={onRemove}
            size="icon"
            type="button"
            variant="ghost"
          >
            <X className="size-4" />
          </Button>
        ) : null}
      </CardHeader>
      <CardContent className="flex-1 overflow-hidden p-4 pt-0">{children}</CardContent>
    </Card>
  );
}
