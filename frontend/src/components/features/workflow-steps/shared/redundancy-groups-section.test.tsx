import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RedundancyGroupsSection } from "./redundancy-groups-section";
import { DEFAULT_REDUNDANCY_GROUPS_CONFIG } from "./redundancy-groups";

vi.mock("@/components/ui/select", () => import("@/test/native-select-mock"));

const ON = { ...DEFAULT_REDUNDANCY_GROUPS_CONFIG, enabled: true };

describe("RedundancyGroupsSection", () => {
  it("shows only the switch while off", () => {
    render(<RedundancyGroupsSection value={DEFAULT_REDUNDANCY_GROUPS_CONFIG} onChange={vi.fn()} />);
    expect(screen.queryByLabelText("Name of a new group")).toBeNull();
    expect(screen.getByRole("switch", { name: /redundancy groups/i })).toBeTruthy();
  });

  it("turns on through the switch", () => {
    const onChange = vi.fn();
    render(<RedundancyGroupsSection value={DEFAULT_REDUNDANCY_GROUPS_CONFIG} onChange={onChange} />);
    fireEvent.click(screen.getByRole("switch", { name: /redundancy groups/i }));
    expect(onChange).toHaveBeenCalledWith({ ...DEFAULT_REDUNDANCY_GROUPS_CONFIG, enabled: true });
  });

  it("shows the name schema with examples and edits the pattern", () => {
    const onChange = vi.fn();
    render(<RedundancyGroupsSection value={ON} onChange={onChange} />);
    expect(screen.getByText("hsrp-1, hsrp-2, hsrp-3")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Name of a new group"), {
      target: { value: "grp-{next}" },
    });
    expect(onChange).toHaveBeenCalledWith({ ...ON, name_pattern: "grp-{next}" });
  });

  it("warns about a pattern without {next}", () => {
    render(<RedundancyGroupsSection value={{ ...ON, name_pattern: "hsrp" }} onChange={vi.fn()} />);
    expect(screen.getByText(/exactly once/)).toBeTruthy();
  });
});
