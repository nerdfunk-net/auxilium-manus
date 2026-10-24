import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AiProxySettingsCard } from "./ai-proxy-settings-card";

const h = vi.hoisted(() => ({
  data: undefined as unknown,
  mutate: vi.fn(),
}));

vi.mock("@/hooks/queries/use-ai-proxy-query", () => ({
  useAiProxyQuery: () => ({ data: h.data, isLoading: h.data === undefined }),
}));
vi.mock("@/hooks/queries/use-ai-proxy-mutations", () => ({
  useAiProxyMutations: () => ({ saveProxy: { mutate: h.mutate, isPending: false } }),
}));
// The picker has its own tests and needs the credentials query.
vi.mock("../credentials/components/credential-select", () => ({
  CredentialSelect: ({ onChange }: { onChange: (id: number | null) => void }) => (
    <button type="button" onClick={() => onChange(7)}>
      pick credential
    </button>
  ),
}));

const SETTINGS = {
  enabled: false,
  url: "",
  credential_id: null,
  credential_name: null,
  bypass_hosts: [] as string[],
  configured: false,
};

describe("AiProxySettingsCard", () => {
  beforeEach(() => {
    h.mutate.mockReset();
    h.data = { ...SETTINGS };
  });

  it("requires a URL while the proxy is enabled", async () => {
    render(<AiProxySettingsCard />);

    fireEvent.click(screen.getByRole("switch", { name: "Use a proxy" }));
    fireEvent.click(screen.getByRole("button", { name: "Save proxy" }));

    expect(await screen.findByText("A proxy URL is required")).toBeTruthy();
    expect(h.mutate).not.toHaveBeenCalled();
  });

  it("saves url, credential reference and parsed bypass hosts", async () => {
    render(<AiProxySettingsCard />);

    fireEvent.click(screen.getByRole("switch", { name: "Use a proxy" }));
    fireEvent.change(screen.getByLabelText("Proxy URL"), {
      target: { value: " http://proxy.corp:3128 " },
    });
    fireEvent.click(screen.getByRole("button", { name: "pick credential" }));
    fireEvent.change(screen.getByLabelText("Bypass hosts"), {
      target: { value: "ollama.corp, 10.0.0.0/8  localhost" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save proxy" }));

    await waitFor(() => expect(h.mutate).toHaveBeenCalledTimes(1));
    expect(h.mutate).toHaveBeenCalledWith({
      enabled: true,
      url: "http://proxy.corp:3128",
      credential_id: 7,
      bypass_hosts: ["ollama.corp", "10.0.0.0/8", "localhost"],
    });
  });

  it("shows stored values and can drop the login", async () => {
    h.data = {
      ...SETTINGS,
      enabled: true,
      url: "http://proxy.corp:3128",
      credential_id: 7,
      credential_name: "corp-proxy",
      bypass_hosts: ["a.corp"],
      configured: true,
    };
    render(<AiProxySettingsCard />);

    expect((screen.getByLabelText("Bypass hosts") as HTMLInputElement).value).toBe("a.corp");
    fireEvent.click(screen.getByRole("button", { name: "Remove login" }));
    fireEvent.click(screen.getByRole("button", { name: "Save proxy" }));

    await waitFor(() => expect(h.mutate).toHaveBeenCalled());
    expect(h.mutate.mock.calls[0][0]).toMatchObject({ credential_id: null });
  });
});
