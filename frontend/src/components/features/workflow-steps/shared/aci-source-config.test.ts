import { describe, expect, it } from "vitest";

import {
  ACI_SOURCE_ID_KEY,
  aciSourceIdFromConfig,
  isAciSourceConfigured,
} from "./aci-source-config";

describe("aci source config", () => {
  it("uses the key the backend step reads", () => {
    expect(ACI_SOURCE_ID_KEY).toBe("aci_source_id");
  });

  it("reads and trims the source id", () => {
    expect(aciSourceIdFromConfig({ aci_source_id: "  lab-aci " })).toBe("lab-aci");
  });

  it("treats missing, blank and non-text values as not configured", () => {
    for (const config of [{}, { aci_source_id: "" }, { aci_source_id: "  " }, { aci_source_id: 5 }]) {
      expect(aciSourceIdFromConfig(config)).toBe("");
      expect(isAciSourceConfigured(config)).toBe(false);
    }
  });

  it("is configured once an id is set", () => {
    expect(isAciSourceConfigured({ aci_source_id: "lab" })).toBe(true);
  });

  it("ignores the Catalyst Center key", () => {
    expect(aciSourceIdFromConfig({ catalyst_center_source_id: "cc" })).toBe("");
  });
});
