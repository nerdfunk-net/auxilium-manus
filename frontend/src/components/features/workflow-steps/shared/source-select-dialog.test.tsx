import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SourceSelectDialog } from "./source-select-dialog";

const h = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("@/components/ui/select", () => import("@/test/native-select-mock"));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: h.push }) }));

const SOURCES = [
  { id: "lab", detail: "https://lab.example" },
  { id: "prod", detail: "https://prod.example" },
];

type Props = React.ComponentProps<typeof SourceSelectDialog>;

function setup(props: Partial<Props> = {}) {
  const handlers = { onClose: vi.fn(), onSave: vi.fn() };
  const base: Props = {
    open: true,
    selectedSourceId: "",
    title: "Demo source",
    description: "Pick the demo source.",
    sourceLabel: "Demo",
    idPrefix: "demo",
    sources: SOURCES,
    isLoading: false,
    ...handlers,
  };
  const view = render(<SourceSelectDialog {...base} {...props} />);
  return { ...handlers, view, base };
}

beforeEach(() => h.push.mockReset());

describe("SourceSelectDialog", () => {
  it("shows the title and description", () => {
    setup();
    expect(screen.getByText("Demo source")).toBeTruthy();
    expect(screen.getByText("Pick the demo source.")).toBeTruthy();
  });

  it("lists every source with its detail", () => {
    setup();
    expect(screen.getByRole("option", { name: /lab/ }).textContent).toContain("https://lab.example");
    expect(screen.getByRole("option", { name: /prod/ }).textContent).toContain("https://prod.example");
  });

  it("names the integration in the placeholder and gives the select its id", () => {
    setup();
    expect(screen.getByRole("option", { name: "Select a Demo source" })).toBeTruthy();
    expect(screen.getByLabelText("Source ID").id).toBe("demo-source-select");
  });

  it("saves only the chosen id and closes", () => {
    const { onSave, onClose } = setup();
    fireEvent.change(screen.getByLabelText("Source ID"), { target: { value: "prod" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).toHaveBeenCalledWith("prod");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("starts from the selected id", () => {
    setup({ selectedSourceId: "lab" });
    expect((screen.getByLabelText("Source ID") as HTMLSelectElement).value).toBe("lab");
  });

  it("cannot save before a source is chosen", () => {
    const { onSave } = setup();
    const save = screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.click(save);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("shows the loading state and no select", () => {
    setup({ isLoading: true, sources: [] });
    expect(screen.getByText("Loading sources…")).toBeTruthy();
    expect(screen.queryByLabelText("Source ID")).toBeNull();
  });

  it("points to Settings when there is no source, and cannot save", () => {
    const { onClose } = setup({ sources: [], selectedSourceId: "lab" });
    expect(screen.getByText("No Demo sources configured yet.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open Settings → Sources" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(h.push).toHaveBeenCalledWith("/settings/sources");
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("closes through Cancel without saving", () => {
    const { onClose, onSave } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("renders the hint for the current choice", () => {
    setup({ renderHint: (id) => <p>hint:{id || "none"}</p> });
    expect(screen.getByText("hint:none")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Source ID"), { target: { value: "lab" } });
    expect(screen.getByText("hint:lab")).toBeTruthy();
  });

  it("resets the choice to the selected id when it is reopened", () => {
    const { view, base } = setup({ selectedSourceId: "lab" });
    fireEvent.change(screen.getByLabelText("Source ID"), { target: { value: "prod" } });
    view.rerender(<SourceSelectDialog {...base} selectedSourceId="lab" open={false} />);
    view.rerender(<SourceSelectDialog {...base} selectedSourceId="lab" open />);
    expect((screen.getByLabelText("Source ID") as HTMLSelectElement).value).toBe("lab");
  });
});
