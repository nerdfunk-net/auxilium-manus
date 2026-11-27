/** A path into the editor's `parsed` variable: `["cisco_config"]`, or `[node_id, output_key]`
 * for the entry a facts step writes at runtime (`set_node_result` in the backend). */
export type ParsedPath = readonly [string, ...string[]];

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function without(root: JsonObject, key: string): JsonObject {
  return Object.fromEntries(
    Object.entries(root).filter(([name]) => name !== key),
  );
}

/** `root` with `entry` at `path`, as a new object: objects on the way are copied, anything
 * else in the way is replaced by an object. */
export function withParsedEntry(
  root: JsonObject,
  path: ParsedPath,
  entry: unknown,
): JsonObject {
  const [head, ...rest] = path;
  if (rest.length === 0) return { ...root, [head]: entry };
  const child = root[head];
  return {
    ...root,
    [head]: withParsedEntry(
      isObject(child) ? child : {},
      rest as unknown as ParsedPath,
      entry,
    ),
  };
}

/** `root` without the value at `path`; an object the removal leaves empty goes too. Returns
 * `root` itself when nothing is at `path`. */
export function withoutParsedEntry(
  root: JsonObject,
  path: ParsedPath,
): JsonObject {
  const [head, ...rest] = path;
  if (!Object.hasOwn(root, head)) return root;
  if (rest.length === 0) return without(root, head);
  const child = root[head];
  if (!isObject(child)) return root;
  const nextChild = withoutParsedEntry(child, rest as unknown as ParsedPath);
  if (nextChild === child) return root;
  return Object.keys(nextChild).length > 0
    ? { ...root, [head]: nextChild }
    : without(root, head);
}
