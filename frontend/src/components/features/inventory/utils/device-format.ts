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
      return "bg-green-100 text-green-800";
    case "planned":
      return "bg-blue-100 text-blue-800";
    case "staged":
      return "bg-yellow-100 text-yellow-800";
    case "failed":
      return "bg-red-100 text-red-800";
    case "offline":
      return "bg-gray-100 text-gray-800";
    default:
      return "bg-blue-100 text-blue-800";
  }
}
