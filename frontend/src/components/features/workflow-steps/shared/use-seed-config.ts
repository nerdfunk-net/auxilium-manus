import { useEffect, useRef } from "react";

interface SeedConfigOptions {
  nodeId: string;
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  /** The config to write, or null when this node needs nothing. Wrap it in `useCallback`. */
  seed: (config: Record<string, unknown>) => Record<string, unknown> | null;
}

/** Writes derived state into a node the first time its panel opens (once per node id).
 *
 * Only for what the backend cannot default: a value inferred from the canvas (the upstream
 * step a step reads from) or node state derived from the config. Plain defaults are not
 * seeded; the panel shows them and writes nothing until the user edits (D8,
 * doc/analysis W14-03). */
export function useSeedConfigOnce({ nodeId, config, onChange, seed }: SeedConfigOptions): void {
  const seededFor = useRef<string | null>(null);

  useEffect(() => {
    if (seededFor.current === nodeId) return;
    seededFor.current = nodeId;
    const next = seed(config);
    if (next) onChange(next);
  }, [nodeId, config, onChange, seed]);
}
