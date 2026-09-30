"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Add to ISE.
 * Covers every Configuration control with practical examples.
 */
export function AddToIseHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Registers a network device as a new RADIUS/TACACS client in Cisco ISE.
          Use when a device exists in Nautobot or another upstream source but is
          not yet present in ISE, or when onboarding net-new hardware.
        </p>
        <p>
          Each field can be a fixed value or a per-device expression resolved
          from the workflow context (e.g. <HelpCode>{"{name}"}</HelpCode> from
          a Nautobot inventory step).
        </p>
      </HelpSection>

      <HelpSection title="ISE source">
        <p>
          Click{" "}
          <span className="font-medium text-foreground">Configure Source</span>{" "}
          (or Edit Source) and choose a source created under Settings → Sources
          → Cisco ISE. The step stores that source&apos;s ID as{" "}
          <HelpCode>ise_source_id</HelpCode>.
        </p>
        <HelpExample>
          ise_source_id: prod-ise
        </HelpExample>
        <HelpWarning title="Source required">
          <p>
            Without a valid source the step cannot create devices in ISE.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Device name">
        <p>
          <HelpCode>device_name</HelpCode> is the ISE network device name. Use
          a fixed string or an expression from context.
        </p>
        <HelpExample>
          device_name: router1
          <br />
          device_name: {"{name}"}
          <br />
          device_name: {"{name | default('unknown-device')}"}
        </HelpExample>
      </HelpSection>

      <HelpSection title="Description">
        <p>
          <HelpCode>description</HelpCode> is optional text stored on the ISE
          network device record. Use fixed text, or an attribute expression
          resolved per device (use the search button to browse attributes). If
          the expression resolves to nothing, the device is created without a
          description. Leave blank for none.
        </p>
        <HelpExample>
          description: Lab edge router — onboarded by Auxilium Manus
          <br />
          description: {"{nautobot.location.name}"}
        </HelpExample>
      </HelpSection>

      <HelpSection title="IP address">
        <p>
          <HelpCode>ip_address</HelpCode> is the host address ISE uses for the
          device. Registered as a single host — a netmask suffix (e.g.{" "}
          <HelpCode>/24</HelpCode>) is stripped automatically; ISE has no
          separate netmask field, so the device is always stored as{" "}
          <HelpCode>/32</HelpCode>.
        </p>
        <HelpExample>
          ip_address: 10.0.0.1
          <br />
          ip_address: {"{primary_ip4}"}
          <br />
          ip_address: {"{primary_ip4 | default('10.0.0.1')}"}
        </HelpExample>
        <HelpWarning title="Host only">
          <p>
            Do not pass a subnet CIDR expecting ISE to expand it — use Get from
            ISE with resolve_to_devices, or register individual hosts.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="New key">
        <p>
          <HelpCode>new_key</HelpCode> is the initial TACACS+ shared secret for
          the new ISE entry. Fixed value or expression, with optional fallback.
        </p>
        <HelpExample>
          new_key: MySecretKey123
          <br />
          new_key: {"{custom.new_tacacs_key}"}
          <br />
          new_key: {"{custom.new_tacacs_key | default('MySecretKey123')}"}
        </HelpExample>
      </HelpSection>

      <HelpSection title="Device groups">
        <p>
          <HelpCode>device_groups</HelpCode> is a list of full hierarchical ISE
          network device group (NDG) strings. Click the plus button to add a
          row; leave the list empty for no group membership.
        </p>
        <p>
          Each entry must be the complete <HelpCode>#</HelpCode>-delimited path,
          not just the leaf name — same rules as Get from ISE group mode.
        </p>
        <HelpExample>
          device_groups:
          <br />
          {"  "}- Location#All Locations
          <br />
          {"  "}- Location#All Locations#Building1
          <br />
          {"  "}- Device Type#All Device Types#Router
        </HelpExample>
        <HelpWarning title="Full NDG strings required">
          <ul className="list-disc space-y-0.5 pl-4">
            <li>
              <HelpCode>Building1</HelpCode> alone returns nothing — use{" "}
              <HelpCode>Location#All Locations#Building1</HelpCode>.
            </li>
            <li>
              Custom categories repeat the root:{" "}
              <HelpCode>myGroup#myGroup#my-test-001</HelpCode>, not{" "}
              <HelpCode>myGroup#my-test-001</HelpCode>.
            </li>
          </ul>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Debugging: request and response">
        <p>
          After a run, open the run&apos;s device detail view and choose the{" "}
          <span className="font-medium text-foreground">Requests</span> section.
          It shows the exact request body sent to ISE (after{" "}
          <HelpCode>{"{path}"}</HelpCode> resolution) and ISE&apos;s response —
          the new device id on success, or the error ISE returned. It is shown
          for created, already-existing (<HelpCode>exists</HelpCode>) and
          rejected devices. Devices that failed before a request was built (for
          example an unresolved expression) have no entry.
        </p>
        <p>
          This is for inspection only: it is not stored in the attribute bags,
          so later steps and <HelpCode>{"{path}"}</HelpCode> expressions cannot
          read it. The TACACS+ shared secret is shown as{" "}
          <HelpCode>***REDACTED***</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — ISE
            accepted the create for the device. A device whose fields could not
            be resolved, or that ISE rejected for another reason, is marked
            failed on that device but still leaves through this handle.
          </li>
          <li>
            <span className="font-medium text-foreground">exists</span> — ISE
            refused the create because a network device with that name already
            exists. These devices are passed through unchanged.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — the
            step itself failed: ISE could not be reached or authentication
            failed. All devices leave through this handle.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Configure a Cisco ISE source.</li>
          <li>
            After Get from Nautobot (or similar), set{" "}
            <HelpCode>device_name</HelpCode> to <HelpCode>{"{name}"}</HelpCode>{" "}
            and <HelpCode>ip_address</HelpCode> to{" "}
            <HelpCode>{"{primary_ip4}"}</HelpCode>.
          </li>
          <li>
            Add NDG strings for Location / Device Type membership; set{" "}
            <HelpCode>new_key</HelpCode> from a secret or generated value.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
