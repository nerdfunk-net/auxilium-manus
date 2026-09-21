"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "@/components/features/workflow-steps/shared/step-help";

export function SecretGenerateHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Generates a cryptographically random value per device (stdlib{" "}
          <HelpCode>secrets</HelpCode>, never <HelpCode>random</HelpCode>), stores it
          at one field of an external Secret Manager connection (OpenBao or
          Infisical), and seals it into the device&apos;s attribute bag for a later
          step in the same run — the TACACS+/SNMP{" "}
          <span className="font-medium text-foreground">rotation</span> primitive.
        </p>
        <p>
          The generated value is never shown in the run UI, never logged, and never
          persisted in plaintext — only a sealed envelope reaches{" "}
          <HelpCode>destination_path</HelpCode>, redacted everywhere the run is
          displayed or stored.
        </p>
      </HelpSection>

      <HelpSection title="connection_id">
        <p>
          Which configured Secret Manager connection to write the generated value
          to. Only <span className="font-medium text-foreground">active</span>{" "}
          connections are offered here.
        </p>
      </HelpSection>

      <HelpSection title="path_template">
        <p>
          The path within the connection, rendered per device before the write —
          e.g. <HelpCode>network/{"{device.name}"}/tacacs</HelpCode>. Supports the
          same <HelpCode>{"{device.*}"}</HelpCode>, <HelpCode>{"{nautobot.*}"}</HelpCode>,{" "}
          <HelpCode>{"{git.*}"}</HelpCode> placeholders as{" "}
          <span className="font-medium text-foreground">Store Artifact</span>&apos;s{" "}
          <HelpCode>filename_template</HelpCode>. Always resolves to a{" "}
          <span className="font-medium text-foreground">per-device-unique</span> path
          when it includes <HelpCode>{"{device.*}"}</HelpCode>, which is what keeps
          this step concurrency-safe (fan-out or independent branches) with no Fan In
          node needed.
        </p>
      </HelpSection>

      <HelpSection title="field">
        <p>
          The field name the generated value is stored under, within the secret at{" "}
          <HelpCode>path_template</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="destination_path">
        <p>
          Where the sealed value is written in the device&apos;s attribute bag, in{" "}
          <HelpCode>bag.field</HelpCode> form — so the very next step (e.g. a
          push-config step) can use it without a round trip back to the secret
          manager. Defaults to <HelpCode>tacacs.shared_secret</HelpCode>, the same
          path <span className="font-medium text-foreground">Get/Update ISE TACACS
          Key</span> already use.
        </p>
      </HelpSection>

      <HelpSection title="charset">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>hex</HelpCode> — TACACS+ shared secrets, generic tokens.
          </li>
          <li>
            <HelpCode>alnum</HelpCode> — SNMP community strings (avoids symbols some
            NMS choke on).
          </li>
          <li>
            <HelpCode>alnum_symbols</HelpCode> — SNMPv3 auth/priv passphrases.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="length">
        <p>
          Length of the generated value, in characters. Must be between{" "}
          <HelpCode>4</HelpCode> and <HelpCode>256</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="strict_templates">
        <p>
          When on (default), a namespaced placeholder in{" "}
          <HelpCode>path_template</HelpCode> that resolves empty fails the step
          instead of silently rendering as blank.
        </p>
      </HelpSection>

      <HelpWarning title="Pipe-only — no per-device failure outcome exists">
        <p>
          Generation can&apos;t fail per-device (there&apos;s nothing to look up), so
          this step has no per-device <HelpCode>failure</HelpCode> path. If the
          connection itself is unreachable or authentication fails, the{" "}
          <em>whole</em> step routes to <HelpCode>failure</HelpCode> instead.
        </p>
      </HelpWarning>

      <HelpWarning title="Fan-out risk if path_template is not device-unique">
        <p>
          Fan-out safety depends on <HelpCode>path_template</HelpCode> actually
          rendering to a different path per device (the default does). If you
          override it to a <span className="font-medium text-foreground">fixed,
          shared path</span>, concurrent fan-out children writing different{" "}
          <HelpCode>field</HelpCode> values to that same path can race —{" "}
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
            <span className="font-medium text-foreground">success</span> — the
            generated value was stored and sealed for every device.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — the
            connection was unreachable or denied authentication.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            Configure a connection in Settings → Secret Manager and select it here.
          </li>
          <li>
            Set <HelpCode>path_template</HelpCode>/<HelpCode>field</HelpCode> and pick
            a <HelpCode>charset</HelpCode> matching the credential type being
            rotated.
          </li>
          <li>
            Follow with a config-push step that reads{" "}
            <HelpCode>destination_path</HelpCode> to apply the new value to the
            device, in the same run.
          </li>
        </ol>
        <HelpExample>
          path_template: network/{"{device.name}"}/tacacs
          <br />
          field: key
          <br />
          destination_path: tacacs.shared_secret
          <br />
          charset: hex
          <br />
          length: 32
        </HelpExample>
      </HelpSection>
    </div>
  );
}
