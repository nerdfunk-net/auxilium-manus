"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Start Job.
 * Covers every Configuration control with practical examples.
 */
export function StartNautobotJobHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Starts a Nautobot job once for each device in the workflow context, resolving the
          job&apos;s required and optional parameters per device, and records the returned job
          result ID, the exact request sent, and Nautobot&apos;s response on each device (
          <HelpCode>attribute_bags.nautobot_job</HelpCode>) for a downstream status-check step
          to poll and for debugging in the run&apos;s device detail view.
        </p>
      </HelpSection>

      <HelpSection title="Nautobot source">
        <p>
          Click <span className="font-medium text-foreground">Configure Source</span> and choose
          a source created under Settings → Sources → Nautobot. The step stores that
          source&apos;s ID as <HelpCode>nautobot_source_id</HelpCode>.
        </p>
        <HelpWarning title="Source required">
          <p>Without a valid source the step cannot list jobs, fetch parameters, or run.</p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Selecting a job">
        <p>
          Click <span className="font-medium text-foreground">Configure Job</span>, then{" "}
          <span className="font-medium text-foreground">Select Job</span> to browse jobs
          installed on the configured Nautobot source. Selecting a job fetches its parameter
          schema and renders one row per parameter, split into required and optional.
        </p>
        <p>
          Use <span className="font-medium text-foreground">Refresh parameters</span> if the
          job&apos;s parameters changed in Nautobot since you configured this step — the schema
          is cached on the step so runs don&apos;t depend on a live fetch.
        </p>
      </HelpSection>

      <HelpSection title="Parameter values">
        <p>
          Every value can be a literal (<HelpCode>10</HelpCode>, <HelpCode>true</HelpCode>) or a{" "}
          <HelpCode>{"{path}"}</HelpCode> attribute expression resolved per device — click the
          search icon next to any value to browse real upstream attributes. A required parameter
          left empty (no default, no upstream value) fails that device without starting the job.
        </p>
        <HelpExample>
          {"{nautobot.name}"}
          <br />
          <span className="text-muted-foreground">
            → resolves to that device&apos;s name from its Nautobot attribute bag
          </span>
        </HelpExample>
        <p>
          Optional parameters are off by default — enable the checkbox to send that parameter.
          Values are coerced to the job&apos;s declared type (integer, boolean, JSON/list) before
          the job is started; a value that can&apos;t be coerced fails that device with a clear
          message.
        </p>
      </HelpSection>

      <HelpSection title="Convert to UUID">
        <p>
          Parameters that reference a Nautobot object (location, role, status, device,
          platform, rack, device type, namespace) must be submitted as that object&apos;s
          UUID. Click the fingerprint icon next to a value to turn on UUID conversion, then
          pick what kind of object the value names — the step auto-suggests this when
          Nautobot&apos;s own job schema declares the parameter as an object reference. Role
          and status also need a content type (e.g. <HelpCode>dcim.device</HelpCode> vs{" "}
          <HelpCode>dcim.interface</HelpCode>) since the same status name can exist for
          different object kinds.
        </p>
        <p>
          Conversion runs per device, after the value (literal or <HelpCode>{"{path}"}</HelpCode>
          ) is resolved — so a <HelpCode>{"{path}"}</HelpCode> expression can resolve to a
          different name per device and still convert correctly.{" "}
          <span className="font-medium text-foreground">Test resolve</span> checks a literal
          value against Nautobot right away; it&apos;s disabled for{" "}
          <HelpCode>{"{path}"}</HelpCode> expressions since those only resolve per device at
          run time.
        </p>
      </HelpSection>

      <HelpSection title="Debugging: request and response">
        <p>
          After a run, open the run&apos;s device detail view and check the{" "}
          <span className="font-medium text-foreground">Attribute bags</span> tab for{" "}
          <HelpCode>nautobot_job</HelpCode> — it holds the exact{" "}
          <HelpCode>request</HelpCode> payload sent to Nautobot (after{" "}
          <HelpCode>{"{path}"}</HelpCode> resolution and any UUID conversion) and Nautobot&apos;s{" "}
          <HelpCode>response</HelpCode>. This is recorded on both success and failure, so a
          failed device still shows exactly what was attempted.
        </p>
        <HelpWarning title="Not populated by Test resolve">
          <p>
            <span className="font-medium text-foreground">Test resolve</span> in the config
            dialog is a design-time check only — it never runs this step, so it does not write
            to <HelpCode>attribute_bags.nautobot_job</HelpCode>. You need an actual workflow run
            to see the request/response here.
          </p>
        </HelpWarning>
        <p>
          Values that look like a secret (a field named <HelpCode>password</HelpCode>,{" "}
          <HelpCode>token</HelpCode>, <HelpCode>api_key</HelpCode>, etc.) are replaced with{" "}
          <HelpCode>***REDACTED***</HelpCode> before this is recorded.
        </p>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the REST call to
            start the job succeeded. The device carries the job result ID for a downstream
            status-check step. This does not mean the job itself finished or succeeded — it
            hasn&apos;t run yet.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — the REST call itself
            failed (bad parameters, auth, network, unknown job). Never set because of how the
            job later runs — only how starting it went.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Configure a Nautobot source (Settings → Sources).</li>
          <li>Select the job to run.</li>
          <li>Fill in required parameters; enable and fill in any optional ones you need.</li>
          <li>
            Wire the <span className="font-medium text-foreground">success</span> outcome to a
            status-check step that reads{" "}
            <HelpCode>attribute_bags.nautobot_job.job_result_id</HelpCode> and polls until the
            job finishes.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
