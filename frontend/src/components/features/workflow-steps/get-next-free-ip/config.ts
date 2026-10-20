export const PREFIX_KEY = "prefix";
export const NAMESPACE_KEY = "namespace";
export const COUNT_KEY = "count";
export const START_OFFSET_KEY = "start_offset";
export const ATTRIBUTE_PATH_KEY = "attribute_path";

export const DEFAULT_NAMESPACE = "Global";
export const DEFAULT_COUNT = 1;
export const DEFAULT_START_OFFSET = 1;
export const MAX_COUNT = 100;

export function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const value = config[key];
  return typeof value === "string" ? value : "";
}

/** Text shown in a number input: the stored value, or the default when nothing is stored. */
export function numberText(
  config: Record<string, unknown>,
  key: string,
  fallback: number,
): string {
  const value = config[key];
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value;
  return String(fallback);
}

/**
 * New config with a number input's text applied. A whole number is stored as a number;
 * anything else (an empty box while typing) is kept as typed so the field stays editable
 * and the backend falls back to its default for a blank value.
 */
export function withNumberText(
  config: Record<string, unknown>,
  key: string,
  text: string,
): Record<string, unknown> {
  const trimmed = text.trim();
  return { ...config, [key]: /^-?\d+$/.test(trimmed) ? Number(trimmed) : text };
}

/** Wrap a picked attribute path in braces, without doubling braces already there. */
export function asExpression(path: string): string {
  return `{${path.replace(/^\{|\}$/g, "")}}`;
}

/** True when a number input's current text is a whole number (the backend refuses anything else). */
export function isWholeNumber(config: Record<string, unknown>, key: string, fallback: number): boolean {
  return /^-?\d+$/.test(numberText(config, key, fallback).trim());
}
