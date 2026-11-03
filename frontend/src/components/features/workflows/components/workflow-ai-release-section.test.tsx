import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const storeState = {
  workflowId: 7 as number | null,
  workflowVisibility: "public",
  isDirty: false,
};
vi.mock("../hooks/use-workflow-builder-store", () => ({
  useWorkflowBuilderStore: (selector: (s: typeof storeState) => unknown) =>
    selector(storeState),
}));

const authState = { user: { id: 1 } };
vi.mock("@/lib/auth-store", () => ({
  useAuthStore: (selector: (s: typeof authState) => unknown) =>
    selector(authState),
}));

const permissions = { allowed: true };
vi.mock("@/lib/permissions", () => ({
  hasPermission: (_user: unknown, resource: string, action: string) =>
    permissions.allowed && resource === "workflows" && action === "release_ai",
}));

const toast = vi.fn();
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast }) }));

const query = {
  data: undefined as unknown,
  refetch: vi.fn(),
};
vi.mock("@/hooks/queries/use-workflow-ai-release-query", () => ({
  useWorkflowAiReleaseQuery: () => query,
}));

const release = { mutate: vi.fn(), isPending: false };
const unrelease = { mutate: vi.fn(), isPending: false };
vi.mock("@/hooks/queries/use-workflow-ai-release-mutations", () => ({
  useWorkflowAiReleaseMutations: () => ({ release, unrelease }),
}));

// Radix Select is awkward in jsdom; a native select keeps the test about our logic.
vi.mock("@/components/ui/select", async () => {
  const React = await import("react");
  const SelectTrigger = (props: { "aria-label"?: string }) =>
    props ? null : null;
  return {
    Select: ({
      value,
      onValueChange,
      children,
    }: {
      value: string;
      onValueChange: (v: string) => void;
      children: React.ReactNode;
    }) => {
      const trigger = React.Children.toArray(children).find(
        (child) => React.isValidElement(child) && child.type === SelectTrigger,
      ) as React.ReactElement<{ "aria-label"?: string }> | undefined;
      return (
        <select
          aria-label={trigger?.props["aria-label"]}
          value={value}
          onChange={(e) => onValueChange(e.target.value)}
        >
          {children}
        </select>
      );
    },
    SelectTrigger,
    SelectValue: () => null,
    SelectContent: ({ children }: { children: React.ReactNode }) => (
      <>{children}</>
    ),
    SelectItem: ({
      value,
      children,
    }: {
      value: string;
      children: React.ReactNode;
    }) => <option value={value}>{children}</option>,
  };
});

import { WorkflowAiReleaseSection } from "./workflow-ai-release-section";

const NODES = [
  { id: "n1", type: "workflowNode", data: { title: "Get snapshot" } },
  { id: "n2", type: "workflowNode", data: { title: "Compare" } },
  { id: "l1", type: "labelNode", data: { title: "A label" } },
];

beforeEach(() => {
  storeState.workflowId = 7;
  storeState.workflowVisibility = "public";
  storeState.isDirty = false;
  permissions.allowed = true;
  query.data = {
    ai_released: false,
    ai_description: null,
    ai_result_node_id: null,
    canvas_nodes: NODES,
  };
  query.refetch.mockReset();
  release.mutate.mockReset();
  unrelease.mutate.mockReset();
});

afterEach(cleanup);

describe("WorkflowAiReleaseSection", () => {
  it("is hidden without the release permission", () => {
    permissions.allowed = false;
    render(<WorkflowAiReleaseSection />);
    expect(screen.queryByText(/Release to be used by Ask the Net/i)).toBeNull();
  });

  it("lists only executable steps as result choices", () => {
    render(<WorkflowAiReleaseSection />);
    expect(screen.getByRole("option", { name: "Compare" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "A label" })).toBeNull();
  });

  it("needs a description before it can release, and says so", () => {
    render(<WorkflowAiReleaseSection />);
    expect(screen.getByRole("status").textContent).toMatch(
      /Describe the workflow/i,
    );
    expect(
      (screen.getByRole("button", { name: "Release" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("releases with the description and the chosen result step", () => {
    render(<WorkflowAiReleaseSection />);
    fireEvent.change(screen.getByLabelText(/Description for the assistant/i), {
      target: { value: "  Compare with the baseline.  " },
    });
    fireEvent.change(screen.getByLabelText("Result step"), {
      target: { value: "n2" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Release" }));

    expect(release.mutate).toHaveBeenCalledWith(
      {
        workflowId: 7,
        data: {
          description: "Compare with the baseline.",
          result_node_id: "n2",
          devices_input: null,
          credential_inputs: [],
          allow_free_ip: false,
        },
      },
      expect.any(Object),
    );
  });

  it("sends no result step when none is chosen", () => {
    render(<WorkflowAiReleaseSection />);
    fireEvent.change(screen.getByLabelText(/Description for the assistant/i), {
      target: { value: "x" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    expect(release.mutate.mock.calls[0][0].data.result_node_id).toBeNull();
  });

  it("blocks a private workflow and an unsaved one, saying why", () => {
    storeState.workflowVisibility = "private";
    const { unmount } = render(<WorkflowAiReleaseSection />);
    expect(screen.getByRole("status").textContent).toMatch(/not private/i);
    unmount();

    storeState.workflowVisibility = "public";
    storeState.isDirty = true;
    render(<WorkflowAiReleaseSection />);
    expect(screen.getByRole("status").textContent).toMatch(
      /Save the workflow/i,
    );
    expect(
      (screen.getByRole("button", { name: "Release" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("warns when the release is broken by a change to a workflow it starts", () => {
    query.data = {
      ai_released: true,
      ai_release_current: false,
      ai_description: "Compare.",
      ai_result_node_id: "n2",
      ai_released_at: "2026-11-03T10:00:00Z",
      canvas_nodes: NODES,
    };
    render(<WorkflowAiReleaseSection />);

    expect(screen.getByTestId("ai-release-broken")).toBeTruthy();
  });

  it("shows no warning while the release is current", () => {
    query.data = {
      ai_released: true,
      ai_release_current: true,
      ai_description: "Compare.",
      ai_result_node_id: "n2",
      ai_released_at: "2026-11-03T10:00:00Z",
      canvas_nodes: NODES,
    };
    render(<WorkflowAiReleaseSection />);

    expect(screen.queryByTestId("ai-release-broken")).toBeNull();
  });

  it("shows the saved release and can remove it", () => {
    query.data = {
      ai_released: true,
      ai_description: "Compare.",
      ai_result_node_id: "n2",
      ai_released_at: "2026-11-03T10:00:00Z",
      canvas_nodes: NODES,
    };
    render(<WorkflowAiReleaseSection />);

    expect(
      (
        screen.getByLabelText(
          /Description for the assistant/i,
        ) as HTMLTextAreaElement
      ).value,
    ).toBe("Compare.");
    expect(
      (screen.getByLabelText("Result step") as HTMLSelectElement).value,
    ).toBe("n2");
    fireEvent.click(screen.getByRole("button", { name: "Remove release" }));
    expect(unrelease.mutate).toHaveBeenCalledWith(7, expect.any(Object));
    expect(screen.getByRole("button", { name: "Update release" })).toBeTruthy();
  });

  describe("devices, credentials and addresses outside the inventory", () => {
    const INPUTS = [
      { name: "devs", type: "string" },
      { name: "note", type: "string" },
      { name: "cred", type: "reference", ref_kind: "credential" },
      { name: "inv", type: "reference", ref_kind: "inventory" },
    ];
    const READER = {
      id: "g",
      type: "workflowNode",
      data: {
        title: "Get devices",
        kind: "get-from-user",
        pluginConfig: { device_param: "devs" },
      },
    };

    beforeEach(() => {
      query.data = {
        ai_released: false,
        ai_description: null,
        ai_result_node_id: null,
        ai_devices_input: null,
        ai_credential_inputs: [],
        ai_allow_free_ip: false,
        canvas_nodes: [...NODES, READER],
        static_attributes: INPUTS,
      };
    });

    function describeIt() {
      fireEvent.change(
        screen.getByLabelText(/Description for the assistant/i),
        {
          target: { value: "Onboard." },
        },
      );
    }

    it("pre-selects the one input a Get from User step reads", () => {
      render(<WorkflowAiReleaseSection />);
      expect(
        (screen.getByLabelText("Devices input") as HTMLSelectElement).value,
      ).toBe("devs");
    });

    it("offers only text inputs as the devices input and only credential references as credentials", () => {
      render(<WorkflowAiReleaseSection />);
      const options = within(screen.getByLabelText("Devices input"))
        .getAllByRole("option")
        .map((o) => o.textContent);
      expect(options).toEqual(["None (takes no devices)", "devs", "note"]);
      expect(screen.getByLabelText("cred")).toBeTruthy();
      expect(screen.queryByLabelText("inv")).toBeNull();
    });

    it("sends the devices input, the chosen credentials and the address switch", () => {
      render(<WorkflowAiReleaseSection />);
      describeIt();
      fireEvent.click(screen.getByLabelText("cred"));
      fireEvent.click(
        screen.getByRole("switch", {
          name: /IPv4 addresses outside the inventory/i,
        }),
      );
      expect(screen.getByText(/log in to an address/i)).toBeTruthy();

      fireEvent.click(screen.getByRole("button", { name: "Release" }));

      expect(release.mutate.mock.calls[0][0].data).toMatchObject({
        devices_input: "devs",
        credential_inputs: ["cred"],
        allow_free_ip: true,
      });
    });

    it("cannot allow outside addresses without a devices input", () => {
      render(<WorkflowAiReleaseSection />);
      fireEvent.change(screen.getByLabelText("Devices input"), {
        target: { value: "__none__" },
      });
      const toggle = screen.getByRole("switch", {
        name: /IPv4 addresses outside the inventory/i,
      }) as HTMLButtonElement;
      expect(toggle.disabled).toBe(true);
      describeIt();
      fireEvent.click(screen.getByRole("button", { name: "Release" }));
      expect(release.mutate.mock.calls[0][0].data).toMatchObject({
        devices_input: null,
        allow_free_ip: false,
      });
    });

    it("shows a saved release instead of the suggestion", () => {
      query.data = {
        ...(query.data as object),
        ai_released: true,
        ai_description: "d",
        ai_devices_input: "note",
        ai_credential_inputs: ["cred"],
        ai_allow_free_ip: true,
      };
      render(<WorkflowAiReleaseSection />);
      expect(
        (screen.getByLabelText("Devices input") as HTMLSelectElement).value,
      ).toBe("note");
      expect(
        screen
          .getByRole("checkbox", { name: "cred" })
          .getAttribute("aria-checked"),
      ).toBe("true");
    });
  });

  it("looks again after the canvas is saved, because a save clears the release", () => {
    render(<WorkflowAiReleaseSection />);
    expect(query.refetch).toHaveBeenCalled();
  });
});
