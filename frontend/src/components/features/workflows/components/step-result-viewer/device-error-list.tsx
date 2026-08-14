"use client";

import type { DeviceError } from "@/lib/workflow-context-types";

export function DeviceErrorList({ errors }: { errors: DeviceError[] }) {
  if (errors.length === 0) {
    return null;
  }

  return (
    <ul className="mt-2 space-y-1">
      {errors.map((error, index) => (
        <li
          key={`${error.code}-${error.occurred_at}-${index}`}
          className="rounded bg-error px-2 py-1 text-xs text-error-foreground"
        >
          <span className="font-mono font-medium">{error.code}</span>
          {" — "}
          {error.message}
        </li>
      ))}
    </ul>
  );
}
