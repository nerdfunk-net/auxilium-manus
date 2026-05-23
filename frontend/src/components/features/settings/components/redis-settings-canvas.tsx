"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { AlertCircle, CheckCircle2, Loader2, RefreshCw, Trash2 } from "lucide-react";
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
import { Switch } from "@/components/ui/switch";
import { useRedisSettingsMutations } from "@/hooks/queries/use-redis-settings-mutations";
import {
  useRedisSettingsQuery,
  useRedisStatsQuery,
} from "@/hooks/queries/use-redis-settings-query";

const formSchema = z.object({
  enabled: z.boolean(),
  device_ttl_seconds: z.number().int().min(60).max(86400),
});

type FormValues = z.infer<typeof formSchema>;

const EMPTY_DEFAULTS: FormValues = {
  enabled: true,
  device_ttl_seconds: 1800,
};

function StatItem({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium tabular-nums">{value}</span>
    </div>
  );
}

export function RedisSettingsCanvas() {
  const { data: settingsData, isLoading: settingsLoading } = useRedisSettingsQuery();
  const { data: statsData, isLoading: statsLoading, refetch: refetchStats } = useRedisStatsQuery();
  const { saveSettings, clearCache } = useRedisSettingsMutations();
  const [refreshing, setRefreshing] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);

  const defaultValues = useMemo<FormValues>(
    () =>
      settingsData
        ? {
            enabled: settingsData.enabled,
            device_ttl_seconds: settingsData.device_ttl_seconds,
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

  const handleRefreshStats = async () => {
    setRefreshing(true);
    await refetchStats();
    setRefreshing(false);
  };

  const connected = settingsData?.redis_connected ?? false;
  const overview = statsData?.overview as Record<string, number> | undefined;
  const performance = statsData?.performance as Record<string, number> | undefined;

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto bg-slate-50 p-8">
      <div className="mx-auto w-full max-w-2xl space-y-6">
        {/* Status card */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">Redis Status</CardTitle>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={refreshing || statsLoading}
                onClick={handleRefreshStats}
              >
                <RefreshCw className={`size-4 ${refreshing ? "animate-spin" : ""}`} />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-3">
              {connected ? (
                <CheckCircle2 className="size-5 shrink-0 text-green-500" />
              ) : (
                <AlertCircle className="size-5 shrink-0 text-destructive" />
              )}
              <Badge
                variant={connected ? "default" : "destructive"}
                className={connected ? "bg-green-500 hover:bg-green-500" : ""}
              >
                {connected ? "Connected" : "Disconnected"}
              </Badge>
            </div>

            {connected && overview && (
              <div className="space-y-2 rounded-lg border bg-muted/30 p-3">
                <StatItem label="Cached items" value={overview.total_items ?? 0} />
                <StatItem
                  label="Hit rate"
                  value={`${performance?.hit_rate_percent ?? 0}%`}
                />
                <StatItem
                  label="Cache hits"
                  value={performance?.cache_hits ?? 0}
                />
                <StatItem
                  label="Cache misses"
                  value={performance?.cache_misses ?? 0}
                />
                <StatItem
                  label="Uptime"
                  value={`${Math.floor((overview.uptime_seconds ?? 0) / 60)} min`}
                />
              </div>
            )}

            {!connected && !settingsLoading && (
              <p className="text-sm text-muted-foreground">
                Redis is not reachable. Check the connection URL and ensure Redis is running.
              </p>
            )}
          </CardContent>
        </Card>

        {/* Configuration form */}
        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSave)} className="space-y-6">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Configuration</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField
                  control={form.control}
                  name="enabled"
                  render={({ field }) => (
                    <FormItem className="flex items-center justify-between rounded-lg border p-3">
                      <div>
                        <FormLabel>Enable device caching</FormLabel>
                        <FormDescription>
                          Cache Nautobot device detail responses in Redis.
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
                  name="device_ttl_seconds"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Device cache TTL (seconds)</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          min={60}
                          max={86400}
                          {...field}
                          onChange={(e) => field.onChange(e.target.valueAsNumber)}
                        />
                      </FormControl>
                      <FormDescription>
                        How long individual device details are cached. Min 60 s, max 86400 s (24 h).
                        Default: 1800 s (30 min).
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </CardContent>
            </Card>

            <div className="flex justify-end">
              <Button type="submit" disabled={saveSettings.isPending}>
                {saveSettings.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
                Save Changes
              </Button>
            </div>
          </form>
        </Form>

        {/* Cache Management card */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Cache Management</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              <div>
                <p className="text-sm font-medium">Clear all cached data</p>
                <p className="text-sm text-muted-foreground">
                  Removes all entries from Redis immediately. The cache will be repopulated
                  on the next request.
                </p>
              </div>
              {confirmClear ? (
                <div className="flex items-center gap-2">
                  <p className="text-sm text-destructive">Are you sure?</p>
                  <Button
                    type="button"
                    variant="destructive"
                    size="sm"
                    disabled={clearCache.isPending}
                    onClick={() => {
                      clearCache.mutate();
                      setConfirmClear(false);
                    }}
                  >
                    {clearCache.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
                    Yes, clear cache
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setConfirmClear(false)}
                  >
                    Cancel
                  </Button>
                </div>
              ) : (
                <Button
                  type="button"
                  variant="destructive"
                  size="sm"
                  disabled={!connected || clearCache.isPending}
                  onClick={() => setConfirmClear(true)}
                >
                  <Trash2 className="mr-2 size-4" />
                  Clear Cache
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
