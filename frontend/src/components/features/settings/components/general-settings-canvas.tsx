"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2, RotateCcw } from "lucide-react";
import { useMemo } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

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
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useGeneralSettingsMutations } from "@/hooks/queries/use-general-settings-mutations";
import { useGeneralSettingsQuery } from "@/hooks/queries/use-general-settings-query";

const formSchema = z.object({
  session_timeout_minutes: z.number().int().min(1).max(1440),
  default_export_directory: z.string(),
  switch_to_runs_on_start: z.boolean(),
});

type FormValues = z.infer<typeof formSchema>;

const EMPTY_DEFAULTS: FormValues = {
  session_timeout_minutes: 20,
  default_export_directory: "",
  switch_to_runs_on_start: true,
};

export function GeneralSettingsCanvas() {
  const { data: settingsData } = useGeneralSettingsQuery();
  const { saveSettings } = useGeneralSettingsMutations();

  const defaultValues = useMemo<FormValues>(
    () =>
      settingsData
        ? {
            session_timeout_minutes: settingsData.session_timeout_minutes,
            default_export_directory: settingsData.default_export_directory,
            switch_to_runs_on_start: settingsData.switch_to_runs_on_start,
          }
        : EMPTY_DEFAULTS,
    [settingsData],
  );

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    values: defaultValues,
  });

  const handleSave = (values: FormValues) => {
    saveSettings.mutate(values);
  };

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto bg-muted p-8">
      <div className="mx-auto w-full max-w-2xl space-y-6">
        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSave)} className="space-y-6">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Session</CardTitle>
              </CardHeader>
              <CardContent>
                <FormField
                  control={form.control}
                  name="session_timeout_minutes"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Default session timeout (minutes)</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          min={1}
                          max={1440}
                          className="w-40"
                          {...field}
                          onChange={(e) => field.onChange(e.target.valueAsNumber)}
                        />
                      </FormControl>
                      <FormDescription>
                        How long a session can be idle before the user is signed out.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Artifacts</CardTitle>
              </CardHeader>
              <CardContent>
                <FormField
                  control={form.control}
                  name="default_export_directory"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Default export directory</FormLabel>
                      <div className="flex items-center gap-2">
                        <FormControl>
                          <Input className="font-mono text-xs" {...field} />
                        </FormControl>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="shrink-0"
                              aria-label="Use default directory"
                              disabled={!settingsData}
                              onClick={() =>
                                settingsData &&
                                field.onChange(settingsData.resolved_export_directory)
                              }
                            >
                              <RotateCcw className="size-4" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>
                            {settingsData
                              ? `Use default (${settingsData.resolved_export_directory})`
                              : "Use default"}
                          </TooltipContent>
                        </Tooltip>
                      </div>
                      <FormDescription>
                        Base directory used by the Store Artifact workflow step when
                        writing files to disk. Leave blank to use the server&apos;s
                        configured data directory.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Workflow Runs</CardTitle>
              </CardHeader>
              <CardContent>
                <FormField
                  control={form.control}
                  name="switch_to_runs_on_start"
                  render={({ field }) => (
                    <FormItem className="flex items-center justify-between rounded-lg border p-3">
                      <div>
                        <FormLabel>Switch to Runs when a run starts</FormLabel>
                        <FormDescription>
                          Navigate to the Runs page automatically when you start a
                          workflow run. Debug runs always stay on the canvas.
                        </FormDescription>
                      </div>
                      <FormControl>
                        <Switch checked={field.value} onCheckedChange={field.onChange} />
                      </FormControl>
                    </FormItem>
                  )}
                />
              </CardContent>
            </Card>

            <div className="flex items-center justify-end">
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
