import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildMergeConfigConfig, MergeConfigPlugin } from "./index";

vi.mock("@/components/features/workflow-steps/shared/ssh-credential-field", () => ({
  SshCredentialField: () => null,
}));

describe("buildMergeConfigConfig", () => {
  it("defaults fail_on_cli_error to true", () => {
    expect(buildMergeConfigConfig({}).fail_on_cli_error).toBe(true);
  });

  it("keeps an explicit false and lets a patch override it", () => {
    expect(buildMergeConfigConfig({ fail_on_cli_error: false }).fail_on_cli_error).toBe(false);
    expect(
      buildMergeConfigConfig({ fail_on_cli_error: false }, { fail_on_cli_error: true })
        .fail_on_cli_error,
    ).toBe(true);
  });
});

describe("MergeConfigPlugin ConfigPanel", () => {
  it("writes fail_on_cli_error when the checkbox is toggled", () => {
    const onChange = vi.fn();
    const Panel = MergeConfigPlugin.ConfigPanel;
    render(
      <Panel
        config={{ source_filename: "flash:a.cfg" }}
        nodeId="self"
        onChange={onChange}
        onPreview={() => undefined}
      />,
    );

    const box = screen.getByRole("checkbox", { name: /fail_on_cli_error/ });
    expect(box.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(box);

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toMatchObject({
      source_filename: "flash:a.cfg",
      fail_on_cli_error: false,
    });
  });

  it("shows an explicit false as unchecked", () => {
    const Panel = MergeConfigPlugin.ConfigPanel;
    render(
      <Panel
        config={{ fail_on_cli_error: false }}
        nodeId="self"
        onChange={() => undefined}
        onPreview={() => undefined}
      />,
    );

    const box = screen.getByRole("checkbox", { name: /fail_on_cli_error/ });
    expect(box.getAttribute("aria-checked")).toBe("false");
  });
});
