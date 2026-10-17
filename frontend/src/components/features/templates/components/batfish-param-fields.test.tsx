import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ParamFieldGrid, type ParamFieldSpec } from "./batfish-param-fields";

const FIELDS: readonly ParamFieldSpec[] = [
  { kind: "text", key: "node", id: "f-node", label: "Node", required: true },
  { kind: "list", key: "applications", id: "f-apps", label: "Applications" },
  { kind: "integer", key: "max_traces", id: "f-max", label: "Max Traces", min: 1 },
];

afterEach(cleanup);

describe("ParamFieldGrid", () => {
  it("shows Required while a required text field is blank", () => {
    render(<ParamFieldGrid fields={FIELDS} params={{}} onParamsChange={vi.fn()} />);
    expect(screen.getByText("Required")).toBeTruthy();
  });

  it("hides Required once the field has a value", () => {
    render(<ParamFieldGrid fields={FIELDS} params={{ node: "R1" }} onParamsChange={vi.fn()} />);
    expect(screen.queryByText("Required")).toBeNull();
  });

  it("emits a new params object (no mutation) when a text field changes", () => {
    const params = { node: "R1" };
    const onParamsChange = vi.fn();
    render(<ParamFieldGrid fields={FIELDS} params={params} onParamsChange={onParamsChange} />);
    fireEvent.change(screen.getByLabelText("Node"), { target: { value: "R2" } });
    expect(onParamsChange).toHaveBeenCalledWith({ node: "R2" });
    expect(params).toEqual({ node: "R1" });
  });

  it("splits the list field on commas into a string array", () => {
    const onParamsChange = vi.fn();
    render(<ParamFieldGrid fields={FIELDS} params={{}} onParamsChange={onParamsChange} />);
    fireEvent.change(screen.getByLabelText("Applications"), { target: { value: "SSH, HTTPS ,," } });
    expect(onParamsChange).toHaveBeenCalledWith({ applications: ["SSH", "HTTPS"] });
  });

  it("stores integers as numbers", () => {
    const onParamsChange = vi.fn();
    render(<ParamFieldGrid fields={FIELDS} params={{}} onParamsChange={onParamsChange} />);
    fireEvent.change(screen.getByLabelText("Max Traces"), { target: { value: "5" } });
    expect(onParamsChange).toHaveBeenCalledWith({ max_traces: 5 });
  });
});
