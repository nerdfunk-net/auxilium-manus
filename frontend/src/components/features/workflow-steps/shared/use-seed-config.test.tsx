import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useSeedConfigOnce } from "./use-seed-config";

type Config = Record<string, unknown>;

function setup(seed: (config: Config) => Config | null, config: Config = {}) {
  const onChange = vi.fn();
  const view = renderHook(
    (props: { nodeId: string; config: Config }) =>
      useSeedConfigOnce({ nodeId: props.nodeId, config: props.config, onChange, seed }),
    { initialProps: { nodeId: "n1", config } },
  );
  return { onChange, ...view };
}

describe("useSeedConfigOnce", () => {
  it("writes the seed when the node is first opened", () => {
    const { onChange } = setup((config) => ({ ...config, a: 1 }), { b: 2 });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ b: 2, a: 1 });
  });

  it("writes nothing when the seed is null", () => {
    const { onChange } = setup(() => null);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("does not seed again when the config changes for the same node", () => {
    const { onChange, rerender } = setup(() => ({ a: 1 }));
    rerender({ nodeId: "n1", config: { a: 1, edited: true } });
    rerender({ nodeId: "n1", config: {} });
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("seeds a null result only once too: a later seedable config is left alone", () => {
    let seedable = false;
    const { onChange, rerender } = setup(() => (seedable ? { a: 1 } : null));
    seedable = true;
    rerender({ nodeId: "n1", config: { x: 1 } });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("seeds again for another node", () => {
    const { onChange, rerender } = setup(() => ({ a: 1 }));
    rerender({ nodeId: "n2", config: {} });
    expect(onChange).toHaveBeenCalledTimes(2);
  });
});
