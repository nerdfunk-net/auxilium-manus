"use client";

import { GripVertical, Pencil, X } from "lucide-react";
import { useState, type KeyboardEvent, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type {
  WidgetDefinition,
  WidgetSettings,
} from "@/components/features/dashboard/types/dashboard";

interface WidgetShellProps {
  definition: WidgetDefinition;
  isEditing: boolean;
  onRemove: () => void;
  onSettingsChange: (patch: WidgetSettings) => void;
  settings?: WidgetSettings;
  children: ReactNode;
}

export function WidgetShell({
  definition,
  isEditing,
  onRemove,
  onSettingsChange,
  settings,
  children,
}: WidgetShellProps) {
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");

  const customTitle = typeof settings?.title === "string" ? settings.title : "";
  const displayTitle = customTitle.trim() || definition.title;

  const startEditingTitle = () => {
    setDraftTitle(customTitle);
    setIsEditingTitle(true);
  };

  const commitTitle = () => {
    setIsEditingTitle(false);
    const trimmed = draftTitle.trim();
    if (trimmed !== customTitle) {
      onSettingsChange({ title: trimmed });
    }
  };

  const handleTitleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.currentTarget.blur();
    } else if (event.key === "Escape") {
      setIsEditingTitle(false);
    }
  };

  return (
    <Card className="flex h-full flex-col overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0 p-4">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {isEditing ? (
            <GripVertical className="drag-handle size-4 shrink-0 cursor-grab text-muted-foreground" />
          ) : null}
          <definition.icon className="size-4 shrink-0 text-muted-foreground" />
          {isEditingTitle ? (
            <Input
              autoFocus
              className="h-7 flex-1 text-sm"
              onBlur={commitTitle}
              onChange={(event) => setDraftTitle(event.target.value)}
              onKeyDown={handleTitleKeyDown}
              placeholder={definition.title}
              value={draftTitle}
            />
          ) : (
            <CardTitle className="truncate text-sm">{displayTitle}</CardTitle>
          )}
        </div>
        {isEditing && !isEditingTitle ? (
          <div className="flex shrink-0 items-center gap-1">
            <Button
              aria-label={`Edit ${displayTitle} card title`}
              className="size-6 shrink-0"
              onClick={startEditingTitle}
              size="icon"
              type="button"
              variant="ghost"
            >
              <Pencil className="size-3.5" />
            </Button>
            <Button
              aria-label={`Remove ${displayTitle} card`}
              className="size-6 shrink-0"
              onClick={onRemove}
              size="icon"
              type="button"
              variant="ghost"
            >
              <X className="size-4" />
            </Button>
          </div>
        ) : null}
      </CardHeader>
      <CardContent className="flex-1 overflow-hidden p-4 pt-0">{children}</CardContent>
    </Card>
  );
}
