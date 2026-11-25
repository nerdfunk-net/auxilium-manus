import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BatfishCombinedFactsPanel, type FactsQuestionToggle } from "./batfish-combined-facts-panel";

vi.mock("./batfish-direct-target-fields", () => ({
  BatfishDirectTargetFields: ({ config }: { config: Record<string, unknown> }) => (
    <div data-testid="direct-target" data-config={JSON.stringify(config)} />
  ),
}));

const TOGGLES: FactsQuestionToggle[] = [
  { key: "include_a", label: "Alpha", hint: "alphaQuestion rows" },
  { key: "include_b", label: "Beta", hint: "betaQuestion rows" },
];

function setup(config: Record<string, unknown> = {}) {
  const onChange = vi.fn();
  render(
    <BatfishCombinedFactsPanel
      config={config}
      onChange={onChange}
      toggles={TOGGLES}
      defaultOutputKey="batfish_x_facts"
    />,
  );
  return onChange;
}

describe("BatfishCombinedFactsPanel", () => {
  it("lists every toggle with its hint, on by default", () => {
    setup();
    expect(screen.getByText("alphaQuestion rows")).toBeTruthy();
    expect(screen.getByText("betaQuestion rows")).toBeTruthy();
    expect(screen.getAllByRole("checkbox").slice(0, 2).map((b) => b.getAttribute("aria-checked"))).toEqual([
      "true",
      "true",
    ]);
  });

  it("shows the default output key as placeholder", () => {
    setup();
    expect(screen.getByPlaceholderText("batfish_x_facts")).toBeTruthy();
  });

  it("writes a toggle without touching the other keys", () => {
    const onChange = setup({ nodes: "R1" });
    fireEvent.click(screen.getByRole("checkbox", { name: /Alpha/ }));
    expect(onChange).toHaveBeenCalledWith({ nodes: "R1", include_a: false });
  });

  it("keeps the last enabled question on", () => {
    setup({ include_a: false });
    const beta = screen.getByRole("checkbox", { name: /Beta/ });
    expect(beta.hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("checkbox", { name: /Alpha/ }).hasAttribute("disabled")).toBe(false);
  });

  it("writes nodes and output_key", () => {
    const onChange = setup({ output_key: "k" });
    fireEvent.change(screen.getByPlaceholderText("e.g. R1"), { target: { value: "R2" } });
    expect(onChange).toHaveBeenCalledWith({ output_key: "k", nodes: "R2" });
    fireEvent.change(screen.getByPlaceholderText("batfish_x_facts"), { target: { value: "o" } });
    expect(onChange).toHaveBeenCalledWith({ output_key: "o" });
  });

  it("renders the direct target fields with the config", () => {
    setup({ nodes: "R1" });
    const el = screen.getByTestId("direct-target");
    expect(JSON.parse(el.getAttribute("data-config") ?? "{}")).toEqual({ nodes: "R1" });
  });
});
