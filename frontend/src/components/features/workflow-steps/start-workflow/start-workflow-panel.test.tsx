import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { StaticAttributeDef } from "@/components/features/workflows/types/workflow-persistence";

import { StartWorkflowPlugin } from "./index";

const workflows = [
  { id: 7, name: "Backup" },
  { id: 8, name: "Other" },
];

let targetData: Record<string, unknown> | undefined;

vi.mock("@/hooks/queries/use-workflows-query", () => ({
  useWorkflowsQuery: () => ({ data: { workflows }, isLoading: false }),
}));
vi.mock("@/hooks/queries/use-workflow-query", () => ({
  useWorkflowQuery: () => ({ data: targetData, isError: false }),
}));
vi.mock(
  "@/components/features/schedules/components/schedule-parameter-fields",
  () => ({
    ScheduleParameterFields: ({
      attributes,
    }: {
      attributes: StaticAttributeDef[];
    }) => (
      <ul data-testid="fields">
        {attributes.map((attr) => (
          <li key={attr.name}>{attr.name}</li>
        ))}
      </ul>
    ),
  }),
);

const fromUser = (param: string) => ({
  id: param,
  data: { kind: "get-from-user", pluginConfig: { device_param: param } },
});

function target(
  attrs: StaticAttributeDef[],
  nodes: unknown[],
): Record<string, unknown> {
  return {
    id: 7,
    name: "Backup",
    static_attributes: attrs,
    canvas_nodes: nodes,
  };
}

const TARGETS: StaticAttributeDef = {
  name: "targets",
  type: "string",
  required: true,
};

function renderPanel(config: Record<string, unknown>, nodes: unknown[] = []) {
  const onChange = vi.fn();
  const { ConfigPanel } = StartWorkflowPlugin;
  render(
    <ConfigPanel
      nodeId="n1"
      config={config}
      onChange={onChange}
      onPreview={() => undefined}
      workflowNodes={nodes as never}
    />,
  );
  return onChange;
}

beforeEach(() => {
  targetData = undefined;
});
afterEach(cleanup);

describe("StartWorkflow config panel", () => {
  it("passes the devices to the only text input a Get from User step reads", () => {
    targetData = target([TARGETS], [fromUser("targets")]);
    const onChange = renderPanel({ workflow_id: 7 });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ workflow_id: 7, devices_input: "targets" }),
    );
  });

  it("does not pick one when the workflow has several candidates", () => {
    targetData = target(
      [TARGETS, { name: "more", type: "string", required: false }],
      [fromUser("targets"), fromUser("more")],
    );
    const onChange = renderPanel({ workflow_id: 7 });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ devices_input: "" }),
    );
  });

  it("never overrides an explicit choice, not even 'none'", () => {
    targetData = target([TARGETS], [fromUser("targets")]);
    const onChange = renderPanel({ workflow_id: 7, devices_input: "" });
    expect(onChange).not.toHaveBeenCalled();
    expect(
      screen.getByText(/expects devices, but none are passed/i),
    ).toBeTruthy();
  });

  it("lists only the inputs it fills by hand: not the device input, not secrets", () => {
    targetData = target(
      [
        TARGETS,
        { name: "site", type: "string", required: false },
        { name: "tacacs", type: "secret", required: false },
      ],
      [fromUser("targets")],
    );
    renderPanel({ workflow_id: 7, devices_input: "targets" });
    expect(screen.getByTestId("fields").textContent).toBe("site");
    expect(screen.getByText(/never passed by a step/i).textContent).toContain(
      "tacacs",
    );
  });

  it("warns about a required secret the step cannot give", () => {
    targetData = target(
      [{ name: "tacacs", type: "secret", required: true }],
      [],
    );
    renderPanel({ workflow_id: 7, devices_input: "" });
    expect(screen.getByText(/cannot\s+be started from here/i)).toBeTruthy();
  });

  it("warns about required inputs without a default that are still empty", () => {
    targetData = target(
      [TARGETS, { name: "site", type: "string", required: true }],
      [fromUser("targets")],
    );
    renderPanel({ workflow_id: 7, devices_input: "targets", run_inputs: {} });
    expect(screen.getByText(/Required, no default: site/)).toBeTruthy();
  });

  it("warns about one run per device, with the cap and the fan-out risk", () => {
    targetData = target([TARGETS], [fromUser("targets")]);
    renderPanel(
      {
        workflow_id: 7,
        devices_input: "targets",
        run_mode: "per_device",
        max_runs: 10,
      },
      [{ id: "inv", data: { pluginConfig: { fan_out: { enabled: true } } } }],
    );
    const warning = screen.getByText(/Starts one run for every device/);
    expect(warning.textContent).toContain("10");
    expect(warning.textContent).toContain("fans out");
  });

  it("shows no run-mode controls when no devices are passed", () => {
    targetData = target([], []);
    renderPanel({ workflow_id: 7, devices_input: "" });
    expect(screen.queryByText(/One run per device/)).toBeNull();
    expect(screen.getByText(/takes no devices/i)).toBeTruthy();
  });

  it("flags run inputs the workflow no longer declares", () => {
    targetData = target([TARGETS], [fromUser("targets")]);
    renderPanel({
      workflow_id: 7,
      devices_input: "targets",
      run_inputs: { gone: "x" },
    });
    expect(
      screen.getByText(/Not declared by this workflow any more: gone/),
    ).toBeTruthy();
  });
});
