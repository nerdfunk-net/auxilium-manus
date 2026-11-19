import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { GitRepositoryCategoryBadge } from "./git-repository-category-badge";

afterEach(cleanup);

describe("GitRepositoryCategoryBadge", () => {
  it("shows a short readable label for the CSV categories", () => {
    render(<GitRepositoryCategoryBadge category="csv_imports" />);
    render(<GitRepositoryCategoryBadge category="csv_exports" />);
    expect(screen.getByText("CSV files")).toBeTruthy();
    expect(screen.getByText("CSV exports")).toBeTruthy();
  });

  it("keeps showing an unknown category as it is", () => {
    render(<GitRepositoryCategoryBadge category="something_new" />);
    expect(screen.getByText("something_new")).toBeTruthy();
  });
});
