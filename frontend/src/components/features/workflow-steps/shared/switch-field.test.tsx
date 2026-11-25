import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SwitchField } from "./switch-field";

describe("SwitchField", () => {
  it("shows the key label, the description and the state", () => {
    render(<SwitchField id="s1" label="commit" checked description="Commit it." onCheckedChange={vi.fn()} />);
    const sw = screen.getByRole("switch", { name: "commit" });
    expect(sw.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText("Commit it.")).toBeTruthy();
  });

  it("omits the description paragraph when none is given", () => {
    const { container } = render(<SwitchField id="s2" label="k" checked={false} onCheckedChange={vi.fn()} />);
    expect(container.querySelector("p")).toBeNull();
  });

  it("reports a boolean on click", () => {
    const onChange = vi.fn();
    render(<SwitchField id="s3" label="k" checked={false} onCheckedChange={onChange} />);
    fireEvent.click(screen.getByRole("switch", { name: "k" }));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("does not report a click while disabled", () => {
    const onChange = vi.fn();
    render(<SwitchField id="s4" label="k" checked={false} disabled onCheckedChange={onChange} />);
    fireEvent.click(screen.getByRole("switch", { name: "k" }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
