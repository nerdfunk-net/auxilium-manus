export function bareIp(value: string | null): string | null {
  if (!value) {
    return null;
  }
  return value.split("/")[0] || null;
}
