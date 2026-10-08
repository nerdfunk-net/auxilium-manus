"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Send Mail.
 * Covers every Configuration control with practical examples.
 */
export function SendMailHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Sends one email through an SMTP server — one message per step
          execution, not one per device. Use it to report that a workflow
          finished or that something needs attention.
        </p>
      </HelpSection>

      <HelpSection title="smtp_server / smtp_port">
        <p>
          Hostname or IP address and TCP port of the SMTP server. The usual
          port depends on <HelpCode>security</HelpCode>: 25 for none, 587 for
          STARTTLS, 465 for SSL/TLS. Changing the protocol moves the port to
          that protocol&apos;s usual port, unless you already typed a custom
          one.
        </p>
        <HelpExample>
          smtp_server: smtp.example.com
          <br />
          smtp_port: 587
        </HelpExample>
      </HelpSection>

      <HelpSection title="security">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">None</span> — plain,
            unencrypted SMTP. Only for a trusted internal relay.
          </li>
          <li>
            <span className="font-medium text-foreground">STARTTLS</span> —
            connects in plain text, then upgrades to TLS before logging in or
            sending. The right choice for port 587.
          </li>
          <li>
            <span className="font-medium text-foreground">SSL/TLS</span> —
            TLS from the first byte (implicit TLS), usually port 465.
          </li>
        </ul>
        <p>
          For STARTTLS and SSL/TLS the server certificate is verified by
          default; a self-signed certificate makes the step fail with{" "}
          <HelpCode>SSLCertVerificationError</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="verify_tls (Validate TLS certificate)">
        <p>
          On by default. Untick it for a server that presents a self-signed
          certificate, such as a local Proton Mail Bridge (host{" "}
          <HelpCode>127.0.0.1</HelpCode>, STARTTLS). The connection is still
          encrypted, but the server&apos;s identity is no longer checked.
          Hidden when security is None, because nothing is encrypted then.
        </p>
        <HelpWarning title="Only for trusted local connections">
          <p>
            With verification off, anyone able to intercept the connection can
            impersonate the server and read the credential. Prefer a real
            certificate for any server reached over a network.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="credential_reference">
        <p>
          A Basic Auth credential from the vault (Settings → Credentials) whose
          username and password are used to log in. SSH credentials are not
          accepted. Only the credential&apos;s name is
          stored on the step — never the password. Choose{" "}
          <span className="font-medium text-foreground">No authentication</span>{" "}
          for a relay that needs no login.
        </p>
        <HelpWarning title="No login over plain SMTP">
          <p>
            With <HelpCode>security: none</HelpCode> the username and password
            would travel unencrypted, so the step refuses to run. Use STARTTLS
            or SSL/TLS whenever a credential is selected.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="from_address / to">
        <p>
          Sender and recipient addresses. <HelpCode>to</HelpCode> accepts
          several addresses separated by commas or semicolons. Both support{" "}
          <HelpCode>{"{path.to.value}"}</HelpCode> placeholders resolved
          against the first device, so the recipient can come from device data.
        </p>
        <HelpExample>
          from_address: manus@example.com
          <br />
          to: ops@example.com; {"{custom.owner_email}"}
        </HelpExample>
      </HelpSection>

      <HelpSection title="subject / body">
        <p>
          Both support placeholders. In the{" "}
          <span className="font-medium text-foreground">subject</span>,{" "}
          <HelpCode>{"{path.to.value}"}</HelpCode> resolves against the first
          device (it must stay a single line). In the{" "}
          <span className="font-medium text-foreground">body</span> it is
          rendered once per device and the results are joined with newlines.
        </p>
        <p>
          <HelpCode>{"{devices}"}</HelpCode> renders every device name,
          comma-joined; <HelpCode>{"{device_count}"}</HelpCode> renders the
          count. A path that doesn&apos;t resolve renders as an empty string.
        </p>
        <HelpExample>
          subject: Config backup failed on {"{device.name}"}
          <br />
          <span className="text-muted-foreground">
            → Config backup failed on router1
          </span>
        </HelpExample>
        <HelpExample>
          body: {"{device.name}"} ({"{nautobot.location.name}"})
          <br />
          <span className="text-muted-foreground">
            → router1 (core)
            <br />→ router2 (edge)
          </span>
        </HelpExample>
        <HelpWarning title="Nothing to report">
          <p>
            If the subject, body or an address needs a device attribute but no
            device reaches this step (for example it is wired to an outcome
            that matched nothing), the step sends no mail and reports success.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the
            server accepted the message (or there was nothing to report).
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — the
            mail could not be sent: server unreachable, TLS or login failed,
            or a recipient was rejected. The step summary shows the error
            type and SMTP status code only.
          </li>
        </ul>
        <p>
          Invalid configuration (missing field, bad port, invalid address)
          fails the step itself.
        </p>
      </HelpSection>

      <HelpSection title="Fan-out">
        <p>
          Place this step after a <HelpCode>Fan In</HelpCode> node for one mail
          covering every device in the run. Placed inside fan-out children it
          sends once per child branch.
        </p>
      </HelpSection>
    </div>
  );
}
