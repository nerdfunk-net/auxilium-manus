import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/hooks/queries/use-report-catalog-query", () => ({
  useReportCatalogQuery: () => ({ data: [], isLoading: false }),
}));

// Radix Select is awkward in jsdom; a native select keeps the test about our logic.
vi.mock("./labeled-select", () => ({
  LabeledSelect: ({
    value,
    onChange,
    options,
    ariaLabel,
  }: {
    value: string;
    onChange: (value: string) => void;
    options: readonly { value: string; label: string }[];
    ariaLabel: string;
  }) => (
    <select
      aria-label={ariaLabel}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="">choose</option>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));

import { DEFAULT_BUILDER_STATE } from "../utils/query-spec";
import { QueryBuilder } from "./query-builder";

const SOURCES = [
  { id: "report_data", label: "Report database" },
  { id: "nautobot", label: "Nautobot" },
] as const;

afterEach(cleanup);

function renderBuilder(
  props: Partial<React.ComponentProps<typeof QueryBuilder>> = {},
) {
  return render(
    <QueryBuilder
      sources={SOURCES}
      isRunning={false}
      onRun={vi.fn()}
      {...props}
    />,
  );
}

describe("QueryBuilder: telling the page which source is chosen", () => {
  it("reports the first source as soon as the list is known", () => {
    const onSourceChange = vi.fn();

    renderBuilder({ onSourceChange });

    expect(onSourceChange).toHaveBeenLastCalledWith("report_data");
  });

  it("reports the source a loaded query starts from", () => {
    const onSourceChange = vi.fn();

    renderBuilder({
      onSourceChange,
      initialState: { ...DEFAULT_BUILDER_STATE, sourceId: "nautobot" },
    });

    expect(onSourceChange).toHaveBeenLastCalledWith("nautobot");
  });

  it("reports the new source when the user picks another one", () => {
    const onSourceChange = vi.fn();
    renderBuilder({ onSourceChange });

    fireEvent.change(screen.getByLabelText("Source"), {
      target: { value: "nautobot" },
    });

    expect(onSourceChange).toHaveBeenLastCalledWith("nautobot");
  });

  it("works without a listener", () => {
    renderBuilder();

    expect(screen.getByLabelText("Source")).toBeTruthy();
  });
});
