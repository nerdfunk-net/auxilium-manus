import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { NautobotSourceBanner } from "./nautobot-source-banner";

afterEach(cleanup);

describe("NautobotSourceBanner", () => {
  it("tells the user to configure a source when the list loaded and is empty", () => {
    render(<NautobotSourceBanner isLoading={false} hasSources={false} isReady={false} />);
    expect(screen.getByText(/No Nautobot source is configured/)).toBeTruthy();
    expect(screen.getByText("Open Settings")).toBeTruthy();
  });

  it("shows the load error, not 'no source configured', when the list could not be read", () => {
    render(
      <NautobotSourceBanner
        isLoading={false}
        hasSources={false}
        isReady={false}
        error="Permission denied: settings:read required"
      />,
    );
    expect(screen.getByText(/Permission denied: settings:read required/)).toBeTruthy();
    expect(screen.queryByText(/No Nautobot source is configured/)).toBeNull();
    expect(screen.queryByText("Open Settings")).toBeNull();
  });

  it("keeps showing the loading state while the request runs", () => {
    render(<NautobotSourceBanner isLoading hasSources={false} isReady={false} error="x" />);
    expect(screen.getByText(/Resolving Nautobot source/)).toBeTruthy();
  });

  it("shows the active source when one is ready", () => {
    render(<NautobotSourceBanner isLoading={false} hasSources isReady sourceId="nb-1" />);
    expect(screen.getByText("nb-1")).toBeTruthy();
  });
});
