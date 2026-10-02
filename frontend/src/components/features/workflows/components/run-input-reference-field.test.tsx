import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RunInputReferenceField } from "./run-input-reference-field";

const inventories = [
  { id: 1, name: "City A Campus", scope: "global", is_active: true },
  { id: 2, name: "City B Campus", scope: "global", is_active: true },
  { id: 3, name: "City A Lab", scope: "private", is_active: true },
  { id: 4, name: "City A Retired", scope: "global", is_active: false },
];

vi.mock("@/hooks/queries/use-saved-inventories-query", () => ({
  useSavedInventoriesQuery: () => ({ data: inventories, isLoading: false, isError: false }),
}));

afterEach(cleanup);

describe("RunInputReferenceField", () => {
  it("filters inventories by the typed phrase and hides inactive ones", () => {
    render(<RunInputReferenceField value="" onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /select an inventory/i }));
    fireEvent.change(screen.getByPlaceholderText("Search inventories…"), {
      target: { value: "city a" },
    });

    expect(screen.getByText("City A Campus")).toBeTruthy();
    expect(screen.getByText("City A Lab (private)")).toBeTruthy();
    expect(screen.queryByText("City B Campus")).toBeNull();
    expect(screen.queryByText("City A Retired")).toBeNull();
  });

  it("emits the numeric inventory id on selection", () => {
    const onChange = vi.fn();
    render(<RunInputReferenceField value="" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /select an inventory/i }));
    fireEvent.click(screen.getByText("City B Campus"));

    expect(onChange).toHaveBeenCalledWith(2);
  });
});
