/** "2026-11-17T09:30:00.123Z" -> locale date/time; unknown or missing -> "unknown date". */
export function formatSnapshotDate(createdAt: string | null | undefined): string {
  if (!createdAt) {
    return "unknown date";
  }
  const parsed = new Date(createdAt);
  return Number.isNaN(parsed.getTime()) ? "unknown date" : parsed.toLocaleString();
}

/** Snapshot label with its date in braces right behind the name. */
export function snapshotLabel(
  name: string,
  createdAt: string | null | undefined,
): string {
  return `${name} (${formatSnapshotDate(createdAt)})`;
}
