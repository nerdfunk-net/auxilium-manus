"use client";

import {
  FanOutHelpSection,
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Get from User.
 * Covers every Configuration control with practical examples.
 */
export function GetFromUserHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Prompts the operator to enter one or more target devices when they
          start the workflow run, instead of resolving devices from Nautobot
          (Get from Nautobot) or a fixed canvas list (Get from List). Useful
          for deliberate, one-off changes — e.g. rolling out an ACL update to
          a hand-picked set of devices, a few at a time.
        </p>
        <p>
          Devices are added to the workflow context with identity only (name
          and/or IP address) — no Nautobot attributes or credentials until a
          later step enriches the context. This step has no runtime
          dependency on Nautobot: even with{" "}
          <span className="font-medium text-foreground">Nautobot search</span>{" "}
          configured below, that only offers suggestions while the operator
          types — it never blocks a run.
        </p>
      </HelpSection>

      <HelpSection title="device_param">
        <p>
          Name of a workflow <HelpCode>string</HelpCode> static attribute you
          declare in the Properties panel (mark it{" "}
          <span className="font-medium text-foreground">required</span> so
          operators can&apos;t skip it). When someone starts a run, the Run
          Inputs dialog prompts for that attribute; whatever they enter
          becomes this step&apos;s device list for that run only.
        </p>
        <HelpExample>
          device_param: target_devices
          <br />
          <span className="text-muted-foreground">
            → Properties panel declares a required string attribute named
            &quot;target_devices&quot;
          </span>
        </HelpExample>
        <p>
          The value is one device per line. Each line is either a bare
          hostname, a bare IP address (auto-detected), or{" "}
          <HelpCode>name,ip_address</HelpCode> to set both explicitly. Names
          are never checked for existence — there is no inventory to check
          against. An IP-looking token must be a valid IPv4/IPv6 address (with
          or without a CIDR suffix); anything else is treated as a name.
        </p>
        <HelpExample>
          router1.example.com
          <br />
          10.0.0.5
          <br />
          switch2.example.com,10.0.0.6
        </HelpExample>
        <HelpWarning title="At least one device required">
          <p>
            Blank lines are ignored, and duplicate name/IP pairs are
            deduplicated. If the operator submits nothing usable, the step
            fails with a clear error rather than silently running against zero
            devices.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Lookup mode">
        <p>
          <span className="font-medium text-foreground">Manual</span>{" "}
          (default) — the Run Inputs dialog shows a plain multi-line box; the
          operator types devices directly.
        </p>
        <p>
          <span className="font-medium text-foreground">Nautobot search</span>{" "}
          — the dialog additionally suggests devices as the operator types (3
          or more characters triggers a debounced &quot;name contains&quot;
          lookup against the configured Nautobot source). Clicking a
          suggestion adds it with its resolved IP address already filled in.
          The operator can still type a raw entry manually — Nautobot search is
          a convenience, never a requirement, and this step&apos;s executor
          never calls Nautobot itself.
        </p>
        <HelpWarning title="Nautobot source is a UI hint only">
          <p>
            <HelpCode>nautobot_source_id</HelpCode> only powers suggestions in
            the Run Inputs dialog. If the source is unreachable or
            misconfigured, the operator falls back to typing devices manually
            — the run is never blocked on Nautobot.
          </p>
        </HelpWarning>
      </HelpSection>

      <FanOutHelpSection />

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the
            entered devices were added to context.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> —
            device_param is not configured, the run parameter wasn&apos;t
            supplied for this run, or no valid devices were entered.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            In the workflow Properties panel, add a required{" "}
            <HelpCode>string</HelpCode> static attribute (e.g.{" "}
            <HelpCode>target_devices</HelpCode>).
          </li>
          <li>On this step, set device_param to that same name.</li>
          <li>
            Optionally switch Lookup mode to Nautobot search and pick a
            source, for name-contains suggestions while typing.
          </li>
          <li>
            Chain a <span className="font-medium text-foreground">Reachable</span>{" "}
            step right after this one to fail fast on a typo&apos;d device
            before any risky change runs.
          </li>
          <li>
            For a canary rollout, enable fan-out with{" "}
            <span className="font-medium text-foreground">
              Wait for approval between batches
            </span>{" "}
            so devices are processed a few at a time with a manual approval
            gate in between.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
