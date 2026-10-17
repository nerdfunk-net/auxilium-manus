import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DeleteCredentialDialog } from "./delete-credential-dialog";

const noop = () => undefined;

afterEach(cleanup);

describe("DeleteCredentialDialog", () => {
  it("offers a plain Delete when nothing is known to use the credential", () => {
    render(<DeleteCredentialDialog open credentialName="lab" onClose={noop} onConfirm={noop} />);

    expect(screen.getByRole("button", { name: "Delete" })).toBeDefined();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("lists what still uses it and changes the button to Delete anyway", () => {
    const onConfirm = vi.fn();
    render(
      <DeleteCredentialDialog
        open
        credentialName="lab"
        dependants={[
          { kind: "git_repository", id: 3, name: "configs" },
          { kind: "workflow", id: 8, name: "Backup" },
        ]}
        onClose={noop}
        onConfirm={onConfirm}
      />,
    );

    expect(screen.getByRole("alert").textContent).toContain("Still in use by 2 items");
    expect(screen.getByText("configs")).toBeDefined();
    expect(screen.getByText("Git repository")).toBeDefined();
    expect(screen.getByText("Backup")).toBeDefined();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Delete anyway" }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});
