import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/** Monospace preview block (logical expression, device list). Follows the theme tokens. */
export function CodePreview({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-md border bg-muted font-mono text-foreground", className)}
      {...props}
    />
  );
}
