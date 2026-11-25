import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NautobotSourceStatus, SourceRow } from "./source-row";

describe("SourceRow", () => {
  it("shows the key, the badge, the id and an Edit button", () => {
    const onOpen = vi.fn();
    render(<SourceRow label="ise_source_id" badge="ise" sourceId="lab" onOpen={onOpen} />);
    expect(screen.getByText("ise_source_id")).toBeTruthy();
    expect(screen.getByText("ise")).toBeTruthy();
    expect(screen.getByText("lab")).toBeTruthy();
    expect(screen.queryByText("Not configured")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Edit Source" }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("says Not configured and offers Configure Source without an id", () => {
    render(<SourceRow label="k" badge="b" sourceId="" onOpen={vi.fn()} />);
    expect(screen.getByText("Not configured")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Configure Source" })).toBeTruthy();
  });

  it("shows the status next to the id only when an id is set", () => {
    const { rerender } = render(
      <SourceRow label="k" badge="b" sourceId="lab" onOpen={vi.fn()} status={<span>STATUS</span>} />,
    );
    expect(screen.getByText("STATUS")).toBeTruthy();
    rerender(<SourceRow label="k" badge="b" sourceId="" onOpen={vi.fn()} status={<span>STATUS</span>} />);
    expect(screen.queryByText("STATUS")).toBeNull();
  });
});

describe("NautobotSourceStatus", () => {
  it("shows the URL when the credentials are ready", () => {
    render(<NautobotSourceStatus isReady isLoading={false} url="https://nb.example" />);
    expect(screen.getByText("https://nb.example")).toBeTruthy();
  });

  it("shows loading while they load", () => {
    render(<NautobotSourceStatus isReady={false} isLoading url="" />);
    expect(screen.getByText("Loading credentials…")).toBeTruthy();
  });

  it("says the source is not found otherwise", () => {
    render(<NautobotSourceStatus isReady={false} isLoading={false} url="" />);
    expect(screen.getByText("Source not found in settings")).toBeTruthy();
  });

  it("prefers ready over loading", () => {
    render(<NautobotSourceStatus isReady isLoading url="u" />);
    expect(screen.queryByText("Loading credentials…")).toBeNull();
  });
});
