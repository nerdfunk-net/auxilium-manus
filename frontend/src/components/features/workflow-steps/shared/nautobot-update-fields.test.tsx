import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DryRunSwitch,
  FromInterfacesSwitch,
  LocationsFields,
} from "./nautobot-update-fields";

vi.mock("./expression-field", () => ({
  ExpressionField: ({
    configKey,
    value,
    onValueChange,
    children,
  }: {
    configKey: string;
    value: string;
    onValueChange: (next: string) => void;
    children?: React.ReactNode;
  }) => (
    <div>
      <input aria-label={configKey} value={value} onChange={(e) => onValueChange(e.target.value)} />
      {children}
    </div>
  ),
}));
vi.mock("@/components/ui/select", () => import("@/test/native-select-mock"));

afterEach(cleanup);

describe("FromInterfacesSwitch", () => {
  it("shows label and description and reports the switch", () => {
    const onChange = vi.fn();
    render(
      <FromInterfacesSwitch
        label="VLANs from interfaces"
        description="Take the VLANs."
        ariaLabel="vlans_from_interfaces"
        checked={false}
        onCheckedChange={onChange}
      />,
    );
    expect(screen.getByText("VLANs from interfaces")).toBeTruthy();
    expect(screen.getByText("Take the VLANs.")).toBeTruthy();
    fireEvent.click(screen.getByRole("switch", { name: "vlans_from_interfaces" }));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("draws a top border only when asked", () => {
    const { container, rerender } = render(
      <FromInterfacesSwitch label="l" description="d" ariaLabel="a" checked onCheckedChange={vi.fn()} bordered />,
    );
    expect(container.firstElementChild?.className).toContain("border-t");
    rerender(<FromInterfacesSwitch label="l" description="d" ariaLabel="a" checked onCheckedChange={vi.fn()} />);
    expect(container.firstElementChild?.className).not.toContain("border-t");
  });
});

describe("DryRunSwitch", () => {
  it("shows the description and reports the switch", () => {
    const onChange = vi.fn();
    render(<DryRunSwitch description="Write nothing." checked onCheckedChange={onChange} />);
    expect(screen.getByText("Dry run")).toBeTruthy();
    expect(screen.getByText("Write nothing.")).toBeTruthy();
    const sw = screen.getByRole("switch", { name: "dry_run" });
    expect(sw.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(sw);
    expect(onChange).toHaveBeenCalledWith(false);
  });
});

function renderLocations(config: Record<string, unknown>, problems: string[] = []) {
  const patch = vi.fn();
  render(
    <LocationsFields
      config={config}
      patch={patch}
      problems={problems}
      noun="VLAN"
      nodeId="n1"
      workflowNodes={[]}
      workflowEdges={[]}
    />,
  );
  return patch;
}

describe("LocationsFields", () => {
  it("edits the list through patch", () => {
    const patch = renderLocations({ locations: "Berlin" });
    fireEvent.change(screen.getByLabelText("locations"), { target: { value: "Munich" } });
    expect(patch).toHaveBeenCalledWith("locations", "Munich");
  });

  it("edits the mode through patch and shows the stored mode", () => {
    const patch = renderLocations({ locations_mode: "add" });
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("add");
    fireEvent.change(select, { target: { value: "remove" } });
    expect(patch).toHaveBeenCalledWith("locations_mode", "remove");
  });

  it("names the object in the help text", () => {
    renderLocations({});
    expect(screen.getByText(/current locations/).textContent).toContain("VLAN's");
  });

  it("warns about an invalid stored mode instead of the help text", () => {
    renderLocations({ locations_mode: "merge" }, ["locations_mode is not valid"]);
    expect(screen.getByText(/not valid and the step would fail/)).toBeTruthy();
    expect(screen.queryByText(/current locations/)).toBeNull();
  });
});
