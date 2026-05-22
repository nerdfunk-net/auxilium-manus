"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { AlertCircle, CheckCircle2, ExternalLink, Loader2, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
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
import { Switch } from "@/components/ui/switch";
import {
  type HatchetStatusData,
  useHatchetSettingsMutations,
} from "@/hooks/queries/use-hatchet-settings-mutations";
import { useHatchetSettingsQuery } from "@/hooks/queries/use-hatchet-settings-query";

const formSchema = z.object({
  host_port: z.string().min(1, "Required"),
  token: z.string().optional(),
  dashboard_url: z.string().url("Must be a valid URL").or(z.literal("")),
  debug: z.boolean(),
  worker_name: z.string().min(1, "Required"),
  worker_slots: z.number().int().min(1).max(100),
});

type FormValues = z.infer<typeof formSchema>;

const EMPTY_DEFAULTS: FormValues = {
  host_port: "localhost:7077",
  token: "",
  dashboard_url: "http://localhost:8888",
  debug: false,
  worker_name: "auxilium-manus-worker",
  worker_slots: 10,
};

export function HatchetSettingsCanvas() {
  const { data, isLoading } = useHatchetSettingsQuery();
  const { saveSettings, testConnection } = useHatchetSettingsMutations();
  const [lastStatus, setLastStatus] = useState<HatchetStatusData | null>(null);

  const defaultValues = useMemo<FormValues>(
    () =>
      data
        ? {
            host_port: data.host_port,
            token: "",
            dashboard_url: data.dashboard_url,
            debug: data.debug,
            worker_name: data.worker_name,
            worker_slots: data.worker_slots,
          }
        : EMPTY_DEFAULTS,
    [data],
  );

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    values: defaultValues,
  });

  const handleTest = async () => {
    const result = await testConnection.mutateAsync();
    setLastStatus(result);
  };

  const handleSave = (values: FormValues) => {
    const payload: Parameters<typeof saveSettings.mutate>[0] = {
      host_port: values.host_port,
      dashboard_url: values.dashboard_url,
      debug: values.debug,
      worker_name: values.worker_name,
      worker_slots: values.worker_slots,
    };
    if (values.token && values.token.trim()) {
      payload.token = values.token.trim();
    }
    saveSettings.mutate(payload);
  };

  const watchedDashboardUrl = useWatch({ control: form.control, name: "dashboard_url" });
  const dashboardUrl = watchedDashboardUrl || data?.dashboard_url || "";

  const statusToShow = lastStatus;

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto bg-slate-50 p-8">
      <div className="mx-auto w-full max-w-2xl space-y-6">
        {/* Status card */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Connection Status</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {statusToShow ? (
              <div className="flex items-start gap-3">
                {statusToShow.reachable ? (
                  <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-green-500" />
                ) : (
                  <AlertCircle className="mt-0.5 size-5 shrink-0 text-destructive" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Badge
                      variant={statusToShow.reachable ? "default" : "destructive"}
                      className={statusToShow.reachable ? "bg-green-500 hover:bg-green-500" : ""}
                    >
                      {statusToShow.reachable ? "Connected" : "Unreachable"}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {new Date(statusToShow.checked_at).toLocaleTimeString()}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">{statusToShow.message}</p>
                  <div className="mt-2 flex gap-4 text-xs text-muted-foreground">
                    <span>Host: {statusToShow.host_port}</span>
                    <span>
                      Token:{" "}
                      {statusToShow.token_configured ? (
                        <span className="text-green-600">Configured</span>
                      ) : (
                        <span className="text-amber-600">Not set</span>
                      )}
                    </span>
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                {isLoading
                  ? "Loading configuration…"
                  : "Run a connection test to check the Hatchet engine status."}
              </p>
            )}

            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={testConnection.isPending}
                onClick={handleTest}
              >
                {testConnection.isPending ? (
                  <Loader2 className="mr-2 size-4 animate-spin" />
                ) : (
                  <RefreshCw className="mr-2 size-4" />
                )}
                Test Connection
              </Button>
              {dashboardUrl && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  asChild
                >
                  <a href={dashboardUrl} target="_blank" rel="noopener noreferrer">
                    <ExternalLink className="mr-2 size-4" />
                    Open Dashboard
                  </a>
                </Button>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Configuration form */}
        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSave)} className="space-y-6">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Connection</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField
                  control={form.control}
                  name="host_port"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>gRPC Host:Port</FormLabel>
                      <FormControl>
                        <Input placeholder="localhost:7077" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="token"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>API Token</FormLabel>
                      <FormControl>
                        <Input
                          type="password"
                          placeholder={
                            data?.token_configured
                              ? "Leave blank to keep current token"
                              : "Paste token from Hatchet dashboard"
                          }
                          {...field}
                        />
                      </FormControl>
                      <FormDescription>
                        {data?.token_configured ? (
                          <span className="text-green-600">Token is configured.</span>
                        ) : (
                          <span className="text-amber-600">No token set.</span>
                        )}{" "}
                        Generate one in the Hatchet dashboard under Settings → API Tokens.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="dashboard_url"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Dashboard URL</FormLabel>
                      <FormControl>
                        <Input placeholder="http://localhost:8888" {...field} />
                      </FormControl>
                      <FormDescription>Used for the &quot;Open Dashboard&quot; shortcut.</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="debug"
                  render={({ field }) => (
                    <FormItem className="flex items-center justify-between rounded-lg border p-3">
                      <div>
                        <FormLabel>Debug Mode</FormLabel>
                        <FormDescription>
                          Enables verbose SDK logging (HATCHET_CLIENT_DEBUG).
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

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Worker</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField
                  control={form.control}
                  name="worker_name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Worker Name</FormLabel>
                      <FormControl>
                        <Input placeholder="auxilium-manus-worker" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="worker_slots"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Max Concurrent Slots</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          min={1}
                          max={100}
                          {...field}
                          onChange={(e) => field.onChange(e.target.valueAsNumber)}
                        />
                      </FormControl>
                      <FormDescription>
                        Maximum number of workflow runs that can execute in parallel.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <p className="flex items-start gap-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">
                  <AlertCircle className="mt-0.5 size-4 shrink-0" />
                  Worker changes take effect after restarting the Hatchet worker process
                  (<code>python -m hatchet.worker</code>).
                </p>
              </CardContent>
            </Card>

            <div className="flex justify-end">
              <Button type="submit" disabled={saveSettings.isPending}>
                {saveSettings.isPending && (
                  <Loader2 className="mr-2 size-4 animate-spin" />
                )}
                Save Changes
              </Button>
            </div>
          </form>
        </Form>
      </div>
    </div>
  );
}
