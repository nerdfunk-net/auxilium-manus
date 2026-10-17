import { describe, expect, it } from "vitest";

import {
  buildWorkflowRunsListQuery,
  EMPTY_WORKFLOW_RUN_FILTERS,
} from "./workflow-run-filters";

describe("buildWorkflowRunsListQuery", () => {
  it("passes limit and offset", () => {
    expect(
      buildWorkflowRunsListQuery(EMPTY_WORKFLOW_RUN_FILTERS, { limit: 50, offset: 100 }),
    ).toBe("?limit=50&offset=100");
  });

  it("keeps the filters next to the page", () => {
    const query = buildWorkflowRunsListQuery(
      { ...EMPTY_WORKFLOW_RUN_FILTERS, statuses: ["failed"] },
      { limit: 50, offset: 0 },
    );
    expect(query).toContain("limit=50");
    expect(query).toContain("status=failed");
  });

  it("is empty without filters and without a page", () => {
    expect(buildWorkflowRunsListQuery(EMPTY_WORKFLOW_RUN_FILTERS)).toBe("");
  });
});
