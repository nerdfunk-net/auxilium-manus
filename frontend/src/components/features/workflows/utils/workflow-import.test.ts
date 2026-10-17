import { describe, expect, it } from "vitest";

import { dropLegacySendMailSettings } from "./workflow-import";

describe("dropLegacySendMailSettings", () => {
  it("drops legacy send-mail settings", () => {
    const nodes = [
      {
        id: "n1",
        data: {
          kind: "send-mail",
          pluginConfig: {
            to: "ops@example.com",
            credential_reference: "mail",
            security: "none",
            smtp_server: "mail.example.com",
          },
        },
      },
    ];
    const [node] = dropLegacySendMailSettings(nodes);
    expect((node.data as { pluginConfig: unknown }).pluginConfig).toEqual({
      to: "ops@example.com",
    });
  });

  it("leaves other nodes untouched", () => {
    const nodes = [
      {
        id: "n2",
        data: { kind: "run-command", pluginConfig: { credential_reference: "lab-ssh" } },
      },
    ];
    expect(dropLegacySendMailSettings(nodes)).toEqual(nodes);
  });
});
