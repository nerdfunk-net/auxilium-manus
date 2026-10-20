import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NautobotSourceSelectDialog } from "./nautobot-source-select-dialog";

const h = vi.hoisted(() => ({
  query: vi.fn(),
  data: { value: undefined as unknown },
  isLoading: { value: false },
  push: vi.fn(),
}));

vi.mock("@/components/ui/select", () => import("@/test/native-select-mock"));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: h.push }) }));
vi.mock("@/hooks/queries/use-nautobot-configured-sources-query", () => ({
  useNautobotConfiguredSourcesQuery: (options: unknown) => {
    h.query(options);
    return { data: h.data.value, isLoading: h.isLoading.value };
  },
}));

const SOURCES = [
  { source_id: "lab", url: "https://lab.example", token_configured: true },
  { source_id: "dev", url: "https://dev.example", token_configured: true },
];

function setup(props: Partial<React.ComponentProps<typeof NautobotSourceSelectDialog>> = {}) {
  const handlers = { onClose: vi.fn(), onSave: vi.fn() };
  render(<NautobotSourceSelectDialog open selectedSourceId="" {...handlers} {...props} />);
  return handlers;
}

beforeEach(() => {
  h.query.mockReset();
  h.push.mockReset();
  h.data.value = SOURCES;
  h.isLoading.value = false;
});

describe("NautobotSourceSelectDialog", () => {
  it("reads the sources only while open, from the endpoint that needs sources.nautobot:read", () => {
    setup({ open: false });
    expect(h.query).toHaveBeenLastCalledWith({ enabled: false });
    setup();
    expect(h.query).toHaveBeenLastCalledWith({ enabled: true });
  });

  it("lists the sources with their URL", () => {
    setup();
    expect(screen.getByRole("option", { name: /lab/ }).textContent).toContain("https://lab.example");
    expect(screen.getByRole("option", { name: /dev/ })).toBeTruthy();
  });

  it("saves the chosen source and closes", () => {
    const { onSave, onClose } = setup();
    fireEvent.change(screen.getByLabelText("Source ID"), { target: { value: "dev" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).toHaveBeenCalledWith("dev");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("starts from the source the step already uses", () => {
    setup({ selectedSourceId: "lab" });
    expect((screen.getByLabelText("Source ID") as HTMLSelectElement).value).toBe("lab");
  });

  it("cannot save before a source is chosen", () => {
    setup();
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows the loading state", () => {
    h.isLoading.value = true;
    h.data.value = undefined;
    setup();
    expect(screen.getByText("Loading sources…")).toBeTruthy();
  });

  it("points to Settings when no source is configured", () => {
    h.data.value = [];
    const { onClose } = setup();
    expect(screen.getByText("No Nautobot sources configured yet.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open Settings → Sources" }));
    expect(onClose).toHaveBeenCalled();
    expect(h.push).toHaveBeenCalledWith("/settings/sources");
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("closes through Cancel without saving", () => {
    const { onClose, onSave } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
  });
});
