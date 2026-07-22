"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Set Default Attributes.
 * Covers every Configuration control with practical examples.
 */
export function SetDefaultAttributesHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Seeds default values directly into each device&apos;s{" "}
          <HelpCode>attribute_bags.nautobot</HelpCode> — the same bag{" "}
          <HelpCode>{"{nautobot.origin}"}</HelpCode> reads in Add to Nautobot / Update
          Device. Unlike those steps, this one never calls the Nautobot API — it only
          writes into the in-memory workflow context, so it works even for a device
          discovered only by IP (no DNS, no existing Nautobot record).
        </p>
        <p>
          Place it early — right after an inventory step (Get from List, Get from
          Nautobot, Get from Git) — so downstream{" "}
          <HelpCode>{"{nautobot.origin}"}</HelpCode> expressions resolve without typing
          a literal fallback into every workflow.
        </p>
      </HelpSection>

      <HelpSection title="Type">
        <p>
          Resource type these defaults apply to. Only <HelpCode>Device</HelpCode> is
          implemented — <HelpCode>IP Address</HelpCode> and{" "}
          <HelpCode>IP Prefix</HelpCode> are shown but disabled, reserved for a future
          release. Running the step with any other type raises a clear error.
        </p>
      </HelpSection>

      <HelpSection title="Mode">
        <p>
          Where the default values come from:
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">Manual panel</span> — set
            values directly in the Edit Defaults dialog (role, status, location,
            platform, device type, tags, custom fields, interfaces).
          </li>
          <li>
            <span className="font-medium text-foreground">Git repo (YAML)</span> —
            read a YAML file from a configured Git source. The matched file must
            contain a top-level <HelpCode>devices</HelpCode> mapping, e.g.:
          </li>
        </ul>
        <HelpExample>
          devices:
          <br />
          {"  "}role: Network
          <br />
          {"  "}status: Active
          <br />
          {"  "}location: City A
          <br />
          {"  "}tags: production
          <br />
          {"  "}device_type:
          <br />
          {"    "}manufacturer:
          <br />
          {"      "}name: Cisco
          <br />
          {"  "}custom_fields:
          <br />
          {"    "}net: lab
          <br />
          {"  "}interfaces:
          <br />
          {"    "}- name: Ethernet0/0
          <br />
          {"      "}status: {"{"}name: Active{"}"}
          <br />
          {"      "}type: VIRTUAL
          <br />
          {"      "}ip_addresses: [192.168.178.240/24]
        </HelpExample>
        <HelpWarning title="No file, or invalid YAML, fails the whole step">
          <p>
            Unlike Get from Git (which silently treats a missing/bad file as &quot;0
            devices&quot;), a missing <HelpCode>devices</HelpCode> mapping or unparsable
            YAML raises an error — seeding no defaults silently is a worse failure
            mode than stopping the run.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Overwrite">
        <p>
          <span className="font-medium text-foreground">Off</span> (default) — a
          default only fills in a field the device&apos;s nautobot bag doesn&apos;t
          already have (missing, empty, or <HelpCode>null</HelpCode>). Existing values
          are left untouched.
        </p>
        <p>
          <span className="font-medium text-foreground">On</span> — a default always
          replaces whatever the device&apos;s nautobot bag already has for that field.
        </p>
        <p>
          This applies uniformly to every scalar field, to each{" "}
          <HelpCode>custom_fields</HelpCode> entry individually, and to interfaces
          (matched by <HelpCode>name</HelpCode> — off skips a name match entirely, on
          replaces the whole matched interface).
        </p>
      </HelpSection>

      <HelpSection title="Attributes (manual mode)">
        <p>
          Role, Status, Location, Platform, Software version, Serial, Asset tag, and
          Tags are simple checkbox + value rows — only checked rows with a value are
          applied. Device Type sets model and manufacturer name together. Rack, Face,
          and Position default a rack placement. Custom Fields and Interfaces work the
          same way as Add to Nautobot&apos;s equivalents, except Interfaces takes a
          comma-separated list of{" "}
          <span className="font-medium text-foreground">IP addresses</span> per
          interface (a real device interface can have more than one).
        </p>
      </HelpSection>

      <HelpWarning title="Interfaces aren't picked up by Add to Nautobot yet">
        <p>
          Add to Nautobot / Update Device resolve{" "}
          <HelpCode>{"{nautobot.origin}"}</HelpCode> only for scalar device fields
          (name, role, status, location, device_type, platform, tags, custom_fields,
          etc.) — <span className="font-medium text-foreground">not</span> for
          interfaces, which are a hand-typed list with no expression support. This
          step still writes interface defaults into the bag (inspectable via Log
          Attributes, and ready for a future enhancement), but nothing downstream
          consumes them automatically today.
        </p>
      </HelpWarning>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — defaults
            were merged into every device in context (or the step was a no-op: no
            devices, or nothing configured).
          </li>
        </ul>
        <p>
          There is no failure outcome — a bad configuration (unsupported type, missing
          git source, invalid YAML) fails the whole step rather than routing specific
          devices.
        </p>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Add this step right after an inventory step (e.g. Get from List).</li>
          <li>
            Choose Manual or Git mode and set your organization&apos;s standard
            defaults (role, status, location, device type, ...).
          </li>
          <li>
            Leave Overwrite off to only fill gaps, or turn it on to enforce these
            values everywhere.
          </li>
          <li>
            Add Add to Nautobot / Update Device downstream — their{" "}
            <HelpCode>{"{nautobot.origin}"}</HelpCode> fields now resolve to these
            defaults for any device that doesn&apos;t already have its own value.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
