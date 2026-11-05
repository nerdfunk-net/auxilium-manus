import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DeviceCommandProposal,
  DeviceCommandResult,
} from "../types/ai-assistant";

const mutateAsync = vi.fn();
const mutationState = { isPending: false };
vi.mock("../hooks/use-device-command", () => ({
  useDeviceCommandMutation: () => ({ mutateAsync, ...mutationState }),
}));

const downloadMutate = vi.fn();
const downloadState = { isPending: false, error: null as Error | null };
vi.mock("../hooks/use-parsed-rows-download", () => ({
  useParsedRowsDownload: () => ({ mutate: downloadMutate, ...downloadState }),
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

import { DeviceCommandProposalCard } from "./device-command-proposal-card";

const NOW = 1_800_000_000;

function proposal(
  overrides: Partial<DeviceCommandProposal> = {},
): DeviceCommandProposal {
  return {
    kind: "device_command",
    summary: "show running-config on LAB",
    token: "signed.token",
    expiresAt: NOW + 600,
    device: {
      id: "dev-1",
      name: "LAB",
      host: "10.1.2.3",
      platform: "cisco_ios",
    },
    commands: ["show running-config"],
    parser: "none",
    driverKnown: true,
    driverChoices: ["cisco_ios", "cisco_xe"],
    state: "pending",
    ...overrides,
  };
}

function result(
  overrides: Partial<DeviceCommandResult> = {},
): DeviceCommandResult {
  return {
    success: true,
    error: null,
    deviceName: "LAB",
    commands: ["show running-config"],
    output: "$ show running-config\nhostname LAB",
    truncated: false,
    handle: "res_0123456789ab",
    parser: "none",
    parsedHandle: null,
    parsedText: "",
    parseErrors: [],
    ...overrides,
  };
}

function renderCard(p: DeviceCommandProposal) {
  const onResult = vi.fn();
  const onReject = vi.fn();
  render(
    <DeviceCommandProposalCard
      proposal={p}
      onResult={onResult}
      onReject={onReject}
    />,
  );
  return { onResult, onReject };
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW * 1000);
  mutateAsync.mockReset();
  downloadMutate.mockReset();
  downloadState.isPending = false;
  downloadState.error = null;
  mutationState.isPending = false;
  credentials.data = {
    credentials: [
      {
        id: 11,
        name: "lab-ssh",
        username: "admin",
        type: "ssh",
        visibility: "private",
      },
      {
        id: 12,
        name: "api-token",
        username: "svc",
        type: "token",
        visibility: "global",
      },
      {
        id: 13,
        name: "key",
        username: "k",
        type: "ssh_key",
        visibility: "global",
      },
    ],
  };
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("DeviceCommandProposalCard", () => {
  it("shows the device, its address and the exact commands as plain text", () => {
    renderCard(
      proposal({
        commands: ["show running-config", "show version | include uptime"],
      }),
    );

    expect(screen.getByText("LAB")).toBeTruthy();
    expect(screen.getByText("10.1.2.3")).toBeTruthy();
    expect(screen.getByTestId("device-command-list").textContent).toBe(
      "$ show running-config\n$ show version | include uptime",
    );
  });

  it("does not interpret the commands as markup", () => {
    renderCard(proposal({ commands: ["show <b>x</b>"] }));

    expect(screen.getByTestId("device-command-list").textContent).toContain(
      "<b>x</b>",
    );
    expect(document.querySelector("b")).toBeNull();
  });

  it("offers only SSH logins and keeps Run disabled until one is chosen", () => {
    renderCard(proposal());

    const options = Array.from(
      screen.getByLabelText("SSH login").querySelectorAll("option"),
    ).map((o) => o.textContent);
    expect(options.join("|")).toContain("lab-ssh");
    expect(options.join("|")).not.toContain("api-token");
    expect(options.join("|")).not.toContain("key (k)");
    expect(
      (screen.getByRole("button", { name: /run/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);

    fireEvent.change(screen.getByLabelText("SSH login"), {
      target: { value: "11" },
    });

    expect(
      (screen.getByRole("button", { name: /run/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it("runs with the token and the chosen credential and reports the result", async () => {
    mutateAsync.mockResolvedValue(result());
    const { onResult } = renderCard(proposal());

    fireEvent.change(screen.getByLabelText("SSH login"), {
      target: { value: "11" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run/i }));

    await waitFor(() => expect(onResult).toHaveBeenCalledWith(result()));
    expect(mutateAsync).toHaveBeenCalledWith({
      token: "signed.token",
      credentialId: 11,
    });
  });

  it("shows the server's message when the run is refused", async () => {
    mutateAsync.mockRejectedValue(
      new Error("This confirmation expired or is not valid."),
    );
    const { onResult } = renderCard(proposal());

    fireEvent.change(screen.getByLabelText("SSH login"), {
      target: { value: "11" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run/i }));

    expect(await screen.findByText(/expired or is not valid/)).toBeTruthy();
    expect(onResult).not.toHaveBeenCalled();
  });

  it("refuses to run an expired proposal and says to ask again", () => {
    renderCard(proposal({ expiresAt: NOW - 1 }));
    fireEvent.change(screen.getByLabelText("SSH login"), {
      target: { value: "11" },
    });

    expect(screen.getByText(/expired/i)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: /run/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("checks the expiry again at the click, not only when it was drawn", () => {
    renderCard(proposal());
    fireEvent.change(screen.getByLabelText("SSH login"), {
      target: { value: "11" },
    });
    vi.setSystemTime((NOW + 601) * 1000);

    fireEvent.click(screen.getByRole("button", { name: /run/i }));

    expect(screen.getByText(/expired/i)).toBeTruthy();
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("keeps Run disabled while the assistant is still answering, and says why", () => {
    render(
      <DeviceCommandProposalCard
        proposal={proposal()}
        onResult={vi.fn()}
        onReject={vi.fn()}
        busy
      />,
    );
    fireEvent.change(screen.getByLabelText("SSH login"), {
      target: { value: "11" },
    });

    expect(
      (screen.getByRole("button", { name: /run/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.getByText(/finished answering/i)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: /reject/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it("rejects without running anything", () => {
    const { onReject } = renderCard(proposal());

    fireEvent.click(screen.getByRole("button", { name: /reject/i }));

    expect(onReject).toHaveBeenCalled();
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("shows the output of a finished run and no buttons", () => {
    renderCard(
      proposal({ state: "applied", result: result({ truncated: true }) }),
    );

    expect(screen.getByTestId("device-command-output").textContent).toContain(
      "hostname LAB",
    );
    expect(screen.getByText(/cut/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /run/i })).toBeNull();
  });

  it("says which parser will run, and warns that Genie sends the output out", () => {
    renderCard(proposal({ parser: "textfsm" }));
    expect(screen.getByTestId("device-command-parser").textContent).toContain(
      "TextFSM",
    );
    cleanup();

    renderCard(proposal({ parser: "genie" }));
    expect(screen.getByTestId("device-command-parser").textContent).toContain(
      "pyATS",
    );
  });

  it("shows no parser line when there is no parser", () => {
    renderCard(proposal());

    expect(screen.queryByTestId("device-command-parser")).toBeNull();
  });

  it("shows the parsed data and the commands that did not parse", () => {
    renderCard(
      proposal({
        parser: "textfsm",
        state: "applied",
        result: result({
          parser: "textfsm",
          parsedHandle: "res_aaaaaaaaaaaa",
          parsedText: '[{"command": "show version"}]',
          parseErrors: [{ command: "show clock", error: "No template" }],
        }),
      }),
    );

    expect(screen.getByTestId("device-command-parsed").textContent).toContain(
      "show version",
    );
    expect(
      screen.getByTestId("device-command-parse-errors").textContent,
    ).toContain("show clock — No template");
  });

  describe("parsed rows as a table", () => {
    const CDP_TEXT = JSON.stringify([
      {
        command: "show cdp neighbors detail",
        error: null,
        parsed: [
          {
            neighbor_name: "sw2.example.com",
            local_interface: "Gi1/0/1",
            neighbor_interface: "Gi0/24",
            mgmt_address: "192.0.2.2",
          },
          {
            neighbor_name: "<b>r2</b>",
            local_interface: "Gi1/0/2",
            neighbor_interface: "Gi0/0/1",
            mgmt_address: "10.9.9.2",
          },
        ],
      },
    ]);
    const withText = (parsedText: string) =>
      proposal({
        parser: "textfsm",
        state: "applied",
        result: result({
          parser: "textfsm",
          output: "$ show cdp neighbors detail\nDevice ID: sw2",
          parsedHandle: "res_aaaaaaaaaaaa",
          parsedText,
        }),
      });

    it("shows a table with headers and one row per neighbour", () => {
      renderCard(withText(CDP_TEXT));

      const tables = screen.getByTestId("device-command-tables");
      expect(
        within(tables)
          .getAllByRole("columnheader")
          .map((h) => h.textContent),
      ).toEqual([
        "Local interface",
        "Neighbor",
        "Neighbor interface",
        "Management IP",
      ]);
      expect(within(tables).getAllByRole("row")).toHaveLength(3);
      expect(within(tables).getByText("sw2.example.com")).toBeTruthy();
      expect(within(tables).getByText("2 rows")).toBeTruthy();
    });

    it("shows device text as text, never as markup", () => {
      renderCard(withText(CDP_TEXT));

      const tables = screen.getByTestId("device-command-tables");
      expect(within(tables).getByText("<b>r2</b>")).toBeTruthy();
      expect(tables.querySelector("b")).toBeNull();
    });

    it("keeps the raw output and the JSON, collapsed, under the table", () => {
      renderCard(withText(CDP_TEXT));

      expect(
        screen.getByTestId("device-command-output").closest("details")?.open,
      ).toBe(false);
      expect(screen.getByTestId("device-command-parsed").textContent).toContain(
        "sw2.example.com",
      );
    });

    it("says so when the cut CLI output makes the table a prefix", () => {
      renderCard({
        ...withText(CDP_TEXT),
        result: result({
          parser: "textfsm",
          parsedHandle: "res_aaaaaaaaaaaa",
          parsedText: CDP_TEXT,
          truncated: true,
        }),
      });

      expect(
        screen.getByTestId("device-command-tables-incomplete").textContent,
      ).toMatch(/may be incomplete/i);
    });

    it("has no incomplete notice when the output was not cut", () => {
      renderCard(withText(CDP_TEXT));

      expect(
        screen.queryByTestId("device-command-tables-incomplete"),
      ).toBeNull();
    });

    it("explains why there is no table when the parsed data was cut", () => {
      const cut =
        '[{"command": "x", "parsed": [{"a": "1"},\n…[cut: showed 100000 of 250000 characters; the rest is in the handle]';
      renderCard(withText(cut));

      expect(screen.queryByTestId("device-command-tables")).toBeNull();
      expect(
        screen.getByTestId("device-command-parsed-cut").textContent,
      ).toMatch(/too long to show as a table/i);
      expect(screen.getByTestId("device-command-download")).toBeTruthy();
    });

    it("gives no cut notice when there is simply nothing to tabulate", () => {
      renderCard(
        withText('[{"command": "show version", "parsed": {"version": {}}}]'),
      );

      expect(screen.queryByTestId("device-command-parsed-cut")).toBeNull();
    });

    it("shows only the raw output and the JSON when nothing can be a table", () => {
      renderCard(
        withText('[{"command": "show version", "parsed": {"version": {}}}]'),
      );

      expect(screen.queryByTestId("device-command-tables")).toBeNull();
      expect(
        screen.getByTestId("device-command-output").closest("details"),
      ).toBeNull();
      expect(screen.getByTestId("device-command-parsed")).toBeTruthy();
    });
  });

  describe("downloading the parsed data", () => {
    const parsed = () =>
      proposal({
        parser: "textfsm",
        state: "applied",
        result: result({
          parser: "textfsm",
          parsedHandle: "res_aaaaaaaaaaaa",
          parsedText: "[]",
        }),
      });

    it("downloads the full data as JSON or CSV by its handle", () => {
      renderCard(parsed());

      fireEvent.click(screen.getByRole("button", { name: /download json/i }));
      fireEvent.click(screen.getByRole("button", { name: /download csv/i }));

      expect(downloadMutate).toHaveBeenNthCalledWith(1, {
        handle: "res_aaaaaaaaaaaa",
        format: "json",
        deviceName: "LAB",
      });
      expect(downloadMutate).toHaveBeenNthCalledWith(2, {
        handle: "res_aaaaaaaaaaaa",
        format: "csv",
        deviceName: "LAB",
      });
    });

    it("says the data is only kept for a few hours", () => {
      renderCard(parsed());

      expect(screen.getByTestId("device-command-download").textContent).toMatch(
        /few hours/i,
      );
    });

    it("offers no download when nothing was stored", () => {
      renderCard(
        proposal({
          parser: "textfsm",
          state: "applied",
          result: result({ parser: "textfsm", parsedHandle: null }),
        }),
      );

      expect(screen.queryByTestId("device-command-download")).toBeNull();
    });

    it("shows why a download failed and disables the buttons while it runs", () => {
      downloadState.error = new Error("Unknown or expired result");
      downloadState.isPending = true;
      renderCard(parsed());

      expect(screen.getByText("Unknown or expired result")).toBeTruthy();
      expect(
        (
          screen.getByRole("button", {
            name: /download json/i,
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(true);
    });
  });

  it("shows a failed run's error and any partial output", () => {
    renderCard(
      proposal({
        state: "applied",
        result: result({
          success: false,
          error: "Connection timed out",
          handle: null,
        }),
      }),
    );

    expect(screen.getByText("Connection timed out")).toBeTruthy();
  });

  it("says a rejected proposal was not run", () => {
    renderCard(proposal({ state: "rejected" }));

    expect(screen.getByText(/rejected/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /run/i })).toBeNull();
  });

  it("disables the buttons while a run is in progress", () => {
    mutationState.isPending = true;
    const { rerender } = render(
      <DeviceCommandProposalCard
        proposal={proposal()}
        onResult={vi.fn()}
        onReject={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("SSH login"), {
      target: { value: "11" },
    });
    rerender(
      <DeviceCommandProposalCard
        proposal={proposal()}
        onResult={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    expect(
      (screen.getByRole("button", { name: /running/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: /reject/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  describe("when the inventory names no known device type", () => {
    const unknown = () =>
      proposal({
        driverKnown: false,
        device: { id: "dev-1", name: "LAB", host: "10.1.2.3", platform: null },
      });

    it("does not ask for a device type when the driver is known", () => {
      renderCard(proposal());

      expect(screen.queryByLabelText("Device type")).toBeNull();
    });

    it("asks for one, and keeps Run disabled until both choices are made", () => {
      renderCard(unknown());

      expect(screen.getByText(/does not say which device type/i)).toBeTruthy();
      fireEvent.change(screen.getByLabelText("SSH login"), {
        target: { value: "11" },
      });
      expect(
        (screen.getByRole("button", { name: /run/i }) as HTMLButtonElement)
          .disabled,
      ).toBe(true);

      fireEvent.change(screen.getByLabelText("Device type"), {
        target: { value: "cisco_xe" },
      });
      expect(
        (screen.getByRole("button", { name: /run/i }) as HTMLButtonElement)
          .disabled,
      ).toBe(false);
    });

    it("offers exactly the server's list and sends the choice with the run", async () => {
      mutateAsync.mockResolvedValue(result());
      renderCard(unknown());

      const options = Array.from(
        screen.getByLabelText("Device type").querySelectorAll("option"),
      ).map((o) => o.getAttribute("value"));
      expect(options).toEqual(["", "cisco_ios", "cisco_xe"]);

      fireEvent.change(screen.getByLabelText("SSH login"), {
        target: { value: "11" },
      });
      fireEvent.change(screen.getByLabelText("Device type"), {
        target: { value: "cisco_xe" },
      });
      fireEvent.click(screen.getByRole("button", { name: /run/i }));

      await waitFor(() =>
        expect(mutateAsync).toHaveBeenCalledWith({
          token: "signed.token",
          credentialId: 11,
          networkDriver: "cisco_xe",
        }),
      );
    });

    it("shows the platform the inventory has, when there is one", () => {
      renderCard(
        proposal({
          driverKnown: false,
          device: {
            id: "d",
            name: "LAB",
            host: "10.1.2.3",
            platform: "Plan 9",
          },
        }),
      );

      expect(screen.getByText(/Plan 9/)).toBeTruthy();
    });
  });
});
