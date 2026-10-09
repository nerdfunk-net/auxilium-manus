import { Badge } from "@/components/ui/badge";

import type { BatfishQueryResult } from "../types";

export function BatfishResultPanel({ result }: { result: BatfishQueryResult }) {
  return (
    <div className="min-w-0 space-y-2 rounded-md border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">{result.question}</Badge>
        {typeof result.reachable === "boolean" ? (
          <Badge variant={result.reachable ? "secondary" : "destructive"}>
            {result.reachable ? "Reachable" : "Not reachable"}
          </Badge>
        ) : null}
        {result.action ? (
          <Badge variant={result.action === "PERMIT" ? "secondary" : "destructive"}>
            {result.action}
          </Badge>
        ) : null}
        {result.facts_by_node ? (
          <span className="text-xs text-muted-foreground">
            {Object.keys(result.facts_by_node).length} node(s) · network {result.network} ·
            snapshot {result.snapshot}
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">
            {result.rows.length} row(s) · network {result.network} · snapshot {result.snapshot}
          </span>
        )}
      </div>
      {result.facts_by_node && Object.keys(result.facts_by_node).length > 1 ? (
        <p className="text-[11px] text-muted-foreground">
          More than one node matched — a real workflow run always sees exactly one node&apos;s
          shape per device. Narrow <strong>Nodes</strong> to preview that exact shape.
        </p>
      ) : null}
      <pre className="max-h-48 min-w-0 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-2 text-xs">
        {JSON.stringify(result.facts_by_node ?? result.rows, null, 2)}
      </pre>
    </div>
  );
}
