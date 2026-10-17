"use client";

import { REPORT_VARIABLES } from "./constants";

/** Reference of the variables a report template can use, with a short example. */
export function ReportVariablesPanel() {
  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-3 text-sm">
      <div>
        <h2 className="text-sm font-semibold">Variables</h2>
        <p className="text-xs text-muted-foreground">
          The template is rendered once per generated report. Missing variables are errors.
        </p>
      </div>
      <ul className="space-y-2">
        {REPORT_VARIABLES.map((variable) => (
          <li key={variable.name}>
            <code className="rounded bg-muted px-1 py-0.5 text-xs">{variable.name}</code>
            <p className="text-xs text-muted-foreground">{variable.description}</p>
          </li>
        ))}
      </ul>
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Example
        </h3>
        <pre className="mt-1 overflow-x-auto rounded border bg-muted/30 p-2 text-xs">
          {`We found {{ sections["devices"].value }} devices.

{% for r in sections["per-site"].rows %}
- {{ r.location }}: {{ r.devices }}
{% endfor %}`}
        </pre>
      </div>
    </div>
  );
}
