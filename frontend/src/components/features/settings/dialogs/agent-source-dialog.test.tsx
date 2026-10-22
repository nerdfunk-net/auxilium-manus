import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentSourceDialog, type AgentSourceEditValue } from "./agent-source-dialog";

const h = vi.hoisted(() => ({ testMutate: vi.fn(), testPending: { value: false } }));

vi.mock("@/components/ui/select", () => import("@/test/native-select-mock"));
vi.mock("@/hooks/queries/use-agent-sources-mutations", () => ({
  useAgentSourcesMutations: () => ({
    testConnection: { mutate: h.testMutate, isPending: h.testPending.value },
  }),
}));
vi.mock("../components/agent-status-panel", () => ({
  AgentStatusPanel: ({ sourceId }: { sourceId: string }) => <div>status of {sourceId}</div>,
}));
vi.mock("../credentials/components/credential-select", () => ({
  CredentialSelect: ({
    id,
    value,
    onChange,
    credentialType,
  }: {
    id: string;
    value: number | null;
    onChange: (next: number | null) => void;
    credentialType: string;
  }) => (
    <select
      id={id}
      data-type={credentialType}
      value={value ?? ""}
      onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}
    >
      <option value="">none</option>
      <option value="7">agent-key</option>
    </select>
  ),
}));

function setup(props: Partial<React.ComponentProps<typeof AgentSourceDialog>> = {}) {
  const handlers = { onClose: vi.fn(), onCreate: vi.fn(), onUpdate: vi.fn() };
  render(<AgentSourceDialog open mode="create" {...handlers} {...props} />);
  return handlers;
}

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

async function submit() {
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => undefined);
}

function fillHttp() {
  type("Source ID", "geo");
  type("Agent ID", "geo-agent");
  type("Agent URL", " http://geo-agent:8080 ");
  type("Shared secret", "7");
}

beforeEach(() => {
  h.testMutate.mockReset();
  h.testPending.value = false;
});

describe("AgentSourceDialog create", () => {
  it("sends an http agent with the URL trimmed and limits converted to bytes", async () => {
    const { onCreate } = setup();
    fillHttp();
    type("Max request (KiB)", "512");
    await submit();
    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(1));
    expect(onCreate).toHaveBeenCalledWith({
      source_id: "geo",
      transport: "http",
      agent_id: "geo-agent",
      url: "http://geo-agent:8080",
      credential_id: 7,
      max_concurrency: 4,
      max_request_bytes: 512 * 1024,
      max_timeout_seconds: 60,
    });
  });

  it("only offers shared-secret credentials", () => {
    setup();
    expect(screen.getByLabelText("Shared secret").getAttribute("data-type")).toBe("shared_secret");
  });

  it("a redis agent has no URL field, shows its ACL command and sends url null", async () => {
    const { onCreate } = setup();
    type("Source ID", "geo");
    type("Agent ID", "geo-agent");
    type("Shared secret", "7");
    fireEvent.change(screen.getByLabelText("Transport"), { target: { value: "redis" } });

    expect(screen.queryByLabelText("Agent URL")).toBeNull();
    expect(screen.getByText(/ACL SETUSER agent-geo-agent/)).toBeTruthy();
    expect(screen.getByText(/~manus-agent:geo-agent:\*/)).toBeTruthy();

    await submit();
    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(1));
    expect(onCreate.mock.calls[0][0]).toMatchObject({ transport: "redis", url: null });
  });

  it("never previews a command built from an id that is still invalid", () => {
    setup();
    fireEvent.change(screen.getByLabelText("Transport"), { target: { value: "redis" } });
    type("Agent ID", "geo ~* +@all");
    const preview = document.querySelector("pre")?.textContent ?? "";
    expect(preview).toContain("agent-<agent_id> reset on");
    expect(preview).not.toContain("~*");
    expect(preview).not.toContain("+@all");
    type("Agent ID", "geo");
    expect(document.querySelector("pre")?.textContent).toContain("agent-geo reset on");
  });

  it("rejects an http agent without a valid http(s) URL", async () => {
    const { onCreate } = setup();
    fillHttp();
    for (const bad of ["", "geo-agent:8080", "ftp://x"]) {
      type("Agent URL", bad);
      await submit();
      await screen.findByText(/Enter an http\(s\) URL/);
    }
    expect(onCreate).not.toHaveBeenCalled();
  });

  it("requires a shared-secret credential", async () => {
    const { onCreate } = setup();
    fillHttp();
    type("Shared secret", "");
    await submit();
    await screen.findByText("Select a shared-secret credential");
    expect(onCreate).not.toHaveBeenCalled();
  });

  it("refuses an id that is already in use", async () => {
    const { onCreate } = setup({ existingSourceIds: ["geo"] });
    fillHttp();
    await submit();
    await screen.findByText("This source ID is already in use");
    expect(onCreate).not.toHaveBeenCalled();
  });

  it("validates the id formats", async () => {
    const { onCreate } = setup();
    fillHttp();
    type("Source ID", "Bad Id");
    type("Agent ID", "has space");
    await submit();
    expect(await screen.findAllByText(/Use lowercase letters/)).toHaveLength(2);
    expect(onCreate).not.toHaveBeenCalled();
  });

  it("does not submit out-of-range limits (native min/max) and flags a blank one", async () => {
    const { onCreate } = setup();
    fillHttp();
    for (const bad of ["0", "65"]) {
      type("Parallel calls", bad);
      await submit();
    }
    expect(onCreate).not.toHaveBeenCalled();

    type("Parallel calls", "");
    await submit();
    await screen.findByText("1 to 64");
    expect(onCreate).not.toHaveBeenCalled();
  });

  it("has no test button before the source exists", () => {
    setup();
    expect(screen.queryByRole("button", { name: "Test connection" })).toBeNull();
  });
});

describe("AgentSourceDialog edit", () => {
  const initial: AgentSourceEditValue = {
    sourceId: "geo",
    transport: "http",
    agentId: "geo-agent",
    url: "http://geo-agent:8080",
    credentialId: 7,
    maxConcurrency: 2,
    maxRequestBytes: 2048,
    maxTimeoutSeconds: 15,
  };

  it("prefills the form, locks the id and shows the agent status", () => {
    setup({ mode: "edit", initialValue: initial });
    expect((screen.getByLabelText("Source ID") as HTMLInputElement).value).toBe("geo");
    expect((screen.getByLabelText("Source ID") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText("Max request (KiB)") as HTMLInputElement).value).toBe("2");
    expect(screen.getByText("status of geo")).toBeTruthy();
  });

  it("updates by id without sending the source id in the body", async () => {
    const { onUpdate } = setup({ mode: "edit", initialValue: initial });
    type("Parallel calls", "8");
    await submit();
    await waitFor(() => expect(onUpdate).toHaveBeenCalledTimes(1));
    expect(onUpdate).toHaveBeenCalledWith("geo", {
      transport: "http",
      agent_id: "geo-agent",
      url: "http://geo-agent:8080",
      credential_id: 7,
      max_concurrency: 8,
      max_request_bytes: 2048,
      max_timeout_seconds: 15,
    });
  });

  it("tests the saved source", () => {
    setup({ mode: "edit", initialValue: initial });
    fireEvent.click(screen.getByRole("button", { name: "Test connection" }));
    expect(h.testMutate).toHaveBeenCalledWith({ source_id: "geo" });
  });

  it("does not offer the test while one is running", () => {
    h.testPending.value = true;
    setup({ mode: "edit", initialValue: initial });
    expect((screen.getByRole("button", { name: "Testing…" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
