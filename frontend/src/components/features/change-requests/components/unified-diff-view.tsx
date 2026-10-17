export function diffLineClass(line: string): string {
  if (line.startsWith("+++") || line.startsWith("---")) return "text-muted-foreground";
  if (line.startsWith("@@")) return "text-step";
  if (line.startsWith("diff --git ") || line.startsWith("index ")) {
    return "text-muted-foreground font-semibold";
  }
  if (line.startsWith("+")) return "text-success-foreground";
  if (line.startsWith("-")) return "text-destructive";
  return "text-foreground";
}

interface UnifiedDiffViewProps {
  diff: string;
  truncated?: boolean;
}

export function UnifiedDiffView({ diff, truncated }: UnifiedDiffViewProps) {
  const lines = diff.length > 0 ? diff.split("\n") : [];

  if (lines.length === 0) {
    return (
      <p className="rounded-md border border-dashed px-3 py-6 text-center text-sm text-muted-foreground">
        No changes in this diff.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border bg-muted/30">
      <pre className="min-w-full py-2 font-mono text-xs leading-relaxed">
        {lines.map((line, index) => (
          <code
            key={index}
            className={`block whitespace-pre px-3 ${diffLineClass(line)}`}
          >
            {line || " "}
          </code>
        ))}
      </pre>
      {truncated ? (
        <p className="border-t px-3 py-2 text-[11px] text-warning-foreground">
          Diff truncated — review the full change on the <span className="font-mono">{"manus/cr-*"}</span> branch.
        </p>
      ) : null}
    </div>
  );
}
