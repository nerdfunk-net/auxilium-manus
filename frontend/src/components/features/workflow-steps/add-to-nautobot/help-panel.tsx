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
          Platform, software version, serial, asset tag, and tags are only sent to Nautobot
          when their checkbox is <span className="font-medium text-foreground">enabled</span> —
          by default on a new node they start enabled with{" "}
          <HelpCode>{"{nautobot.origin}"}</HelpCode>, same as the required fields, but you can
          uncheck any of them. Rack placement (rack, face, position) starts unchecked and is
          skipped entirely unless a rack value is set.
        </p>
        <HelpWarning title="An unchecked field is never sent, no matter what's in the bag">
          <p>
            If Set Default Attributes (or Get Nautobot Attributes) seeded{" "}
            <HelpCode>serial</HelpCode> or <HelpCode>tags</HelpCode> into the device&apos;s
            nautobot bag but the device still isn&apos;t created with those values, check that
            the field&apos;s checkbox is actually enabled here — a value sitting in the bag is
            never applied for a field that isn&apos;t checked, even with{" "}
            <HelpCode>{"{nautobot.origin}"}</HelpCode> typed into its value box.
          </p>
        </HelpWarning>
        <p>
          <HelpCode>tags</HelpCode> already sends <span className="font-medium text-foreground">
            every
          </span> tag on the device when set to <HelpCode>{"{nautobot.origin}"}</HelpCode> — the
          bag&apos;s tag list is joined and re-split automatically, so however many tags a
          device has, all of them go through. No separate &quot;all tags&quot; toggle is needed.
        </p>
      </HelpSection>

      <HelpSection title="Custom fields">
        <p>
          Custom fields have two sources, chosen by the <HelpCode>custom_fields_source</HelpCode>{" "}
          dropdown above the rows:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">Manual</span> — the same
            checkbox-per-row editor as Update Device; only enabled rows with a value are sent.
            You must know each custom field&apos;s name in advance.
          </li>
          <li>
            <span className="font-medium text-foreground">All from Nautobot origin</span> —
            ignores the rows and sends every custom field present in the device&apos;s nautobot
            attribute bag as-is, whatever their names are and however many there are. Use this
            when the set of custom fields varies per device (e.g. seeded per-device by Set
            Default Attributes reading a git YAML file, or by an upstream Get Nautobot
            Attributes read of a real device).
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Interfaces">
        <p>
          Interfaces also have two sources, chosen by the <HelpCode>interfaces_source</HelpCode>{" "}
          dropdown above the rows:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">Manual</span> — a fixed list you type
            in advance: name, type, status, IP address, description, and whether the IP becomes
            the device&apos;s primary IPv4. You must know how many interfaces the device has and
            name them yourself.
          </li>
          <li>
            <span className="font-medium text-foreground">All from Nautobot origin</span> —
            ignores the rows and creates every interface present in the device&apos;s nautobot
            attribute bag, each with however many IP addresses it actually has (a real
            interface can have more than one). This is the setting for when it&apos;s not
            obvious in advance how many interfaces a device will turn out to have — the count
            comes from whatever Set Default Attributes or Get Nautobot Attributes put in the
            bag for that specific device.
          </li>
        </ul>
        <HelpExample>
          nautobot.interfaces:
          <br />
          {"  "}- name: Loopback0
          <br />
          {"    "}status: {"{"}name: Active{"}"}
          <br />
          {"    "}ip_addresses: [10.0.0.1/32, 10.0.0.2/32]
          <br />
          <span className="text-muted-foreground">
            → creates Loopback0 with both 10.0.0.1/32 and 10.0.0.2/32 assigned to it
          </span>
        </HelpExample>
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
