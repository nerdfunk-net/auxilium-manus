import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FACT_OPTIONS, GetAciDetailsPlugin } from "./index";

const { ConfigPanel } = GetAciDetailsPlugin;

type Config = Record<string, unknown>;

function setup(config: Config) {
  const onChange = vi.fn<(next: Config) => void>();
  render(<ConfigPanel nodeId="n1" config={config} onChange={onChange} onPreview={vi.fn()} />);
  return onChange;
}

describe("get-aci-details config panel", () => {
  it("offers exactly the facts the backend implements", () => {
    const source = readFileSync(
      resolve(__dirname, "../../../../../../backend/workflow_steps/get_aci_details/executor.py"),
      "utf8",
    );
    const block = /^FACTS = \(([^)]*)\)/m.exec(source)?.[1] ?? "";
    const backend = [...block.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
    expect(FACT_OPTIONS.map((o) => o.value)).toEqual(backend);
    expect(backend).toHaveLength(12);
  });

  it("checks the default facts and adds a fact on click", () => {
    const onChange = setup({});
    expect(screen.getByRole("checkbox", { name: /^Device/ }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("checkbox", { name: /^Hardware/ }).getAttribute("aria-checked")).toBe("false");
    fireEvent.click(screen.getByRole("checkbox", { name: /^Hardware/ }));
    const next = onChange.mock.calls.at(-1)![0];
    expect(next.facts).toEqual(expect.arrayContaining(["device", "software", "interfaces", "hardware"]));
  });

  it("writes the output key", () => {
    const onChange = setup({ parsed_output_key: "aci_details" });
    fireEvent.change(screen.getByDisplayValue("aci_details"), { target: { value: "x" } });
    expect(onChange.mock.calls.at(-1)![0].parsed_output_key).toBe("x");
  });
});
