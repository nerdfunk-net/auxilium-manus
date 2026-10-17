/**
 * A cheap fingerprint of the parts of a canvas the assistant reasons about (step ids, kinds,
 * titles, configs, enabled state and the edges between them). Used only to tell the user "the
 * canvas changed since this proposal was made"; positions and selection are ignored on purpose.
 */
export function canvasFingerprint(
  nodes: readonly Record<string, unknown>[],
  edges: readonly Record<string, unknown>[],
): string {
  const parts = JSON.stringify([
    nodes.map((node) => {
      const data = (node.data ?? {}) as Record<string, unknown>;
      return [
        node.id,
        data.kind,
        data.title,
        data.pluginConfig,
        data.disabled ?? false,
      ];
    }),
    edges.map((edge) => [edge.source, edge.sourceHandle, edge.target]),
  ]);
  let hash = 5381;
  for (let index = 0; index < parts.length; index += 1) {
    hash = ((hash << 5) + hash + parts.charCodeAt(index)) | 0;
  }
  return `${parts.length}:${hash >>> 0}`;
}
