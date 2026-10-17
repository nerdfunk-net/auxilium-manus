"use client";

import { CircleHelp, Minus, Plus } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import { ExpressionHelpDialog } from "./expression-help";
import {
  addRoute,
  buildRouteOnAttributeConfig,
  editableRoutes,
  removeRoute,
  routeOutcomeProblem,
  sameValues,
  setRouteOutcome,
  setRouteValues,
  splitRouteValues,
} from "./route-config";

interface ExpressionInputProps {
  values: string[];
  onCommit: (values: string[]) => void;
  ariaLabel: string;
}

/**
 * Keeps what the user typed (including a trailing comma) as a draft, and commits the parsed
 * list on every keystroke. The draft is only replaced when the stored values change from
 * outside, e.g. after a row above was removed.
 */
function ExpressionInput({ values, onCommit, ariaLabel }: ExpressionInputProps) {
  const [draft, setDraft] = useState(() => values.join(", "));
  const [seen, setSeen] = useState(values);

  if (!sameValues(seen, values)) {
    setSeen(values);
    if (!sameValues(splitRouteValues(draft), values)) {
      setDraft(values.join(", "));
    }
  }

  return (
    <Input
      value={draft}
      onChange={(event) => {
        setDraft(event.target.value);
        onCommit(splitRouteValues(event.target.value));
      }}
      placeholder="cisco_ios, ios   or   {custom.value:gt(10)}"
      aria-label={ariaLabel}
      spellCheck={false}
      className="h-7 font-mono text-xs"
    />
  );
}

export function RoutesTabPanel({ config, onChange }: PluginConfigPanelProps) {
  const [helpOpen, setHelpOpen] = useState(false);
  const routes = useMemo(() => editableRoutes(config), [config]);

  const commit = useCallback(
    (nextRoutes: ReturnType<typeof editableRoutes>) =>
      onChange(buildRouteOnAttributeConfig(config, { routes: nextRoutes })),
    [config, onChange],
  );

  const problems = routes
    .map((_, index) => routeOutcomeProblem(routes, index))
    .map((problem, index) => (problem ? `Route ${index + 1} ${problem}.` : null))
    .filter((problem): problem is string => problem !== null);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <span className="text-xs font-medium">Routes</span>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-5 rounded-full text-muted-foreground"
            onClick={() => setHelpOpen(true)}
            title="Help: writing expressions"
            aria-label="Help: writing expressions"
          >
            <CircleHelp className="size-3.5" />
          </Button>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-7 gap-1 px-2 text-xs"
          onClick={() => commit(addRoute(routes))}
        >
          <Plus className="size-3.5" />
          Add route
        </Button>
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="h-8 w-[32%] px-2 text-[11px]">Outcome</TableHead>
              <TableHead className="h-8 px-2 text-[11px]">Expression</TableHead>
              <TableHead className="h-8 w-9 px-1">
                <span className="sr-only">Remove</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {routes.map((route, index) => (
              <TableRow key={`route-${index}`}>
                <TableCell className="px-2 py-1 align-top">
                  <Input
                    value={route.outcome}
                    onChange={(event) =>
                      commit(setRouteOutcome(routes, index, event.target.value))
                    }
                    placeholder="ios"
                    aria-label={`Outcome of route ${index + 1}`}
                    aria-invalid={routeOutcomeProblem(routes, index) !== null}
                    spellCheck={false}
                    className="h-7 font-mono text-xs"
                  />
                </TableCell>
                <TableCell className="px-2 py-1 align-top">
                  <ExpressionInput
                    values={route.values}
                    onCommit={(values) => commit(setRouteValues(routes, index, values))}
                    ariaLabel={`Expression of route ${index + 1}`}
                  />
                </TableCell>
                <TableCell className="px-1 py-1 align-top">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-7"
                    onClick={() => commit(removeRoute(routes, index))}
                    disabled={routes.length <= 1}
                    title="Remove route"
                    aria-label={`Remove route ${index + 1}`}
                  >
                    <Minus className="size-3.5" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {problems.length > 0 ? (
        <ul className="space-y-0.5 text-[11px] text-destructive">
          {problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      ) : null}

      <p className="text-[11px] leading-4 text-muted-foreground">
        Routes are checked top to bottom; the first match wins. Separate several plain values
        with commas, or use an expression such as{" "}
        <span className="font-mono">{"{custom.value:gt(10)}"}</span>. Click (?) for the full
        list.
      </p>

      <ExpressionHelpDialog open={helpOpen} onOpenChange={setHelpOpen} />
    </div>
  );
}
