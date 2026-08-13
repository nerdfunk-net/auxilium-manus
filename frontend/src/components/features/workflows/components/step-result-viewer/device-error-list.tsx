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
          className="rounded bg-red-50 px-2 py-1 text-xs text-red-700 dark:bg-red-950/30 dark:text-red-400"
        >
          <span className="font-mono font-medium">{error.code}</span>
          {" — "}
          {error.message}
        </li>
      ))}
    </ul>
  );
}
