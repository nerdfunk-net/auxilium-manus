import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { GetNautobotAttributesHelpPanel } from "./help-panel";

afterEach(cleanup);

describe("GetNautobotAttributesHelpPanel", () => {
  it("tells the user the interfaces group brings the MAC address and where to read it", () => {
    const { container } = render(<GetNautobotAttributesHelpPanel />);
    const text = container.textContent ?? "";

    expect(text).toContain("mac_address");
    expect(text).toContain("nautobot.interfaces[name=Ethernet0/0].mac_address");
    expect(text).toContain("Update Device");
  });
});
