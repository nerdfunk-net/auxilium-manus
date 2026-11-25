import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CheckboxField } from "./checkbox-field";

describe("CheckboxField", () => {
  it("shows the key label, the description and the checked state", () => {
    render(
      <CheckboxField id="c1" label="overwrite_existing" checked description="Replace it." onCheckedChange={vi.fn()} />,
    );
    const box = screen.getByRole("checkbox", { name: "overwrite_existing" });
    expect(box.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText("Replace it.")).toBeTruthy();
  });

  it("omits the description paragraph when none is given", () => {
    const { container } = render(
      <CheckboxField id="c2" label="k" checked={false} onCheckedChange={vi.fn()} />,
    );
    expect(container.querySelector("p")).toBeNull();
  });

  it("reports a real boolean on click", () => {
    const onChange = vi.fn();
    render(<CheckboxField id="c3" label="k" checked={false} onCheckedChange={onChange} />);
    fireEvent.click(screen.getByRole("checkbox", { name: "k" }));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("is reachable through its label", () => {
    const onChange = vi.fn();
    render(<CheckboxField id="c4" label="k" checked={false} onCheckedChange={onChange} />);
    fireEvent.click(screen.getByText("k"));
    expect(onChange).toHaveBeenCalledWith(true);
  });
});
