import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BatfishManageDialog } from "./batfish-manage-dialog";

const h = vi.hoisted(() => ({
  permissions: [] as string[],
  deleteNetwork: vi.fn(),
  deleteSnapshots: vi.fn(),
}));

vi.mock("@/lib/auth-store", () => ({
  useAuthStore: (select: (s: { user: { permissions: string[] } }) => unknown) =>
    select({ user: { permissions: h.permissions } }),
}));
vi.mock("@/hooks/queries/use-batfish-network-summaries-query", () => ({
  useBatfishNetworkSummariesQuery: () => ({
    isLoading: false,
    isError: false,
    data: {
      networks: [
        {
          name: "net-a",
          snapshot_count: 2,
          unavailable: false,
          latest_snapshot_at: "2026-11-01T10:00:00Z",
        },
        {
          name: "net-b",
          snapshot_count: 0,
          unavailable: false,
          latest_snapshot_at: null,
        },
      ],
    },
  }),
}));
vi.mock("@/hooks/queries/use-batfish-snapshots-query", () => ({
  useBatfishSnapshotsQuery: () => ({
    isLoading: false,
    data: {
      snapshots: [
        { name: "snap-new", created_at: null },
        { name: "snap-old", created_at: null },
      ],
    },
  }),
}));
vi.mock("@/hooks/queries/use-batfish-snapshot-devices-query", () => ({
  useBatfishSnapshotDevicesQuery: () => ({
    isLoading: false,
    isError: false,
    data: {
      snapshot: "snap-new",
      devices: [{ device: "r1", ip_addresses: ["10.0.0.1", "10.0.1.1"] }],
      ips_unavailable: false,
      truncated: false,
    },
  }),
}));
vi.mock("@/hooks/queries/use-batfish-sources-mutations", () => ({
  useBatfishSourcesMutations: () => ({
    deleteNetwork: { mutateAsync: h.deleteNetwork, isPending: false },
    deleteSnapshots: { mutate: h.deleteSnapshots, isPending: false },
  }),
}));

function setup() {
  const onClose = vi.fn();
  render(<BatfishManageDialog sourceId="lab" onClose={onClose} />);
  return onClose;
}

describe("BatfishManageDialog", () => {
  beforeEach(() => {
    h.permissions = ["sources.batfish:write", "sources.batfish:query"];
    h.deleteNetwork.mockReset();
    h.deleteNetwork.mockResolvedValue(undefined);
    h.deleteSnapshots.mockReset();
  });

  it("lists networks with snapshot counts", () => {
    setup();
    const row = screen.getByText("net-a").closest("tr")!;
    expect(within(row).getByText("2")).toBeTruthy();
    expect(screen.getByText("net-b")).toBeTruthy();
  });

  it("shows the date of the newest snapshot beside the network name", () => {
    setup();
    const rowA = screen.getByText("net-a").closest("tr")!;
    expect(
      within(rowA).getByText(new Date("2026-11-01T10:00:00Z").toLocaleString()),
    ).toBeTruthy();
    const rowB = screen.getByText("net-b").closest("tr")!;
    expect(within(rowB).getByText("—")).toBeTruthy();
  });

  it("removes a network only after confirmation", async () => {
    setup();
    const row = screen.getByText("net-a").closest("tr")!;
    fireEvent.click(
      within(row).getByRole("button", { name: /Remove network net-a/ }),
    );
    expect(h.deleteNetwork).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() =>
      expect(h.deleteNetwork.mock.calls[0][0]).toEqual({
        sourceId: "lab",
        network: "net-a",
      }),
    );
  });

  it("starts only one delete loop when Remove is clicked twice", async () => {
    let release: () => void = () => undefined;
    h.deleteNetwork.mockImplementation(
      () => new Promise<void>((resolve) => (release = resolve)),
    );
    setup();
    const row = screen.getByText("net-a").closest("tr")!;
    fireEvent.click(
      within(row).getByRole("button", { name: /Remove network net-a/ }),
    );
    const dialog = screen.getByRole("dialog", { name: "Remove network?" });
    const confirm = within(dialog).getByRole("button", { name: "Remove" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await waitFor(() => expect(h.deleteNetwork).toHaveBeenCalledTimes(1));
    release();
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Remove network?" }),
      ).toBeNull(),
    );
    expect(h.deleteNetwork).toHaveBeenCalledTimes(1);
  });

  it("removes several selected networks with the button below the table", async () => {
    setup();
    const remove = screen.getByRole("button", { name: "Remove" });
    expect((remove as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByLabelText("Select net-a"));
    fireEvent.click(screen.getByLabelText("Select net-b"));
    fireEvent.click(screen.getByRole("button", { name: "Remove (2)" }));
    fireEvent.click(
      within(
        screen.getByRole("dialog", { name: "Remove networks?" }),
      ).getByRole("button", {
        name: "Remove",
      }),
    );
    await waitFor(() => expect(h.deleteNetwork).toHaveBeenCalledTimes(2));
    expect(h.deleteNetwork.mock.calls.map((c) => c[0].network)).toEqual([
      "net-a",
      "net-b",
    ]);
  });

  it("removes the selected snapshots (date in braces after the name)", () => {
    setup();
    const row = screen.getByText("net-a").closest("tr")!;
    fireEvent.click(
      within(row).getByRole("button", { name: /Remove snapshots of net-a/ }),
    );
    expect(screen.getByText("snap-new (unknown date)")).toBeTruthy();

    const remove = screen.getByRole("button", { name: /^Remove/ });
    expect((remove as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByLabelText("snap-old (unknown date)"));
    fireEvent.click(screen.getByRole("button", { name: "Remove (1)" }));
    fireEvent.click(
      within(
        screen.getByRole("dialog", { name: "Remove snapshots?" }),
      ).getByRole("button", {
        name: "Remove",
      }),
    );
    expect(h.deleteSnapshots.mock.calls[0][0]).toEqual({
      sourceId: "lab",
      network: "net-a",
      snapshots: ["snap-old"],
    });
  });

  it("disables the remove actions without sources.batfish:write", () => {
    h.permissions = ["sources.batfish:read"];
    setup();
    const row = screen.getByText("net-a").closest("tr")!;
    expect(
      (
        within(row).getByRole("button", {
          name: /Remove network net-a/,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      (
        within(row).getByRole("button", {
          name: /Remove snapshots of net-a/,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });

  it("shows the devices of the newest snapshot in the network view", () => {
    setup();
    const row = screen.getByText("net-a").closest("tr")!;
    fireEvent.click(
      within(row).getByRole("button", { name: /Show network net-a/ }),
    );
    expect(screen.getByText("snap-new (unknown date)")).toBeTruthy();
    expect(screen.getByText("r1")).toBeTruthy();
    expect(screen.getByText("10.0.0.1, 10.0.1.1")).toBeTruthy();
  });
});
