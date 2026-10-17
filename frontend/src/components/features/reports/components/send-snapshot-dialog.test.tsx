import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SendSnapshotDialog } from "./send-snapshot-dialog";

const mutate = vi.fn();
vi.mock("@/hooks/queries/use-report-snapshot-send-mutation", () => ({
  useReportSnapshotSendMutation: () => ({
    mutate,
    isPending: false,
    isError: false,
    error: null,
    reset: vi.fn(),
  }),
}));

afterEach(() => {
  cleanup();
  mutate.mockReset();
});

function setup(defaults: string[] = ["ops@example.org", "dev@example.org"]) {
  const onOpenChange = vi.fn();
  render(
    <SendSnapshotDialog
      open
      onOpenChange={onOpenChange}
      snapshotId={7}
      snapshotName="Fleet - now"
      defaultRecipients={defaults}
    />,
  );
  return { onOpenChange };
}

describe("SendSnapshotDialog", () => {
  it("proposes the report's recipients and sends them with the options", () => {
    setup();
    expect((screen.getByLabelText("Recipients") as HTMLTextAreaElement).value).toBe(
      "ops@example.org\ndev@example.org",
    );

    fireEvent.change(screen.getByLabelText(/subject/i), { target: { value: " Weekly " } });
    fireEvent.click(screen.getByLabelText(/attach the report as pdf/i));
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));

    expect(mutate).toHaveBeenCalledOnce();
    expect(mutate.mock.calls[0][0]).toEqual({
      snapshotId: 7,
      input: {
        to: ["ops@example.org", "dev@example.org"],
        subject: "Weekly",
        message: null,
        include_pdf: false,
      },
    });
  });

  it("will not send without recipients or with a bad address", () => {
    setup([]);
    const send = screen.getByRole("button", { name: /^send$/i }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("Recipients"), {
      target: { value: "ok@example.org, nope" },
    });

    expect(screen.getByText(/not an email address: nope/i)).toBeTruthy();
    expect(send.disabled).toBe(true);
    expect(mutate).not.toHaveBeenCalled();
  });
});
