"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useLoggingSettingsMutations } from "@/hooks/queries/use-logging-settings-mutations";
import { useLoggingSettingsQuery } from "@/hooks/queries/use-logging-settings-query";

const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] as const;

const formSchema = z.object({
  default_log_level: z.enum(LOG_LEVELS),
  workflow_log_enabled: z.boolean(),
  workflow_log_level: z.enum(LOG_LEVELS),
  workflow_log_max_mb: z.number().int().min(1).max(1024),
  workflow_log_backup_count: z.number().int().min(0).max(50),
});

type FormValues = z.infer<typeof formSchema>;

interface MutedLoggerRow {
  name: string;
  level: (typeof LOG_LEVELS)[number];
}

const EMPTY_DEFAULTS: FormValues = {
  default_log_level: "INFO",
  workflow_log_enabled: true,
  workflow_log_level: "INFO",
  workflow_log_max_mb: 10,
  workflow_log_backup_count: 5,
};

const BYTES_PER_MB = 1_048_576;

function recordToRows(muted: Record<string, string>): MutedLoggerRow[] {
  return Object.entries(muted)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, level]) => ({ name, level: level as MutedLoggerRow["level"] }));
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

export function LoggingSettingsCanvas() {
  const { data: settingsData, isLoading } = useLoggingSettingsQuery();
  const { saveSettings } = useLoggingSettingsMutations();

  const [mutedLoggers, setMutedLoggers] = useState<MutedLoggerRow[]>([]);
  const [newLoggerName, setNewLoggerName] = useState("");

  // Re-sync local editable rows whenever a fresh settingsData object arrives
  // (initial load or refetch) — adjusted during render (React's documented
  // "storing information from previous renders" pattern), not in an effect,
  // so it doesn't cause an extra cascading render.
  const [syncedMutedLoggers, setSyncedMutedLoggers] = useState<Record<string, string> | undefined>(
    undefined,
  );
  if (settingsData && settingsData.muted_loggers !== syncedMutedLoggers) {
    setSyncedMutedLoggers(settingsData.muted_loggers);
    setMutedLoggers(recordToRows(settingsData.muted_loggers));
  }

  const defaultValues = useMemo<FormValues>(
    () =>
      settingsData
        ? {
            default_log_level: settingsData.default_log_level as FormValues["default_log_level"],
            workflow_log_enabled: settingsData.workflow_log_enabled,
            workflow_log_level: settingsData.workflow_log_level as FormValues["workflow_log_level"],
            workflow_log_max_mb: Math.round(settingsData.workflow_log_max_bytes / BYTES_PER_MB),
            workflow_log_backup_count: settingsData.workflow_log_backup_count,
          }
        : EMPTY_DEFAULTS,
    [settingsData],
  );

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    values: defaultValues,
  });

  const handleAddLogger = () => {
    const name = newLoggerName.trim();
    if (!name || mutedLoggers.some((row) => row.name === name)) {
      return;
    }
    const newRow: MutedLoggerRow = { name, level: "WARNING" };
    setMutedLoggers((rows) => [...rows, newRow].sort((a, b) => a.name.localeCompare(b.name)));
    setNewLoggerName("");
  };

  const handleRemoveLogger = (name: string) => {
    setMutedLoggers((rows) => rows.filter((row) => row.name !== name));
  };

  const handleLoggerLevelChange = (name: string, level: string) => {
    setMutedLoggers((rows) =>
      rows.map((row) => (row.name === name ? { ...row, level: level as MutedLoggerRow["level"] } : row)),
    );
  };

  const handleSave = (values: FormValues) => {
    saveSettings.mutate({
      default_log_level: values.default_log_level,
      workflow_log_enabled: values.workflow_log_enabled,
      workflow_log_level: values.workflow_log_level,
      workflow_log_max_bytes: values.workflow_log_max_mb * BYTES_PER_MB,
      workflow_log_backup_count: values.workflow_log_backup_count,
      muted_loggers: Object.fromEntries(mutedLoggers.map((row) => [row.name, row.level])),
    });
  };

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto bg-slate-50 p-8">
      <div className="mx-auto w-full max-w-2xl space-y-6">
        {/* Log files card */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Log Files</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {isLoading || !settingsData ? (
              <p className="text-sm text-muted-foreground">Loading…</p>
            ) : (
              <div className="space-y-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Directory</span>
                  <span className="font-mono text-xs">{settingsData.log_directory}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">API server</span>
                  <span className="font-mono text-xs">{settingsData.app_log_file}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Workflow worker (all output)</span>
                  <span className="font-mono text-xs">{settingsData.worker_log_file}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Workflow execution (steps + devices only)</span>
                  <span className="font-mono text-xs">{settingsData.workflow_log_file}</span>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSave)} className="space-y-6">
            {/* Default level */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Default Log Level</CardTitle>
              </CardHeader>
              <CardContent>
                <FormField
                  control={form.control}
                  name="default_log_level"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Root level</FormLabel>
                      <Select value={field.value} onValueChange={field.onChange}>
                        <FormControl>
                          <SelectTrigger className="w-40">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {LOG_LEVELS.map((level) => (
                            <SelectItem key={level} value={level}>
                              {level}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormDescription>
                        Applies to app.log / worker.log and anything not otherwise overridden below.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </CardContent>
            </Card>

            {/* Workflow log */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Workflow Execution Log</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField
                  control={form.control}
                  name="workflow_log_enabled"
                  render={({ field }) => (
                    <FormItem className="flex items-center justify-between rounded-lg border p-3">
                      <div>
                        <FormLabel>Write workflow.log</FormLabel>
                        <FormDescription>
                          A dedicated log containing only step start/finish and per-device
                          processing lines — no netmiko, paramiko, or gRPC noise.
                        </FormDescription>
                      </div>
                      <FormControl>
                        <Switch checked={field.value} onCheckedChange={field.onChange} />
                      </FormControl>
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="workflow_log_level"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Level</FormLabel>
                      <Select value={field.value} onValueChange={field.onChange}>
                        <FormControl>
                          <SelectTrigger className="w-40">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {LOG_LEVELS.map((level) => (
                            <SelectItem key={level} value={level}>
                              {level}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <div className="grid grid-cols-2 gap-4">
                  <FormField
                    control={form.control}
                    name="workflow_log_max_mb"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Max file size (MB)</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            min={1}
                            max={1024}
                            {...field}
                            onChange={(e) => field.onChange(e.target.valueAsNumber)}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="workflow_log_backup_count"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Backups to keep</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            min={0}
                            max={50}
                            {...field}
                            onChange={(e) => field.onChange(e.target.valueAsNumber)}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              </CardContent>
            </Card>

            {/* Muted loggers */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Muted Loggers</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="text-sm text-muted-foreground">
                  Third-party loggers that are noisy below the level shown. Set a logger to
                  DEBUG or INFO here to see it again.
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
                          onChange={(level) => handleLoggerLevelChange(row.name, level)}
                        />
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          onClick={() => handleRemoveLogger(row.name)}
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
                    onChange={(e) => setNewLoggerName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        handleAddLogger();
                      }
                    }}
                  />
                  <Button type="button" variant="outline" onClick={handleAddLogger}>
                    <Plus className="mr-2 size-4" />
                    Add
                  </Button>
                </div>
              </CardContent>
            </Card>

            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">
                Changes apply to the API server immediately. Restart the workflow worker for it
                to pick up changes.
              </p>
              <Button type="submit" disabled={saveSettings.isPending}>
                {saveSettings.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
                Save Changes
              </Button>
            </div>
          </form>
        </Form>
      </div>
    </div>
  );
}
