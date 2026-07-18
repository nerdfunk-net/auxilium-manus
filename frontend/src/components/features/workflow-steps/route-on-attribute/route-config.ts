import type { WorkflowOutcomeField } from "@/components/features/workflows/types/workflow-canvas";

export interface RouteRule {
  outcome: string;
  values: string[];
}

/**
 * Special match values that route on the resolved attribute's existence
 * state instead of a literal string. Must stay in sync with
 * `backend/workflow_steps/route_on_attribute/executor.py`.
 */
export const SPECIAL_ROUTE_VALUES = [
  { value: "{absent}", label: "absent", hint: "attribute_path does not exist" },
  { value: "{null}", label: "null", hint: "value is null" },
  { value: "{empty}", label: "empty", hint: "value is an empty string/list/object" },
  { value: "{exists}", label: "exists", hint: "value is present and non-empty" },
] as const;

export interface RouteOnAttributeConfig {
  attribute_path: string;
  routes: RouteRule[];
  default_outcome: string;
  case_sensitive: boolean;
}

export const DEFAULT_ROUTE_ON_ATTRIBUTE_CONFIG: RouteOnAttributeConfig = {
  attribute_path: "device.network_driver",
  default_outcome: "unmatched",
  case_sensitive: false,
  routes: [
    { outcome: "ios", values: ["cisco_ios", "ios"] },
    { outcome: "nxos", values: ["cisco_nxos", "nxos"] },
  ],
};

function parseValues(raw: unknown): string[] {
  if (Array.isArray(raw)) {
    return raw.map((item) => String(item).trim()).filter(Boolean);
  }
  if (typeof raw === "string") {
    return raw
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [];
}

export function parseRouteOnAttributeConfig(
  config: Record<string, unknown>,
): RouteOnAttributeConfig {
  const routes = Array.isArray(config.routes)
    ? config.routes
        .map((item) => {
          if (!item || typeof item !== "object") {
            return null;
          }
          const route = item as Record<string, unknown>;
          const outcome = typeof route.outcome === "string" ? route.outcome.trim() : "";
          if (!outcome) {
            return null;
          }
          return {
            outcome,
            values: parseValues(route.values),
          };
        })
        .filter((route): route is RouteRule => route !== null)
    : DEFAULT_ROUTE_ON_ATTRIBUTE_CONFIG.routes;

  return {
    attribute_path:
      typeof config.attribute_path === "string" && config.attribute_path.trim()
        ? config.attribute_path.trim()
        : DEFAULT_ROUTE_ON_ATTRIBUTE_CONFIG.attribute_path,
    routes: routes.length > 0 ? routes : DEFAULT_ROUTE_ON_ATTRIBUTE_CONFIG.routes,
    default_outcome:
      typeof config.default_outcome === "string"
        ? config.default_outcome.trim()
        : DEFAULT_ROUTE_ON_ATTRIBUTE_CONFIG.default_outcome,
    case_sensitive: config.case_sensitive === true,
  };
}

export function buildRouteOnAttributeConfig(
  config: Record<string, unknown>,
  patch: Partial<RouteOnAttributeConfig> = {},
): Record<string, unknown> {
  const current = parseRouteOnAttributeConfig(config);
  return {
    ...current,
    ...patch,
  };
}

export function deriveRouteOutcomes(
  config: Record<string, unknown>,
): WorkflowOutcomeField[] {
  const parsed = parseRouteOnAttributeConfig(config);
  const names = parsed.routes.map((route) => route.outcome).filter(Boolean);
  if (parsed.default_outcome && !names.includes(parsed.default_outcome)) {
    names.push(parsed.default_outcome);
  }
  return names.map((name) => ({ name }));
}
