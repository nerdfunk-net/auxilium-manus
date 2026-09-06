"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "@/components/features/workflow-steps/shared/step-help";

export function EncryptAttributeHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Reads a cleartext attribute value, encrypts it with a shared secret from
          the credential vault, and writes the resulting portable ciphertext token
          to <HelpCode>destination_path</HelpCode>. A later step (for example{" "}
          <span className="font-medium text-foreground">Store Artifact</span>) can
          then persist that token to disk or Git without ever exposing the
          cleartext.
        </p>
        <p>
          The ciphertext token is self-describing (<HelpCode>AM1.&lt;algorithm&gt;.&hellip;</HelpCode>)
          and can be read back later by the{" "}
          <span className="font-medium text-foreground">Decrypt Attribute</span>{" "}
          step with the same shared secret.
        </p>
      </HelpSection>

      <HelpSection title="source_path">
        <p>
          Dot path to the cleartext value to encrypt — e.g.{" "}
          <HelpCode>run_input.enable_password</HelpCode> (a run parameter) or{" "}
          <HelpCode>custom.some_value</HelpCode>. If the path resolves to a{" "}
          <em>sealed</em> secret the device is routed to{" "}
          <HelpCode>failure</HelpCode>: this step reads cleartext only.
        </p>
        <p>
          To reach a value inside a list, use a{" "}
          <HelpCode>key[field=value]</HelpCode> filter segment (selects the first
          matching entry) — e.g.{" "}
          <HelpCode>nautobot.config_context.credentials[username=noc].password</HelpCode>
          . Numeric indexing is not supported.
        </p>
      </HelpSection>

      <HelpSection title="destination_path">
        <p>
          Where the ciphertext token is written, in{" "}
          <HelpCode>bag.field</HelpCode> form (e.g.{" "}
          <HelpCode>secrets.enable_password_enc</HelpCode>). The token is an
          ordinary string — it is safe to store in Git or on disk.{" "}
          <HelpCode>parsed.*</HelpCode> and <HelpCode>run_input.*</HelpCode> are
          reserved and rejected.
        </p>
      </HelpSection>

      <HelpSection title="credential_reference">
        <p>
          Name of a <span className="font-medium text-foreground">Shared Secret</span>{" "}
          credential from Settings → Credential vault. Only the name is stored in
          the workflow; the passphrase is resolved at run time.
        </p>
      </HelpSection>

      <HelpSection title="algorithm">
        <p>
          Leave as <HelpCode>Use credential default</HelpCode> to inherit the
          algorithm configured on the credential, or pick one explicitly to
          override it for this node.
        </p>
      </HelpSection>

      <HelpSection title="Test Encryption">
        <p>
          Opens a modal that encrypts a sample value with a shared secret you type
          in, so you can verify the output before wiring a full workflow. Nothing
          is read from or written to the vault.
        </p>
      </HelpSection>

      <HelpWarning title="A device with no source value is skipped">
        <p>
          If <HelpCode>source_path</HelpCode> resolves to nothing for a device,
          that device passes through unchanged (no ciphertext is written). If it
          resolves to a <em>sealed</em> secret, the device is routed to{" "}
          <HelpCode>failure</HelpCode> instead of failing the run.
        </p>
      </HelpWarning>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the
            device was encrypted, or skipped because the source resolved to
            nothing.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — the
            source was a sealed secret, or encryption failed. The device carries a{" "}
            <HelpCode>DeviceError</HelpCode> (<HelpCode>{"{error.message}"}</HelpCode>,{" "}
            <HelpCode>{"{error.code}"}</HelpCode>) for a downstream notify step.
          </li>
        </ul>
        <p>
          Missing path/credential or an unknown algorithm override still fail the
          step outright.
        </p>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Create a Shared Secret credential in the credential vault.</li>
          <li>
            Set <HelpCode>source_path</HelpCode> to the cleartext value and{" "}
            <HelpCode>destination_path</HelpCode> to where the token should land.
          </li>
          <li>
            Follow with <span className="font-medium text-foreground">Render Jinja
            Template</span> / <span className="font-medium text-foreground">Store
            Artifact</span> to persist the token.
          </li>
        </ol>
        <HelpExample>
          source_path: run_input.enable_password
          <br />
          destination_path: secrets.enable_password_enc
        </HelpExample>
      </HelpSection>
    </div>
  );
}
