"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Add to Nautobot.
 * Covers every Configuration control with practical examples.
 */
export function AddToNautobotHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Creates a new device record in Nautobot for each device in the workflow context —
          typically devices whose name came from a step like Get from List that don&apos;t yet
          exist in Nautobot. Configure a Nautobot source, set the required device fields, then
          save.
        </p>
      </HelpSection>

      <HelpSection title="Nautobot source">
        <p>
          Click <span className="font-medium text-foreground">Configure Source</span> (or Edit
          Source) and choose a source from Settings → Sources → Nautobot. The step stores{" "}
          <HelpCode>nautobot_source_id</HelpCode>.
        </p>
        <HelpWarning title="Source required">
          <p>
            Without a valid source the step cannot call the Nautobot API. If the ID is missing
            from Settings, the Configuration panel shows &quot;Source not found in settings&quot;.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Required device fields">
        <p>
          <HelpCode>name</HelpCode>, <HelpCode>role</HelpCode>, <HelpCode>status</HelpCode>,{" "}
          <HelpCode>location</HelpCode>, and <HelpCode>device_type</HelpCode> must all resolve to
          a non-empty value for a device or that device is marked failed (other devices in the
          same run still proceed). Each accepts:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            A fixed literal — e.g. <HelpCode>active</HelpCode>, <HelpCode>access-switch</HelpCode>
          </li>
          <li>
            A context path — e.g. <HelpCode>{"{name}"}</HelpCode>,{" "}
            <HelpCode>{"{parsed.cisco_config.hostname}"}</HelpCode>,{" "}
            <HelpCode>{"{nautobot.origin}"}</HelpCode>
          </li>
          <li>
            A path with default — e.g. <HelpCode>{"{custom.role | default('access')}"}</HelpCode>
          </li>
        </ul>
        <p>
          By default this step sets <HelpCode>name</HelpCode> to{" "}
          <HelpCode>{"{parsed.cisco_config.hostname}"}</HelpCode> — the hostname pulled from
          the device&apos;s own config by an upstream Parse Cisco Config step —{" "}
          <HelpCode>role</HelpCode>, <HelpCode>location</HelpCode>, and{" "}
          <HelpCode>device_type</HelpCode> to <HelpCode>{"{nautobot.origin}"}</HelpCode>, and{" "}
          <HelpCode>status</HelpCode> to{" "}
          <HelpCode>{"{nautobot.origin | default('Active')}"}</HelpCode>, so a device that
          already has Nautobot attributes (e.g. from an upstream Get Nautobot Attributes step)
          keeps — or is written back with — its existing values instead of requiring you to
          retype them here, while a brand-new device with no Nautobot record yet still gets a
          usable status instead of failing as missing.
        </p>
        <HelpExample>
          device_fields:
          <br />
          {"  "}name:
          <br />
          {"    "}value: {"{parsed.cisco_config.hostname}"}
          <br />
          {"  "}role:
          <br />
          {"    "}value: {"{nautobot.origin}"}
          <br />
          {"  "}status:
          <br />
          {"    "}value: {"{nautobot.origin | default('Active')}"}
        </HelpExample>
        <HelpWarning title="parsed.cisco_config.hostname needs a running- or startup-only parse">
          <p>
            <HelpCode>{"{parsed.cisco_config.hostname}"}</HelpCode> only resolves when the
            upstream Parse Cisco Config step&apos;s <HelpCode>config_source</HelpCode> is{" "}
            <HelpCode>running</HelpCode> or <HelpCode>startup</HelpCode>. With the{" "}
            <HelpCode>both</HelpCode> default, the model nests one level deeper — use{" "}
            <HelpCode>{"{parsed.cisco_config.running.hostname}"}</HelpCode> instead — otherwise
            <HelpCode>name</HelpCode> resolves empty and the device fails as{" "}
            <HelpCode>missing_required_field</HelpCode>.
          </p>
        </HelpWarning>
        <HelpWarning title="{nautobot.origin} needs an existing nautobot attribute bag">
          <p>
            <HelpCode>{"{nautobot.origin}"}</HelpCode> reads from the device&apos;s existing{" "}
            <HelpCode>nautobot</HelpCode> attribute bag — it&apos;s empty for a device that has
            never been read from or written to Nautobot (e.g. straight from Get from List with
            no Get Nautobot Attributes step upstream). Without a{" "}
            <HelpCode>{"| default(...)"}</HelpCode> fallback (as on <HelpCode>status</HelpCode>{" "}
            by default), the field resolves empty and the device fails as{" "}
            <HelpCode>missing_required_field</HelpCode> — add one, e.g.{" "}
            <HelpCode>{"{nautobot.origin | default('Network')}"}</HelpCode>, to{" "}
            <HelpCode>role</HelpCode>, <HelpCode>location</HelpCode>, or{" "}
            <HelpCode>device_type</HelpCode> if the device may not have one yet.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Optional fields, custom fields, and rack">
        <p>
          Platform, software version, serial, asset tag, and tags are only sent when enabled.
          Custom fields work the same way as Update Device. Rack placement (rack, face, position)
          is skipped entirely unless a rack value is set.
        </p>
      </HelpSection>

      <HelpSection title="Interfaces">
        <p>
          Optional interfaces to create on the new device, same shape as Update Device: name,
          type, status, IP address, description, and whether the IP becomes the device&apos;s
          primary IPv4.
        </p>
      </HelpSection>

      <HelpSection title="Virtual chassis">
        <p>
          Optionally join an existing virtual chassis (by UUID) or create a new one (the new
          device becomes master at position 1).
        </p>
        <HelpWarning title="Fan-out caution">
          <p>
            Two devices in the same fan-out batch joining the <em>same</em> existing chassis
            concurrently can race on position assignment. Prefer{" "}
            <HelpCode>max_concurrency: 1</HelpCode> on the upstream inventory step, or run those
            devices in a separate batch, when several devices share one chassis.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Dry run">
        <p>
          When <HelpCode>dry_run</HelpCode> is on, the step validates the resolved fields against
          Nautobot (duplicate device name, and that role/status/location/device_type UUIDs exist)
          without creating anything.
        </p>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the device was created
            (or, in dry-run mode, validated) successfully.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — a required field
            didn&apos;t resolve, Nautobot rejected the request (e.g. duplicate name, unknown
            role/status/location), or dry-run validation found a problem.
          </li>
        </ul>
      </HelpSection>
    </div>
  );
}
