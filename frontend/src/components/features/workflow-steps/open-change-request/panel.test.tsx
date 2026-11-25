import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OpenChangeRequestPlugin } from "./index";

vi.mock("@/hooks/queries/use-workflows-query", () => ({
  useWorkflowsQuery: () => ({ data: { workflows: [] } }),
}));
vi.mock("@/components/features/workflow-steps/shared/git-repository-select-dialog", () => ({
  GitRepositorySelectDialog: () => null,
}));
vi.mock("@/components/features/workflow-steps/shared/git-repository-value", () => ({
  GitRepositoryValue: () => null,
}));
vi.mock("@/components/ui/select", () => import("@/test/native-select-mock"));

afterEach(cleanup);

function renderPanel(config: Record<string, unknown> = {}) {
  const onChange = vi.fn();
  const { ConfigPanel } = OpenChangeRequestPlugin;
  render(
    <ConfigPanel
      nodeId="n1"
      config={config}
      onChange={onChange}
      onPreview={() => undefined}
      workflowNodes={[]}
      workflowEdges={[]}
    />,
  );
  return onChange;
}

describe("Open Change Request panel: keys that had no control", () => {
  it("edits parsed_output_key", () => {
    const onChange = renderPanel();
    fireEvent.change(screen.getByLabelText("parsed_output_key"), { target: { value: "device_config" } });
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ parsed_output_key: "device_config" }));
  });

  it("edits repository_subdirectory", () => {
    const onChange = renderPanel();
    fireEvent.change(screen.getByLabelText("repository_subdirectory"), {
      target: { value: "network/candidates" },
    });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ repository_subdirectory: "network/candidates" }),
    );
  });

  it("shows strict_templates on by default and turns it off", () => {
    const onChange = renderPanel();
    const box = screen.getByRole("checkbox", { name: "strict_templates" });
    expect(box.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(box);
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ strict_templates: false }));
  });

  it("shows a saved strict_templates: false", () => {
    renderPanel({ strict_templates: false });
    expect(screen.getByRole("checkbox", { name: "strict_templates" }).getAttribute("aria-checked")).toBe(
      "false",
    );
  });

  it("shows the saved values", () => {
    renderPanel({ parsed_output_key: "k", repository_subdirectory: "sub" });
    expect((screen.getByLabelText("parsed_output_key") as HTMLInputElement).value).toBe("k");
    expect((screen.getByLabelText("repository_subdirectory") as HTMLInputElement).value).toBe("sub");
  });
});
