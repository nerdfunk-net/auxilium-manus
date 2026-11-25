import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FromChangeRequestHelpPanel } from "./from-change-request/help-panel";
import { FromChangeRequestPlugin } from "./from-change-request/index";
import { OpenChangeRequestHelpPanel } from "./open-change-request/help-panel";
import { OpenChangeRequestPlugin } from "./open-change-request/index";

describe("change request help panels", () => {
  it("are registered on both plugins", () => {
    expect(OpenChangeRequestPlugin.HelpPanel).toBe(OpenChangeRequestHelpPanel);
    expect(FromChangeRequestPlugin.HelpPanel).toBe(FromChangeRequestHelpPanel);
  });

  it("Open Change Request documents every config key", () => {
    render(<OpenChangeRequestHelpPanel />);
    for (const key of [
      "git_repository_id",
      "content_source",
      "source_step_node_id",
      "filename_template",
      "branch_template",
      "commit_message_template",
      "title_template",
      "deploy_workflow_id",
      "expires_after_hours",
    ]) {
      expect(screen.getAllByText(key).length).toBeGreaterThan(0);
    }
  });

  it("From Change Request documents load_configs", () => {
    render(<FromChangeRequestHelpPanel />);
    expect(screen.getAllByText("load_configs").length).toBeGreaterThan(0);
  });
});
