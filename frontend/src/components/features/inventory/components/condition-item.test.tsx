import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ConditionItem } from "./condition-item";

const label = (field: string) => (field === "all_devices" ? "All Devices" : "Location");

describe("ConditionItem", () => {
  it("shows field, operator and value of a normal condition", () => {
    render(
      <ConditionItem
        getFieldLabel={label}
        item={{ id: "1", field: "location", operator: "not_equals", value: "City A" }}
        onRemove={vi.fn()}
      />,
    );
    expect(screen.getByText("Location")).toBeTruthy();
    expect(screen.getByText("not_equals")).toBeTruthy();
    expect(screen.getByText('"City A"')).toBeTruthy();
  });

  it("shows an all devices condition as its label only", () => {
    const onRemove = vi.fn();
    render(
      <ConditionItem
        getFieldLabel={label}
        item={{ id: "2", field: "all_devices", operator: "equals", value: "true" }}
        onRemove={onRemove}
      />,
    );
    expect(screen.getByText("All Devices")).toBeTruthy();
    expect(screen.queryByText("equals")).toBeNull();
    expect(screen.queryByText('"true"')).toBeNull();
    fireEvent.click(screen.getByTitle("Delete condition"));
    expect(onRemove).toHaveBeenCalledWith("2");
  });
});
