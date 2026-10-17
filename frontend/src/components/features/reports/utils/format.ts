/** Local date and time for a timestamp from the API; the raw text when it cannot be parsed. */
export function formatTimestamp(iso: string | null): string {
  if (!iso) return "never";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}
