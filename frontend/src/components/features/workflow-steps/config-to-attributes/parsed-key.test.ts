import { describe, expect, it } from "vitest";

import { isNestedFormat, parsedKeyFromAttributePath } from "./parsed-key";

describe("parsedKeyFromAttributePath", () => {
  it("takes the first segment for a flat format", () => {
    expect(parsedKeyFromAttributePath("parsed.cisco_config.running", "cisco_config_parser")).toBe(
      "cisco_config",
    );
    expect(parsedKeyFromAttributePath("parsed.aci_details.interfaces.parsed", "aci_details")).toBe(
      "aci_details",
    );
  });

  it("takes node id and output key for a nested format, cutting at the entry's sub-key", () => {
    expect(parsedKeyFromAttributePath("parsed.get-pyats-1.pyats_config.running", "genie")).toBe(
      "get-pyats-1.pyats_config",
    );
    expect(
      parsedKeyFromAttributePath(
        "parsed.extract-1.batfish_extract_facts.parsed.TACACS.TACACS_Servers[address=10.0.0.1]",
        "batfish",
      ),
    ).toBe("extract-1.batfish_extract_facts");
  });

  it("keeps a nested path that ends at the entry itself", () => {
    expect(parsedKeyFromAttributePath("parsed.get-pyats-1.pyats_config", "genie")).toBe(
      "get-pyats-1.pyats_config",
    );
  });

  it("returns a path outside the parsed namespace unchanged", () => {
    expect(parsedKeyFromAttributePath("nautobot.location.name", "genie")).toBe(
      "nautobot.location.name",
    );
  });

  it("knows which formats are nested", () => {
    expect(isNestedFormat("genie")).toBe(true);
    expect(isNestedFormat("batfish")).toBe(true);
    expect(isNestedFormat("aci_details")).toBe(false);
  });
});
