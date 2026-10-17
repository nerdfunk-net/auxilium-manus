import type { WorkflowOutcomeField } from "@/components/features/workflows/types/workflow-canvas";

export interface RouteRule {
  outcome: string;
  values: string[];
}

/**
 * Worked examples shown in the Routes help. The language itself lives in
 * `backend/services/workflow_context/attribute_expression/`; `{:fn()}` (empty key) tests the
 * step's attribute_path, `{path:fn()}` tests another attribute.
 */
export const EXPRESSION_EXAMPLES = [
  { value: "cisco_ios, ios", meaning: "plain values: the attribute_path equals any of them" },
  { value: "{:exists()}", meaning: "attribute_path has a non-empty value" },
  { value: "{:isEmpty()}", meaning: "value is an empty string, list or object" },
  { value: "{:isAbsent()}", meaning: "attribute_path does not exist at all" },
  { value: "{custom.value:gt(10)}", meaning: "another attribute, as a number, is greater than 10" },
  { value: "{parsed.k.serial:count():gt(2)}", meaning: "a list holds more than 2 items" },
  { value: "{device.name:equalsIgnoreCase('lab')}", meaning: "text equals lab, ignoring case" },
  { value: "{device.name:startsWith('sw'):or({device.name:startsWith('lab')})}", meaning: "either condition holds" },
  { value: "{:matches('sw\\d+')}", meaning: "the whole value matches a regular expression" },
  { value: "{:matches('sw\\d+'):and({custom.role:equals('edge')})}", meaning: "regex and another attribute" },
] as const;

/**
 * Split a comma-separated values field, keeping commas inside `{...}` expressions intact.
 * Quotes only matter inside braces. Mirror of `split_values` in the backend parser.
 */
export function splitRouteValues(raw: string): string[] {
  const values: string[] = [];
  let current = "";
  let depth = 0;
  let quote = "";
  let escaped = false;
  for (const char of raw) {
    if (quote) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === quote) quote = "";
    } else if (depth > 0 && (char === "'" || char === '"')) {
      quote = char;
    } else if (char === "{") {
      depth += 1;
    } else if (char === "}") {
      depth = Math.max(0, depth - 1);
    } else if (char === "," && depth === 0) {
      values.push(current.trim());
      current = "";
      continue;
    }
    current += char;
  }
  values.push(current.trim());
  return values.filter(Boolean);
}

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
    return splitRouteValues(raw);
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
  // `current.routes` drops a row whose outcome is still blank; keep it, so an edit on another
  // tab does not delete a route the user is in the middle of naming.
  return {
    ...current,
    routes: editableRoutes(config),
    ...patch,
  };
}

/** Outcome names the engine itself gives a meaning; a route may not use them. */
export const RESERVED_ROUTE_NAMES: readonly string[] = ["success", "failure"];

export function isReservedRouteName(name: string): boolean {
  return RESERVED_ROUTE_NAMES.includes(name.trim());
}

export function deriveRouteOutcomes(
  config: Record<string, unknown>,
): WorkflowOutcomeField[] {
  const parsed = parseRouteOnAttributeConfig(config);
  const names = parsed.routes.map((route) => route.outcome).filter(Boolean);
  if (parsed.default_outcome && !names.includes(parsed.default_outcome)) {
    names.push(parsed.default_outcome);
  }
  // A device whose value matches no route (and there is no default) leaves through "failure".
  return [...names.filter((name) => !isReservedRouteName(name)), "failure"].map((name) => ({
    name,
  }));
}

/**
 * Routes as the Routes tab edits them. Unlike `parseRouteOnAttributeConfig` this keeps a row
 * whose outcome is still empty, so clearing the name field does not make the row vanish.
 */
export function editableRoutes(config: Record<string, unknown>): RouteRule[] {
  const rows = Array.isArray(config.routes)
    ? config.routes
        .filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
        .map((route) => ({
          outcome: typeof route.outcome === "string" ? route.outcome : "",
          values: parseValues(route.values),
        }))
    : [];
  return rows.length > 0 ? rows : DEFAULT_ROUTE_ON_ATTRIBUTE_CONFIG.routes;
}

export function setRouteOutcome(routes: RouteRule[], index: number, outcome: string): RouteRule[] {
  return routes.map((route, i) => (i === index ? { ...route, outcome } : route));
}

export function setRouteValues(routes: RouteRule[], index: number, values: string[]): RouteRule[] {
  return routes.map((route, i) => (i === index ? { ...route, values } : route));
}

export function addRoute(routes: RouteRule[]): RouteRule[] {
  const taken = new Set(routes.map((route) => route.outcome.trim()));
  let number = routes.length + 1;
  while (taken.has(`route-${number}`)) number += 1;
  return [...routes, { outcome: `route-${number}`, values: [] }];
}

/** The last route cannot be removed: the step needs at least one. */
export function removeRoute(routes: RouteRule[], index: number): RouteRule[] {
  return routes.length <= 1 ? routes : routes.filter((_, i) => i !== index);
}

/** Why a route's outcome name is not usable, or null when it is fine. */
export function routeOutcomeProblem(routes: RouteRule[], index: number): string | null {
  const name = routes[index]?.outcome.trim() ?? "";
  if (!name) return "needs a name";
  if (isReservedRouteName(name)) return `"${name}" is reserved`;
  const duplicate = routes.some((route, i) => i !== index && route.outcome.trim() === name);
  return duplicate ? `"${name}" is used twice` : null;
}

export function sameValues(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((value, i) => value === b[i]);
}
