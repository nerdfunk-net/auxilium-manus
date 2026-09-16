"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "@/components/features/workflow-steps/shared/step-help";

export function SecretSetHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Writes an explicit value — a literal, or one read from another attribute
          path — to one field of an external Secret Manager connection (OpenBao or
          Infisical) per device. Also seals the written value into the device&apos;s
          attribute bag, so a later step in the same run can use it without a second
          round trip to the secret manager.
        </p>
        <p>
          Use this when a value already exists somewhere (an operator typed it in as
          a static run attribute, or it came from another system) and you just need
          to store it — for a <em>generated</em> random value, use{" "}
          <span className="font-medium text-foreground">Secret Generate</span> instead.
        </p>
      </HelpSection>

      <HelpSection title="connection_id">
        <p>
          Which configured Secret Manager connection to write to. Only{" "}
          <span className="font-medium text-foreground">active</span> connections are
          offered here.
        </p>
      </HelpSection>

      <HelpSection title="path_template">
        <p>
          The path within the connection, rendered per device before the write — e.g.{" "}
          <HelpCode>network/{"{device.name}"}/tacacs</HelpCode>. Supports the same{" "}
          <HelpCode>{"{device.*}"}</HelpCode>, <HelpCode>{"{nautobot.*}"}</HelpCode>,{" "}
          <HelpCode>{"{git.*}"}</HelpCode> placeholders as{" "}
          <span className="font-medium text-foreground">Store Artifact</span>&apos;s{" "}
          <HelpCode>filename_template</HelpCode>. Always resolves to a{" "}
          <span className="font-medium text-foreground">per-device-unique</span> path
          when it includes <HelpCode>{"{device.*}"}</HelpCode>, which is what keeps
          this step fan-out-safe.
        </p>
      </HelpSection>

      <HelpSection title="field">
        <p>
          The field name to write within the secret at <HelpCode>path_template</HelpCode>.
          One path can hold several named fields.
        </p>
      </HelpSection>

      <HelpSection title="mode">
        <p>
          <HelpCode>fixed</HelpCode> writes the literal value typed into{" "}
          <HelpCode>fixed_value</HelpCode>. <HelpCode>attribute</HelpCode> reads the
          value to write from <HelpCode>source_path</HelpCode> instead — typically a{" "}
          <HelpCode>run_input.*</HelpCode> value an operator supplied when triggering
          the run.
        </p>
      </HelpSection>

      <HelpSection title="fixed_value">
        <p>
          The literal value to write, used only in <HelpCode>fixed</HelpCode> mode.
          Masked the same way any credential input is.
        </p>
      </HelpSection>

      <HelpSection title="source_path">
        <p>
          Attribute path to read the value from, used only in{" "}
          <HelpCode>attribute</HelpCode> mode — e.g.{" "}
          <HelpCode>run_input.new_tacacs_key</HelpCode>. Unlike most generic
          steps, this one <em>is</em> a trusted consumer: it may read a sealed
          value here as cleartext, in memory, for this one write.
        </p>
      </HelpSection>

      <HelpSection title="destination_path">
        <p>
          Where the written value is also sealed into the device&apos;s attribute
          bag, in <HelpCode>bag.field</HelpCode> form — so a later step in the same
          run can use it immediately without reading it back from the secret
          manager. Defaults to <HelpCode>tacacs.shared_secret</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="strict_templates">
        <p>
          When on (default), a namespaced placeholder in{" "}
          <HelpCode>path_template</HelpCode> that resolves empty fails the step
          instead of silently rendering as blank.
        </p>
      </HelpSection>

      <HelpWarning title="A per-device path keeps this step fan-out-safe">
        <p>
          Unlike git/filesystem sinks, this step writes to a{" "}
          <span className="font-medium text-foreground">per-device-unique</span>{" "}
          secret manager path, so it&apos;s safe to run inside a fanned-out branch —
          no Fan In node required.
        </p>
        <p>
          That safety depends on <HelpCode>path_template</HelpCode> actually
          rendering to a different path per device. If you override it to a{" "}
          <span className="font-medium text-foreground">fixed, shared path</span>,
          concurrent fan-out children writing different <HelpCode>field</HelpCode>{" "}
          values to that same path can race —{" "}
          <span className="font-medium text-foreground">on an OpenBao
          connection</span>, each write reads the whole secret, changes one
          field, and writes the whole thing back, so two concurrent writes can
          silently lose one field&apos;s update. Infisical writes each field as
          its own API call and doesn&apos;t hit this specific race. If you can&apos;t
          keep the path device-unique, put a{" "}
          <span className="font-medium text-foreground">Fan In</span> node
          before this step, same as for git-backed sinks.
        </p>
      </HelpWarning>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — devices
            whose value was resolved and written.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — devices
            where <HelpCode>source_path</HelpCode> resolved to nothing (attribute
            mode only), each carrying a <HelpCode>DeviceError</HelpCode>. If the
            connection itself is unreachable or authentication fails, the{" "}
            <em>whole</em> step routes to <HelpCode>failure</HelpCode> instead.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            Configure a connection in Settings → Secret Manager and select it here.
          </li>
          <li>
            Declare a static run attribute (e.g. <HelpCode>new_tacacs_key</HelpCode>)
            on the workflow, set <HelpCode>mode</HelpCode> to{" "}
            <HelpCode>attribute</HelpCode>, and point{" "}
            <HelpCode>source_path</HelpCode> at{" "}
            <HelpCode>run_input.new_tacacs_key</HelpCode>.
          </li>
          <li>
            Follow with a step that consumes <HelpCode>destination_path</HelpCode>,
            e.g. a config-push step.
          </li>
        </ol>
        <HelpExample>
          path_template: network/{"{device.name}"}/tacacs
          <br />
          field: key
          <br />
          mode: attribute
          <br />
          source_path: run_input.new_tacacs_key
          <br />
          destination_path: tacacs.shared_secret
        </HelpExample>
      </HelpSection>
    </div>
  );
}
