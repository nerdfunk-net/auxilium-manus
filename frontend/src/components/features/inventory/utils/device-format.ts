export function formatDeviceValue(
  value: string | { name?: string; address?: string } | null | undefined,
): string {
  if (!value) return "N/A";
  if (typeof value === "object") {
    return value.name || value.address?.split("/")[0] || "N/A";
  }
  return value;
}

export function getStatusColor(status: string): string {
  switch (status?.toLowerCase()) {
    case "active":
      return "bg-success text-success-foreground";
    case "planned":
      return "bg-info text-info-foreground";
    case "staged":
      return "bg-warning text-warning-foreground";
    case "failed":
      return "bg-error text-error-foreground";
    case "offline":
      return "bg-muted text-foreground";
    default:
      return "bg-info text-info-foreground";
  }
}
