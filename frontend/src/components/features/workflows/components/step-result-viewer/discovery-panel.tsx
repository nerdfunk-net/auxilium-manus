"use client";

import { ChevronDown, ChevronRight, Compass } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import type {
  DiscoveryEdgeEntry,
  DiscoveryPayload,
  DiscoverySeenEntry,
  DiscoveryVisitedEntry,
} from "./types";

/** discover-network writes its step-level record to metadata["<node id>.discovery"]. */
export const DISCOVERY_METADATA_SUFFIX = ".discovery";

export interface DiscoveryEntry {
  nodeId: string;
  payload: DiscoveryPayload;
}

const EMPTY_LIST: never[] = [];

const REASON_LABELS: Record<string, string> = {
  follow_disabled: "Following neighbours is switched off",
  no_management_ip: "No management address reported",
  not_infrastructure: "Not a router or switch",
  out_of_scope: "Outside the permitted prefixes",
  unsupported_platform: "Platform not supported",
  limit_reached: "Limit reached (max devices or depth)",
  unreachable: "Could not be reached",
  login_failed: "Login was rejected",
};

const FAILURE_REASONS = new Set(["unreachable", "login_failed"]);

/** A readable text for a reason code; an unknown code is shown as it is. */
export function reasonLabel(reason: string): string {
  return REASON_LABELS[reason] ?? reason;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isDiscoveryRecord(value: unknown): value is Record<string, unknown> {
  return isRecord(value) && Array.isArray(value.visited) && Array.isArray(value.seen_not_visited);
}

export function isDiscoveryMetadataKey(key: string, value: unknown): boolean {
  return key.endsWith(DISCOVERY_METADATA_SUFFIX) && isDiscoveryRecord(value);
}

function listOf<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : (EMPTY_LIST as T[]);
}

export function extractDiscovery(metadata: Record<string, unknown>): DiscoveryEntry[] {
  return Object.entries(metadata)
    .filter(([key, value]) => isDiscoveryMetadataKey(key, value))
    .map(([key, value]) => {
      const record = value as Record<string, unknown>;
      return {
        nodeId: key.slice(0, -DISCOVERY_METADATA_SUFFIX.length),
        payload: {
          visited: listOf<DiscoveryVisitedEntry>(record.visited),
          seen_not_visited: listOf<DiscoverySeenEntry>(record.seen_not_visited),
          edges: listOf<DiscoveryEdgeEntry>(record.edges),
          limits_hit: listOf<string>(record.limits_hit),
          truncated: record.truncated === true,
        },
      };
    });
}

function plural(count: number, one: string, many: string = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

function Mono({ children }: { children: string }) {
  return <span className="font-mono text-[11px]">{children}</span>;
}

function VisitedTable({ rows }: { rows: DiscoveryVisitedEntry[] }) {
  return (
    <Table aria-label="Visited devices">
      <TableHeader>
        <TableRow>
          <TableHead className="h-7 text-[11px]">Device</TableHead>
          <TableHead className="h-7 text-[11px]">Address</TableHead>
          <TableHead className="h-7 text-[11px]">Hops</TableHead>
          <TableHead className="h-7 text-[11px]">Found through</TableHead>
          <TableHead className="h-7 text-[11px]">CDP</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={`${row.ip}-${row.name}`} className="text-xs">
            <TableCell className="py-1.5">
              <span className="font-medium">{row.name}</span>{" "}
              {row.seed ? (
                <Badge variant="secondary" className="text-[10px]">
                  seed
                </Badge>
              ) : null}
            </TableCell>
            <TableCell className="py-1.5">
              <Mono>{row.ip}</Mono>
            </TableCell>
            <TableCell className="py-1.5">{row.depth}</TableCell>
            <TableCell className="py-1.5">{row.discovered_from ?? "—"}</TableCell>
            <TableCell className="py-1.5">
              <Badge variant={row.cdp_status === "ok" ? "outline" : "destructive"} className="text-[10px]">
                {row.cdp_status}
              </Badge>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function SeenTable({ rows }: { rows: DiscoverySeenEntry[] }) {
  return (
    <Table aria-label="Seen, not visited">
      <TableHeader>
        <TableRow>
          <TableHead className="h-7 text-[11px]">Device</TableHead>
          <TableHead className="h-7 text-[11px]">Address</TableHead>
          <TableHead className="h-7 text-[11px]">Platform</TableHead>
          <TableHead className="h-7 text-[11px]">Why not visited</TableHead>
          <TableHead className="h-7 text-[11px]">Seen from</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, index) => (
          <TableRow key={`${row.ip ?? "none"}-${row.name}-${index}`} className="text-xs">
            <TableCell className="py-1.5 font-medium">{row.name}</TableCell>
            <TableCell className="py-1.5">
              {row.ip ? <Mono>{row.ip}</Mono> : <span className="text-muted-foreground">no address</span>}
            </TableCell>
            <TableCell className="py-1.5 text-muted-foreground">{row.platform || "—"}</TableCell>
            <TableCell className="py-1.5">
              <Badge
                variant={FAILURE_REASONS.has(row.reason) ? "destructive" : "secondary"}
                className="text-[10px]"
                title={row.reason}
              >
                {reasonLabel(row.reason)}
              </Badge>
            </TableCell>
            <TableCell className="py-1.5">{row.seen_from || "—"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function EdgesTable({ rows }: { rows: DiscoveryEdgeEntry[] }) {
  return (
    <Table aria-label="Links">
      <TableHeader>
        <TableRow>
          <TableHead className="h-7 text-[11px]">From</TableHead>
          <TableHead className="h-7 text-[11px]">Port</TableHead>
          <TableHead className="h-7 text-[11px]">To</TableHead>
          <TableHead className="h-7 text-[11px]">Port</TableHead>
          <TableHead className="h-7 text-[11px]">Address</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, index) => (
          <TableRow key={`${row.from}-${row.local_port}-${row.to}-${index}`} className="text-xs">
            <TableCell className="py-1.5">{row.from}</TableCell>
            <TableCell className="py-1.5">
              <Mono>{row.local_port || "—"}</Mono>
            </TableCell>
            <TableCell className="py-1.5">{row.to}</TableCell>
            <TableCell className="py-1.5">
              <Mono>{row.remote_port || "—"}</Mono>
            </TableCell>
            <TableCell className="py-1.5">{row.to_ip ? <Mono>{row.to_ip}</Mono> : "—"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function Notices({ payload }: { payload: DiscoveryPayload }) {
  if (payload.limits_hit.length === 0 && !payload.truncated) return null;
  return (
    <div role="alert" className="space-y-0.5 rounded border border-destructive/40 bg-destructive/5 p-2 text-[11px]">
      {payload.limits_hit.length > 0 ? (
        <p>
          The walk stopped at a limit (<span className="font-mono">{payload.limits_hit.join(", ")}</span>
          ); more devices may exist.
        </p>
      ) : null}
      {payload.truncated ? (
        <p>The lists below were cut to keep the stored result small (truncated).</p>
      ) : null}
    </div>
  );
}

function DiscoveryEntryView({ entry }: { entry: DiscoveryEntry }) {
  const [linksOpen, setLinksOpen] = useState(false);
  const { payload } = entry;

  return (
    <div className="space-y-3 rounded-lg border bg-card p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Compass className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Network discovery
        </p>
        <span className="text-[11px] text-muted-foreground">
          {payload.visited.length} visited · {payload.seen_not_visited.length} seen, not visited ·{" "}
          {plural(payload.edges.length, "link")}
        </span>
      </div>

      <Notices payload={payload} />

      <div className="space-y-1">
        <p className="text-xs font-medium">Visited devices</p>
        {payload.visited.length > 0 ? (
          <VisitedTable rows={payload.visited} />
        ) : (
          <p className="text-xs text-muted-foreground">No device was logged into.</p>
        )}
      </div>

      <div className="space-y-1">
        <p className="text-xs font-medium">Seen, not visited</p>
        {payload.seen_not_visited.length > 0 ? (
          <SeenTable rows={payload.seen_not_visited} />
        ) : (
          <p className="text-xs text-muted-foreground">
            Every neighbour that was found was visited.
          </p>
        )}
      </div>

      {payload.edges.length > 0 ? (
        <div className="space-y-1">
          <button
            type="button"
            className="flex items-center gap-1.5 text-left text-xs font-medium hover:text-foreground"
            onClick={() => setLinksOpen((value) => !value)}
            aria-expanded={linksOpen}
          >
            {linksOpen ? (
              <ChevronDown className="size-3.5 shrink-0" aria-hidden />
            ) : (
              <ChevronRight className="size-3.5 shrink-0" aria-hidden />
            )}
            <span>Links ({payload.edges.length})</span>
          </button>
          {linksOpen ? <EdgesTable rows={payload.edges} /> : null}
        </div>
      ) : null}
    </div>
  );
}

export function DiscoveryPanel({ entries }: { entries: DiscoveryEntry[] }) {
  if (entries.length === 0) return null;
  return (
    <div className="space-y-3">
      {entries.map((entry) => (
        <DiscoveryEntryView key={entry.nodeId} entry={entry} />
      ))}
    </div>
  );
}
