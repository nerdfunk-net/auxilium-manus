/** The handle the server gives a stored result: `res_` + 12 hex digits. */
export const RESULT_HANDLE = /^res_[0-9a-f]{12}$/;

function slug(value: string, fallback: string): string {
  return (
    value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || fallback
  );
}

/** `<device>-<running|startup>-config.cfg`, with both parts reduced to a safe slug. */
export function configFileName(device: string, kind: string): string {
  return `${slug(device, "device")}-${slug(kind, "running")}-config.cfg`;
}

/** "1,204 lines, 38 KB" for the card. */
export function describeSize(lineCount: number, sizeChars: number): string {
  const kb = Math.max(1, Math.round(sizeChars / 1024));
  return `${lineCount.toLocaleString("en-US")} lines, ${kb} KB`;
}
