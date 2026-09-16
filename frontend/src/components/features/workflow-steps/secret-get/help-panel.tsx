"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "@/components/features/workflow-steps/shared/step-help";

export function SecretGetHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Reads one field from an external Secret Manager connection (OpenBao or
          Infisical) per device and seals it into the device&apos;s attribute bag —
          the &quot;retrieve the current or a previous device secret&quot; primitive
          (a TACACS+ key, an SNMP credential, ...). A device with no value at the
          configured path/field is routed to <HelpCode>failure</HelpCode>; the step
          itself still succeeds for every other device (proceed with survivors).
        </p>
        <p>
          Configure the connection itself in{" "}
          <span className="font-medium text-foreground">Settings → Secret Manager</span>{" "}
          — that page has its own Help dialog covering OpenBao/Infisical setup.
        </p>
      </HelpSection>

      <HelpSection title="connection_id">
        <p>
          Which configured Secret Manager connection to read from. Only{" "}
          <span className="font-medium text-foreground">active</span> connections are
          offered here.
        </p>
      </HelpSection>

      <HelpSection title="path_template">
        <p>
          The path within the connection, rendered per device before the read — e.g.{" "}
          <HelpCode>network/{"{device.name}"}/tacacs</HelpCode> becomes{" "}
          <HelpCode>network/router1/tacacs</HelpCode> for a device named{" "}
          <HelpCode>router1</HelpCode>. Supports the same{" "}
          <HelpCode>{"{device.*}"}</HelpCode>, <HelpCode>{"{nautobot.*}"}</HelpCode>,{" "}
          <HelpCode>{"{git.*}"}</HelpCode> placeholders as{" "}
          <span className="font-medium text-foreground">Store Artifact</span>&apos;s{" "}
          <HelpCode>filename_template</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="field">
        <p>
          The field name to read within the secret stored at{" "}
          <HelpCode>path_template</HelpCode>. One path can hold several named fields
          (e.g. <HelpCode>key</HelpCode>, <HelpCode>rotated_at</HelpCode>) — this
          picks one of them.
        </p>
      </HelpSection>

      <HelpSection title="destination_path">
        <p>
          Where the value is written in the device&apos;s attribute bag, in{" "}
          <HelpCode>bag.field</HelpCode> form. Defaults to{" "}
          <HelpCode>tacacs.shared_secret</HelpCode> — the same path{" "}
          <span className="font-medium text-foreground">Get ISE TACACS Key</span> and{" "}
          <span className="font-medium text-foreground">Update ISE TACACS Key</span>{" "}
          already use, so downstream steps written before this feature existed need
          no changes to consume the value.
        </p>
      </HelpSection>

      <HelpSection title="version">
        <p>
          Optional. Reads a specific historical version instead of the latest — the
          &quot;what was the key before the last rotation&quot; use case. Leave blank
          to read the latest version.
        </p>
      </HelpSection>

      <HelpSection title="strict_templates">
        <p>
          When on (default), a namespaced placeholder in{" "}
          <HelpCode>path_template</HelpCode> (e.g. <HelpCode>{"{nautobot.*}"}</HelpCode>)
          that resolves empty fails the step instead of silently rendering as blank.
        </p>
      </HelpSection>

      <HelpWarning title="The value is always sealed — never exposed as plaintext">
        <p>
          The read value is written into <HelpCode>destination_path</HelpCode> as a
          sealed envelope, not a plain string. It is redacted everywhere the run is
          persisted or displayed. Only a trusted consumer (e.g.{" "}
          <span className="font-medium text-foreground">Render Jinja Template</span>)
          can read the cleartext, and only in memory for one call.
        </p>
      </HelpWarning>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — devices
            that had a value at the configured path/field.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — devices
            with no value found, each carrying a <HelpCode>DeviceError</HelpCode> for
            a downstream notify step. If the connection itself is unreachable or
            authentication fails, the <em>whole</em> step routes to{" "}
            <HelpCode>failure</HelpCode> instead (every device affected equally).
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            Configure a connection in Settings → Secret Manager and select it here.
          </li>
          <li>
            Set <HelpCode>path_template</HelpCode> and <HelpCode>field</HelpCode> to
            match how <span className="font-medium text-foreground">Secret Set</span>{" "}
            / <span className="font-medium text-foreground">Secret Generate</span>{" "}
            stored the value.
          </li>
          <li>
            Follow with a step that consumes the sealed value, e.g.{" "}
            <span className="font-medium text-foreground">Render Jinja Template</span>{" "}
            or <span className="font-medium text-foreground">Update ISE TACACS Key</span>.
          </li>
        </ol>
        <HelpExample>
          path_template: network/{"{device.name}"}/tacacs
          <br />
          field: key
          <br />
          destination_path: tacacs.shared_secret
        </HelpExample>
      </HelpSection>
    </div>
  );
}
