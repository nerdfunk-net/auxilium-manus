"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Collect Statistics.
 * Covers every Configuration control with practical examples.
 */
export function CollectStatisticsHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Writes one row per device in the workflow context to the job statistics
          table — job name and id (the containing workflow&apos;s name/id), run id,
          device name, and the result configured below. Powers the dashboard&apos;s
          Job Statistics pie chart, which shows the pass/fail split for the most
          recent run of a job.
        </p>
      </HelpSection>

      <HelpSection title="result">
        <p>
          One of <HelpCode>success</HelpCode> or <HelpCode>failed</HelpCode>. Recorded
          verbatim for every device that reaches this node — the step does not inspect
          the device&apos;s own pass/fail status, only the value configured here.
        </p>
        <HelpExample>result: success — recorded when wired to a success handle</HelpExample>
        <HelpExample>result: failed — recorded when wired to a failure handle</HelpExample>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            Place one Collect Statistics node on the <HelpCode>success</HelpCode> handle
            of the step you&apos;re measuring (e.g. Get Device Configs), with{" "}
            <HelpCode>result: success</HelpCode>.
          </li>
          <li>
            Place a second Collect Statistics node on that same step&apos;s{" "}
            <HelpCode>failure</HelpCode> handle, with <HelpCode>result: failed</HelpCode>.
          </li>
          <li>
            Together, the two nodes record every device that reached either branch —
            one step type covering both outcomes.
          </li>
        </ol>
        <HelpWarning title="Wire both handles to get an accurate total">
          <p>
            A device that never reaches either Collect Statistics node contributes to
            neither count, so the dashboard&apos;s total reflects devices{" "}
            <span className="font-medium text-foreground">recorded</span>, not
            necessarily every device the run targeted. Wire both outcome handles you
            care about, not just one.
          </p>
        </HelpWarning>
        <HelpWarning title="Avoid recording the same device twice">
          <p>
            If a device can reach more than one recording instance in the same run
            (e.g. two different upstream branches both leading here), it is counted
            more than once — there is no device-level dedup. Place each instance at a
            true branch point a device can only take once.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — a row was
            written for each device in context (zero devices writes zero rows and is
            not an error). Pass-through: the context is forwarded unchanged so the
            workflow can continue after recording.
          </li>
        </ul>
      </HelpSection>
    </div>
  );
}
