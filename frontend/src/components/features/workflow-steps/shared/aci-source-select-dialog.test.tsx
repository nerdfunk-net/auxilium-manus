import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AciSourceSelectDialog } from "./aci-source-select-dialog";

const h = vi.hoisted(() => ({
  data: { value: undefined as unknown },
  isLoading: { value: false },
  push: vi.fn(),
}));

vi.mock("@/components/ui/select", () => import("@/test/native-select-mock"));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: h.push }) }));
vi.mock("@/hooks/queries/use-aci-sources-query", () => ({
  useAciSourcesQuery: () => ({ data: h.data.value, isLoading: h.isLoading.value }),
}));

const SOURCES = {
  sources: [
    { source_id: "lab-aci", url: "https://apic-lab.example" },
    { source_id: "prod-aci", url: "https://apic-prod.example" },
  ],
  total: 2,
};

function setup(props: Partial<React.ComponentProps<typeof AciSourceSelectDialog>> = {}) {
  const handlers = { onClose: vi.fn(), onSave: vi.fn() };
  render(<AciSourceSelectDialog open selectedSourceId="" {...handlers} {...props} />);
  return handlers;
}

beforeEach(() => {
  h.push.mockReset();
  h.data.value = SOURCES;
  h.isLoading.value = false;
});

describe("AciSourceSelectDialog", () => {
  it("lists the configured Cisco ACI sources with their URL", () => {
    setup();
    expect(screen.getByRole("option", { name: /lab-aci/ }).textContent).toContain(
      "https://apic-lab.example",
    );
    expect(screen.getByRole("option", { name: /prod-aci/ })).toBeTruthy();
  });

  it("saves only the chosen source id and closes", () => {
    const { onSave, onClose } = setup();
    fireEvent.change(screen.getByLabelText("Source ID"), { target: { value: "prod-aci" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).toHaveBeenCalledWith("prod-aci");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("starts from the source the step already uses", () => {
    setup({ selectedSourceId: "lab-aci" });
    expect((screen.getByLabelText("Source ID") as HTMLSelectElement).value).toBe("lab-aci");
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

  it("points to Settings when no ACI source exists yet", () => {
    h.data.value = { sources: [], total: 0 };
    const { onClose } = setup();
    expect(screen.getByText("No Cisco ACI sources configured yet.")).toBeTruthy();
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
