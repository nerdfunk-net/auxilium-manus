"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Check Job.
 * Covers every Configuration control with practical examples.
 */
export function CheckNautobotJobHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Polls a Nautobot job result&apos;s status once per device — check, wait, check again —
          up to a maximum number of checks. Routes to <HelpCode>success</HelpCode> only when the
          job&apos;s own result status is <HelpCode>SUCCESS</HelpCode>. Everything else (the
          job&apos;s own result is <HelpCode>FAILURE</HelpCode>/<HelpCode>REVOKED</HelpCode>, it
          never finished within the check budget, or a check&apos;s REST call itself errored)
          routes to <HelpCode>failure</HelpCode> — there are only two outcomes.
        </p>
      </HelpSection>

      <HelpSection title="Nautobot source">
        <p>
          Click <span className="font-medium text-foreground">Configure Source</span> and choose
          a source created under Settings → Sources → Nautobot. The step stores that
          source&apos;s ID as <HelpCode>nautobot_source_id</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="job_uuid">
        <p>
          The UUID of the Nautobot job result to check — a literal UUID or a{" "}
          <HelpCode>{"{path}"}</HelpCode> attribute expression, resolved per device. Click the
          search icon to browse real upstream attributes.
        </p>
        <HelpExample>
          {"{nautobot_job.job_result_id}"}
          <br />
          <span className="text-muted-foreground">
            → the default — reads the job result ID Start Job wrote for this device
          </span>
        </HelpExample>
        <p>
          A device with no value for this expression (no upstream Start Job, and no literal
          UUID) fails immediately without making a REST call.
        </p>
      </HelpSection>

      <HelpSection title="max_checks and interval_seconds">
        <p>
          <HelpCode>max_checks</HelpCode> is the maximum number of status checks before giving
          up. <HelpCode>interval_seconds</HelpCode> is how long to wait between checks — the
          step never waits after the last check. Total worst-case wait is{" "}
          <HelpCode>max_checks × interval_seconds</HelpCode>.
        </p>
        <HelpExample>
          max_checks: 10
          <br />
          interval_seconds: 5
          <br />
          <span className="text-muted-foreground">→ up to 50s worst case</span>
        </HelpExample>
        <HelpWarning title="120s ceiling">
          <p>
            <HelpCode>max_checks × interval_seconds</HelpCode> must not exceed 120 seconds — the
            step fails to start otherwise. This bounds how long the run occupies a worker slot
            while polling; it is a plain loop inside the step, not a durable wait.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="bag_name">
        <p>
          The <HelpCode>attribute_bags</HelpCode> key this step merges its{" "}
          <HelpCode>status</HelpCode>/<HelpCode>checks_performed</HelpCode> result into.
          Defaults to <HelpCode>nautobot_job</HelpCode> — the same bag Start Job writes to
          by default, so a single job pair works with no configuration.
        </p>
        <HelpWarning title="Running more than one job on the same device">
          <p>
            Two Start Job/Check Job pairs on the same device (e.g. one onboarding job, one
            update job) both default to the bag name <HelpCode>nautobot_job</HelpCode> — the
            second pair&apos;s write overwrites the first pair&apos;s result. Give each pair a
            distinct <HelpCode>bag_name</HelpCode> (matching the paired Start Job node&apos;s
            bag_name) and point this step&apos;s <HelpCode>job_uuid</HelpCode> at that same
            name, e.g. <HelpCode>{"{onboard_job.job_result_id}"}</HelpCode> with{" "}
            <HelpCode>bag_name: onboard_job</HelpCode>.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the job&apos;s own
            result status is <HelpCode>SUCCESS</HelpCode>.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — the job&apos;s own
            result is <HelpCode>FAILURE</HelpCode> or <HelpCode>REVOKED</HelpCode>, it was still
            running after the last check, or every check&apos;s REST call errored. The device
            error names the last observed status (or last REST error) and how many checks ran.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Wire this step after Start Job&apos;s success outcome.</li>
          <li>Leave job_uuid at its default so it reads Start Job&apos;s job result ID.</li>
          <li>Set max_checks/interval_seconds to fit how long the job typically takes.</li>
          <li>Route success/failure onward — e.g. to a notification or a rollback step.</li>
        </ol>
      </HelpSection>
    </div>
  );
}
