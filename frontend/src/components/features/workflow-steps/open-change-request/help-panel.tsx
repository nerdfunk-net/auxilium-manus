"use client";

import { HelpCode, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Open Change Request.
 * Covers every Configuration control (see doc/CICD_PIPELINE.md).
 */
export function OpenChangeRequestHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Ends a <strong>stage</strong> run. It commits the configs rendered by an upstream Render
          Jinja Template step to a per-change git branch, pushes the branch, stores a unified diff
          and records a change request that waits for review. Approving the change request (in
          the UI or through a signed git webhook) starts a separate deploy run.
        </p>
        <p>
          When the rendered configs equal the base branch there is nothing to review: the devices
          leave through the <HelpCode>unchanged</HelpCode> outcome and no change request is opened.
        </p>
      </HelpSection>

      <HelpSection title="Where to place it">
        <p>
          Put it after a Fan In step (or another join point) so exactly one change request comes
          out, not one per fan-out child or sibling branch. A per-repository lock serialises
          callers that use the same repository.
        </p>
      </HelpSection>

      <HelpSection title="Repository and content">
        <p>
          <HelpCode>git_repository_id</HelpCode> is the repository the branch is pushed to.{" "}
          <HelpCode>content_source</HelpCode> defaults to <HelpCode>rendered_template</HelpCode>.{" "}
          <HelpCode>source_step_node_id</HelpCode> names the Render Jinja Template step to commit;
          leave it empty to commit every rendered template on the devices (the panel fills it in
          when the workflow has exactly one render step).
        </p>
      </HelpSection>

      <HelpSection title="Templates">
        <p>
          <HelpCode>filename_template</HelpCode> is the per-device file path, for example{" "}
          <HelpCode>{"{nautobot.location.name}/{device.name}.cfg"}</HelpCode>.{" "}
          <HelpCode>branch_template</HelpCode> (default <HelpCode>{"manus/cr-{run.id}"}</HelpCode>
          ), <HelpCode>commit_message_template</HelpCode> and <HelpCode>title_template</HelpCode>{" "}
          take <HelpCode>{"{run.id}"}</HelpCode> and <HelpCode>{"{workflow.id}"}</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Deploy and expiry">
        <p>
          <HelpCode>deploy_workflow_id</HelpCode> is the workflow that deploys an approved change
          request. It is optional: the reviewer may choose one at approval time.{" "}
          <HelpCode>expires_after_hours</HelpCode> (default 168) is how long an un-actioned change
          request stays open; <HelpCode>0</HelpCode> disables expiry.
        </p>
      </HelpSection>

      <HelpWarning title="Approval needs two permissions">
        <p>
          The approver needs <HelpCode>change_requests:approve</HelpCode> and{" "}
          <HelpCode>workflows:execute</HelpCode>, and must be able to see the deploy workflow.
        </p>
      </HelpWarning>
    </div>
  );
}
