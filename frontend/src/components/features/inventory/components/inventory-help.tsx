"use client";

import { BookOpen, Filter, Layers } from "lucide-react";

import { Badge } from "@/components/ui/badge";

function CodeExample({ title, code }: { title: string; code: string }) {
  return (
    <div className="space-y-2">
      <h5 className="text-sm font-medium text-muted-foreground">{title}</h5>
      <pre className="overflow-x-auto rounded-lg bg-muted p-4 text-xs text-foreground">
        <code>{code}</code>
      </pre>
    </div>
  );
}

export function InventoryHelpContent() {
  return (
    <div className="space-y-8">
      <div className="overflow-hidden rounded-lg border-0 bg-card shadow-lg">
        <div className="border-b bg-muted px-4 py-2">
          <div className="flex items-center gap-2 text-lg font-semibold">
            <BookOpen className="h-5 w-5" />
            <span>Inventory Builder Overview</span>
          </div>
        </div>
        <div className="space-y-4 p-6">
          <p className="text-muted-foreground">
            The Inventory Builder uses logical operations (AND / OR / NOT) to create
            dynamic device inventories from Nautobot. Build nested groups, preview matching
            devices, and save filters for reuse in workflows.
          </p>
          <div className="mt-4 grid gap-4 md:grid-cols-3">
            <div className="rounded-lg border bg-muted/50 p-4">
              <h4 className="mb-2 font-semibold">Logical Conditions</h4>
              <p className="text-sm text-muted-foreground">
                Filter by role, location, status, tags, device type, manufacturer, platform,
                IP prefix, primary prefix, or custom fields.
              </p>
            </div>
            <div className="rounded-lg border bg-muted/50 p-4">
              <h4 className="mb-2 font-semibold">Nested Groups</h4>
              <p className="text-sm text-muted-foreground">
                Organize conditions into groups with their own AND/OR logic. Click a group
                to set it as the active target for new conditions.
              </p>
            </div>
            <div className="rounded-lg border bg-muted/50 p-4">
              <h4 className="mb-2 font-semibold">Save &amp; Load</h4>
              <p className="text-sm text-muted-foreground">
                Persist filters with names, descriptions, scope, and folder groups.
                Load saved inventories back into the builder at any time.
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border-0 bg-card shadow-lg">
        <div className="border-b bg-muted px-4 py-2">
          <div className="flex items-center gap-2 text-lg font-semibold">
            <Filter className="h-5 w-5" />
            <span>Building Conditions</span>
          </div>
        </div>
        <div className="space-y-4 p-6">
          <ol className="list-decimal space-y-2 pl-5 text-sm text-muted-foreground">
            <li>Select a field, operator, and value in the condition row.</li>
            <li>Choose a connector (AND/OR) and optionally Negate (NOT) for groups.</li>
            <li>Click <Badge variant="secondary">+</Badge> to add a condition or <Badge variant="secondary">+ Group</Badge> for nested logic.</li>
            <li>Click a group in the expression tree to add conditions inside it.</li>
            <li>Use <strong>Preview Results</strong> to see matching devices from Nautobot.</li>
          </ol>
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border-0 bg-card shadow-lg">
        <div className="border-b bg-muted px-4 py-2">
          <div className="flex items-center gap-2 text-lg font-semibold">
            <Layers className="h-5 w-5" />
            <span>Examples</span>
          </div>
        </div>
        <div className="space-y-6 p-6">
          <CodeExample
            title="All active Cisco devices in lab locations"
            code={`Root (OR)
  Device Name contains "lab"
  Device Name contains "switch"
  GROUP (AND)
    Manufacturer equals "Cisco"`}
          />
          <CodeExample
            title="Devices excluding a status"
            code={`Root (AND)
  Status not_equals "offline"
  GROUP (NOT)
    Tag equals "decommissioned"`}
          />
        </div>
      </div>
    </div>
  );
}
