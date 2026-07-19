"use client";

import type { ReactNode } from "react";

/** Inline monospace chip for config values, field names, and short examples. */
export function HelpCode({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
      {children}
    </code>
  );
}

/** Section heading + body stack used inside step Help tabs. */
export function HelpSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold">{title}</h3>
      <div className="space-y-2 text-xs leading-5 text-muted-foreground">
        {children}
      </div>
    </div>
  );
}

/** Preformatted example block (commands, sample values, hierarchies). */
export function HelpExample({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-md border bg-muted/40 p-2 font-mono text-[11px] leading-5">
      {children}
    </div>
  );
}

/** Amber callout for common mistakes or important constraints. */
export function HelpWarning({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800">
      <p className="font-medium">{title}</p>
      <div className="mt-1 space-y-1">{children}</div>
    </div>
  );
}

/** Placeholder when a step has not shipped HelpPanel content yet. */
export function HelpUnavailable() {
  return (
    <div className="space-y-2">
      <p className="text-sm font-semibold">Help</p>
      <p className="text-xs leading-5 text-muted-foreground">
        Detailed help for this step is not available yet. Use the Description
        tab for the step schema, or open Configuration to set the available
        options.
      </p>
    </div>
  );
}

/** Shared fan-out documentation for inventory selector steps. */
export function FanOutHelpSection() {
  return (
    <HelpSection title="Fan-out">
      <p>
        When <HelpCode>fan_out</HelpCode> is off (default), the whole workflow
        runs once with every matched device sharing a single context.
      </p>
      <p>
        When enabled, each device — or each chunk of devices — is processed as
        an independent Hatchet child workflow. Place a{" "}
        <span className="font-medium text-foreground">Fan In</span> node before
        any git / shared store steps so those run once on the merged result.
      </p>
      <ul className="list-disc space-y-1.5 pl-4">
        <li>
          <span className="font-medium text-foreground">Per device</span> —{" "}
          <HelpCode>mode: per_device</HelpCode>. One child per device (e.g. 50
          routers → 50 children).
        </li>
        <li>
          <span className="font-medium text-foreground">Chunked</span> —{" "}
          <HelpCode>mode: chunked</HelpCode> with{" "}
          <HelpCode>chunk_size</HelpCode> (≥1). Example: 50 devices, chunk size{" "}
          <HelpCode>10</HelpCode> → 5 children.
        </li>
        <li>
          <span className="font-medium text-foreground">Max concurrency</span> —{" "}
          <HelpCode>0</HelpCode> unlimited, <HelpCode>1</HelpCode> sequential,{" "}
          <HelpCode>5</HelpCode> at most five children at once.
        </li>
      </ul>
      <HelpWarning title="Git and shared stores are not fan-out-safe">
        <p>
          Pattern: inventory (fan-out on) → per-device steps → Fan In → store /
          git-push once.
        </p>
      </HelpWarning>
    </HelpSection>
  );
}
