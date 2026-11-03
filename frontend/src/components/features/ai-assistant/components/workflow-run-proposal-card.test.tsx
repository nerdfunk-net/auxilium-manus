import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkflowRunProposal } from "../types/ai-assistant";

const mutateAsync = vi.fn();
const mutationState = { isPending: false };
vi.mock("../hooks/use-workflow-run-confirm", () => ({
  useWorkflowRunConfirmMutation: () => ({ mutateAsync, ...mutationState }),
}));

const credentials = { data: undefined as unknown };
vi.mock(
  "@/components/features/settings/credentials/hooks/use-credentials-query",
  () => ({ useCredentialsQuery: () => credentials }),
);

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
          <option value="">choose</option>
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

import { WorkflowRunProposalCard } from "./workflow-run-proposal-card";

const NOW = 1_800_000_000;
const SW1 = { name: "sw1", ip: "10.0.0.1", inInventory: true };
const NEW = { name: "192.168.5.9", ip: "192.168.5.9", inInventory: false };

function proposal(
  overrides: Partial<WorkflowRunProposal> = {},
): WorkflowRunProposal {
  return {
    kind: "workflow_run",
    summary: "Run PyATS Compare",
    token: "signed.token",
    expiresAt: NOW + 600,
    workflow: { id: 5, name: "PyATS Compare" },
    inputs: { features: "ospf", strict: true },
    devices: [SW1],
    credentialInputs: [],
    driverChoices: [],
    state: "pending",
    ...overrides,
  };
}

function renderCard(p: WorkflowRunProposal, busy = false) {
  const onResult = vi.fn();
  const onReject = vi.fn();
  const onAskResult = vi.fn();
  render(
    <WorkflowRunProposalCard
      proposal={p}
      onResult={onResult}
      onReject={onReject}
      onAskResult={onAskResult}
      busy={busy}
    />,
  );
  return { onResult, onReject, onAskResult };
}

const runButton = () =>
  screen.getByRole("button", { name: /^run$/i }) as HTMLButtonElement;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW * 1000);
  mutateAsync.mockReset();
  mutationState.isPending = false;
  credentials.data = {
    credentials: [
      { id: 11, name: "lab-ssh", username: "admin", type: "ssh" },
      { id: 12, name: "api-token", username: "svc", type: "generic" },
    ],
  };
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("WorkflowRunProposalCard", () => {
  it("shows the workflow, inputs and devices with their addresses as text", () => {
    renderCard(proposal());

    expect(screen.getByText("PyATS Compare")).toBeTruthy();
    expect(screen.getByTestId("workflow-run-inputs").textContent).toContain(
      "ospf",
    );
    expect(screen.getByTestId("workflow-run-devices").textContent).toContain(
      "sw1",
    );
    expect(screen.getByTestId("workflow-run-devices").textContent).toContain(
      "10.0.0.1",
    );
    expect(screen.queryByText(/not in the inventory/i)).toBeNull();
  });

  it("starts nothing until Run is clicked, then sends the token and nothing else", async () => {
    mutateAsync.mockResolvedValue({ runId: 42, workflowId: 5 });
    const { onResult } = renderCard(proposal());
    expect(mutateAsync).not.toHaveBeenCalled();

    fireEvent.click(runButton());

    await waitFor(() =>
      expect(onResult).toHaveBeenCalledWith({ runId: 42, workflowId: 5 }),
    );
    expect(mutateAsync).toHaveBeenCalledWith({
      token: "signed.token",
      credentials: {},
      freeIpDriver: undefined,
    });
  });

  it("makes the user choose a credential for every credential input, from their SSH logins", async () => {
    mutateAsync.mockResolvedValue({ runId: 42, workflowId: 5 });
    renderCard(proposal({ credentialInputs: ["cred"] }));
    const select = screen.getByLabelText("Credential for cred");

    expect(runButton().disabled).toBe(true);
    const options = Array.from(select.querySelectorAll("option")).map(
      (o) => o.textContent,
    );
    expect(options.some((o) => o?.includes("lab-ssh"))).toBe(true);
    expect(options.some((o) => o?.includes("api-token"))).toBe(false);

    fireEvent.change(select, { target: { value: "lab-ssh" } });
    expect(runButton().disabled).toBe(false);
    fireEvent.click(runButton());

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    expect(mutateAsync).toHaveBeenCalledWith({
      token: "signed.token",
      credentials: { cred: "lab-ssh" },
      freeIpDriver: undefined,
    });
  });

  it("warns about an address outside the inventory and sends the chosen device type", async () => {
    mutateAsync.mockResolvedValue({ runId: 42, workflowId: 5 });
    renderCard(
      proposal({
        devices: [SW1, NEW],
        driverChoices: ["cisco_ios", "cisco_xe"],
      }),
    );

    expect(
      screen.getByTestId("workflow-run-outside-warning").textContent,
    ).toContain("192.168.5.9");
    expect(screen.getByText(/not in the inventory$/i)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Device type"), {
      target: { value: "cisco_xe" },
    });
    fireEvent.click(runButton());

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    expect(mutateAsync.mock.calls[0][0].freeIpDriver).toBe("cisco_xe");
  });

  it("does not offer a device type when every device is in the inventory", () => {
    renderCard(proposal({ driverChoices: ["cisco_ios"] }));
    expect(screen.queryByLabelText("Device type")).toBeNull();
    expect(screen.queryByTestId("workflow-run-outside-warning")).toBeNull();
  });

  it("shows the server's error and does not report a result", async () => {
    mutateAsync.mockRejectedValue(
      new Error("This workflow is no longer released"),
    );
    const { onResult } = renderCard(proposal());

    fireEvent.click(runButton());

    expect(
      await screen.findByText("This workflow is no longer released"),
    ).toBeTruthy();
    expect(onResult).not.toHaveBeenCalled();
  });

  it("disables Run once the proposal has expired", () => {
    renderCard(proposal({ expiresAt: NOW - 1 }));

    expect(screen.getByText(/expired/i)).toBeTruthy();
    expect(runButton().disabled).toBe(true);
  });

  it("waits while the assistant is still answering", () => {
    renderCard(proposal(), true);

    expect(runButton().disabled).toBe(true);
  });

  it("rejecting reports it and a rejected card offers nothing to run", () => {
    const { onReject } = renderCard(proposal());
    fireEvent.click(screen.getByRole("button", { name: /reject/i }));
    expect(onReject).toHaveBeenCalled();

    cleanup();
    renderCard(proposal({ state: "rejected" }));
    expect(screen.queryByRole("button", { name: /^run$/i })).toBeNull();
    expect(screen.getByText(/nothing was started/i)).toBeTruthy();
  });

  it("after the start shows the run id and lets the user ask for the result", () => {
    const { onAskResult } = renderCard(
      proposal({ state: "applied", result: { runId: 42, workflowId: 5 } }),
    );

    expect(screen.getByTestId("workflow-run-started").textContent).toContain(
      "run 42",
    );
    fireEvent.click(screen.getByRole("button", { name: /read the result/i }));
    expect(onAskResult).toHaveBeenCalledWith(
      { runId: 42, workflowId: 5 },
      "PyATS Compare",
    );
  });
});
