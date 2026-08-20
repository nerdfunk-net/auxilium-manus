"use client";

import { Plus, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] as const;

export interface MutedLoggerRow {
  name: string;
  level: (typeof LOG_LEVELS)[number];
}

function LevelSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="w-32">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {LOG_LEVELS.map((level) => (
          <SelectItem key={level} value={level}>
            {level}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export interface LoggingOverridesCardProps {
  mutedLoggers: MutedLoggerRow[];
  newLoggerName: string;
  onNewLoggerNameChange: (value: string) => void;
  onAddLogger: () => void;
  onRemoveLogger: (name: string) => void;
  onLoggerLevelChange: (name: string, level: string) => void;
}

export function LoggingOverridesCard({
  mutedLoggers,
  newLoggerName,
  onNewLoggerNameChange,
  onAddLogger,
  onRemoveLogger,
  onLoggerLevelChange,
}: LoggingOverridesCardProps) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Muted Loggers</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Third-party loggers that are noisy below the level shown. Set a logger to DEBUG or INFO
          here to see it again.
        </p>

        <div className="space-y-2">
          {mutedLoggers.length === 0 && (
            <p className="text-sm text-muted-foreground">No loggers muted.</p>
          )}
          {mutedLoggers.map((row) => (
            <div
              key={row.name}
              className="flex items-center justify-between gap-2 rounded-lg border p-2"
            >
              <Badge variant="outline" className="font-mono text-xs">
                {row.name}
              </Badge>
              <div className="flex items-center gap-2">
                <LevelSelect
                  value={row.level}
                  onChange={(level) => onLoggerLevelChange(row.name, level)}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => onRemoveLogger(row.name)}
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <Input
            placeholder="logger name, e.g. urllib3"
            value={newLoggerName}
            onChange={(e) => onNewLoggerNameChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                onAddLogger();
              }
            }}
          />
          <Button type="button" variant="outline" onClick={onAddLogger}>
            <Plus className="mr-2 size-4" />
            Add
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
