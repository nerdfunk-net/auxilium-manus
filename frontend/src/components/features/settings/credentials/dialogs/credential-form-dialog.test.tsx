import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CredentialFormDialog } from "./credential-form-dialog";

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = ResizeObserverStub;

const noop = () => undefined;

afterEach(cleanup);

async function fillLogin(password: string) {
  fireEvent.change(screen.getByLabelText("Credential ID"), { target: { value: "lab-switch" } });
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: "admin" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
}

describe("CredentialFormDialog password warning", () => {
  it("saves a password that meets the account rules without a warning", async () => {
    const onSubmit = vi.fn();
    render(<CredentialFormDialog open mode="create" onClose={noop} onSubmit={onSubmit} />);

    await fillLogin("correct-horse-battery");
    expect(screen.queryByRole("alert")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledOnce();
    });
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ type: "ssh", password: "correct-horse-battery" }),
    );
    expect(screen.queryByRole("button", { name: "Use it anyway" })).toBeNull();
  });

  it("warns on an insecure SSH password and saves it from Use it anyway", async () => {
    const onSubmit = vi.fn();
    render(<CredentialFormDialog open mode="create" onClose={noop} onSubmit={onSubmit} />);

    await fillLogin("cisco");
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(onSubmit).not.toHaveBeenCalled();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("This password is insecure");
    expect(alert.textContent).toContain("ISE");

    fireEvent.click(screen.getByRole("button", { name: "Use it anyway" }));
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledOnce();
    });
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ type: "ssh", username: "admin", password: "cisco" }),
    );
  });

  it("asks again when the password changes after it was accepted", async () => {
    const onSubmit = vi.fn();
    render(<CredentialFormDialog open mode="create" onClose={noop} onSubmit={onSubmit} />);

    await fillLogin("cisco");
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    fireEvent.click(await screen.findByRole("button", { name: "Use it anyway" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledOnce());

    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "lab" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await screen.findByRole("button", { name: "Use it anyway" });
    expect(onSubmit).toHaveBeenCalledOnce();
  });
});
