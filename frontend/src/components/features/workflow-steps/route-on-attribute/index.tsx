"use client";

import { Minus, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import {
  buildRouteOnAttributeConfig,
  DEFAULT_ROUTE_ON_ATTRIBUTE_CONFIG,
  parseRouteOnAttributeConfig,
  SPECIAL_ROUTE_VALUES,
  type RouteRule,
} from "./route-config";

function formatValues(values: string[]): string {
  return values.join(", ");
}

function RouteOnAttributeConfigPanel({
  config,
  onChange,
  nodeId,
}: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const parsed = useMemo(() => parseRouteOnAttributeConfig(config), [config]);

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!Array.isArray(config.routes) || config.routes.length === 0) {
      onChange(buildRouteOnAttributeConfig(config, DEFAULT_ROUTE_ON_ATTRIBUTE_CONFIG));
    }
  }, [nodeId, config, onChange]);

  const handleAttributePathChange = useCallback(
    (value: string) => {
      onChange(buildRouteOnAttributeConfig(config, { attribute_path: value }));
    },
    [config, onChange],
  );

  const handleDefaultOutcomeChange = useCallback(
    (value: string) => {
      onChange(buildRouteOnAttributeConfig(config, { default_outcome: value }));
    },
    [config, onChange],
  );

  const handleCaseSensitiveChange = useCallback(
    (checked: boolean) => {
      onChange(buildRouteOnAttributeConfig(config, { case_sensitive: checked }));
    },
    [config, onChange],
  );

  const handleRouteOutcomeChange = useCallback(
    (index: number, value: string) => {
      const nextRoutes = parsed.routes.map((route, routeIndex) =>
        routeIndex === index ? { ...route, outcome: value } : route,
      );
      onChange(buildRouteOnAttributeConfig(config, { routes: nextRoutes }));
    },
    [config, onChange, parsed.routes],
  );

  const handleRouteValuesChange = useCallback(
    (index: number, value: string) => {
      const nextRoutes = parsed.routes.map((route, routeIndex) =>
        routeIndex === index
          ? {
              ...route,
              values: value
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean),
            }
          : route,
      );
      onChange(buildRouteOnAttributeConfig(config, { routes: nextRoutes }));
    },
    [config, onChange, parsed.routes],
  );

  const handleInsertSpecialValue = useCallback(
    (index: number, token: string) => {
      const nextRoutes = parsed.routes.map((route, routeIndex) => {
        if (routeIndex !== index || route.values.includes(token)) {
          return route;
        }
        return { ...route, values: [...route.values, token] };
      });
      onChange(buildRouteOnAttributeConfig(config, { routes: nextRoutes }));
    },
    [config, onChange, parsed.routes],
  );

  const handleAddRoute = useCallback(() => {
    const nextRoutes: RouteRule[] = [
      ...parsed.routes,
      { outcome: `route-${parsed.routes.length + 1}`, values: [] },
    ];
    onChange(buildRouteOnAttributeConfig(config, { routes: nextRoutes }));
  }, [config, onChange, parsed.routes]);

  const handleRemoveRoute = useCallback(
    (index: number) => {
      if (parsed.routes.length <= 1) {
        return;
      }
      const nextRoutes = parsed.routes.filter((_, routeIndex) => routeIndex !== index);
      onChange(buildRouteOnAttributeConfig(config, { routes: nextRoutes }));
    },
    [config, onChange, parsed.routes],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">attribute_path</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={parsed.attribute_path}
          onChange={(event) => handleAttributePathChange(event.target.value)}
          placeholder="device.network_driver"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Use <span className="font-mono">device.network_driver</span> for core device
          fields, <span className="font-mono">nautobot.role.name</span> for Nautobot
          attributes, or <span className="font-mono">custom.field</span> for user-defined
          attribute bags.
        </p>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">routes</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              object_list
            </Badge>
          </div>
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-7"
            onClick={handleAddRoute}
            title="Add route"
          >
            <Plus className="size-3.5" />
          </Button>
        </div>

        <div className="space-y-3">
          {parsed.routes.map((route, index) => (
            <div key={`route-${index}`} className="space-y-2 rounded-lg border p-3">
              <div className="flex items-center gap-2">
                <div className="min-w-0 flex-1 space-y-1">
                  <Label className="text-[11px] text-muted-foreground">Outcome handle</Label>
                  <Input
                    value={route.outcome}
                    onChange={(event) =>
                      handleRouteOutcomeChange(index, event.target.value)
                    }
                    placeholder="ios"
                    className="h-8 font-mono text-xs"
                  />
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  className="mt-5 size-8 shrink-0"
                  onClick={() => handleRemoveRoute(index)}
                  disabled={parsed.routes.length <= 1}
                  title="Remove route"
                >
                  <Minus className="size-3.5" />
                </Button>
              </div>
              <div className="space-y-1">
                <Label className="text-[11px] text-muted-foreground">
                  Match values (comma-separated)
                </Label>
                <Input
                  value={formatValues(route.values)}
                  onChange={(event) => handleRouteValuesChange(index, event.target.value)}
                  placeholder="cisco_ios, ios"
                  className="h-8 font-mono text-xs"
                />
                <div className="flex flex-wrap items-center gap-1 pt-0.5">
                  {SPECIAL_ROUTE_VALUES.map((special) => (
                    <Button
                      key={special.value}
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-5 rounded px-1.5 font-mono text-[10px]"
                      title={special.hint}
                      disabled={route.values.includes(special.value)}
                      onClick={() => handleInsertSpecialValue(index, special.value)}
                    >
                      {special.value}
                    </Button>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
        <p className="text-[11px] leading-4 text-muted-foreground">
          Routes are evaluated in order. The first matching value sends the device down that
          outcome handle. Besides literal values, the special tokens{" "}
          <span className="font-mono">{"{absent}"}</span>,{" "}
          <span className="font-mono">{"{null}"}</span>,{" "}
          <span className="font-mono">{"{empty}"}</span>, and{" "}
          <span className="font-mono">{"{exists}"}</span> match on the attribute&apos;s
          existence state instead of its literal text — use{" "}
          <span className="font-mono">{"{exists}"}</span> for "has a non-empty value" (for
          example, checking whether a TACACS+ key was found).
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">default_outcome</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={parsed.default_outcome}
          onChange={(event) => handleDefaultOutcomeChange(event.target.value)}
          placeholder="unmatched"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Devices with a missing or unmatched attribute value are sent to this outcome.
          Leave empty to fail the step instead.
        </p>
      </div>

      <div className="flex items-start gap-2">
        <input
          id={`case-sensitive-${nodeId}`}
          type="checkbox"
          checked={parsed.case_sensitive}
          onChange={(event) => handleCaseSensitiveChange(event.target.checked)}
          className="mt-0.5 size-4 rounded border"
        />
        <div className="space-y-0.5">
          <Label htmlFor={`case-sensitive-${nodeId}`} className="font-mono text-xs font-medium">
            case_sensitive
          </Label>
          <p className="text-[11px] text-muted-foreground">
            When disabled, route matching ignores letter case.
          </p>
        </div>
      </div>
    </div>
  );
}

export const RouteOnAttributePlugin = {
  ConfigPanel: RouteOnAttributeConfigPanel,
};
