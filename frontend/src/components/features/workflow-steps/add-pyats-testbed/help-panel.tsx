"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Add Testbed.
 * Covers every Configuration control with practical examples.
 */
export function AddPyatsTestbedHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Resolves a credential and a pyATS shim source once for every device
          in the current selection, and writes a reusable connection bundle
          into each device&apos;s <HelpCode>pyats_testbed</HelpCode> attribute
          bag (host, os, username, and an encrypted password). Downstream
          pyATS-backed steps — like Get & Parse Config — read this bundle
          instead of asking for their own credential or source.
        </p>
        <HelpWarning title="Requires an upstream inventory step">
          <p>
            This step needs a device list — connect it after a Get from
            Nautobot, Get from List, or similar inventory step.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Using this step with fan-out">
        <p>
          Place this step directly after the inventory step, inside the
          fan-out branch, and before the pyATS steps that need it. The
          pyATS steps send the devices of one fan-out child to the shim as a
          single job (up to 5 devices per job), and every job pays pyATS&apos;s
          start-up cost once.
        </p>
        <HelpWarning title="Use Chunked fan-out, not Per device">
          <p>
            With <HelpCode>mode: per_device</HelpCode> each child holds one
            device, so every pyATS job runs for a single device and the
            batching never applies. Set the fan-out of the inventory step to{" "}
            <HelpCode>mode: chunked</HelpCode> with a{" "}
            <HelpCode>chunk_size</HelpCode> of about 5 to 10. Keep chunks
            small: the devices of a chunk are processed one after another
            inside one pyATS job.
          </p>
        </HelpWarning>
        <HelpExample>
          Get from Nautobot (fan-out: chunked, chunk_size: 5)
          <br />
          <span className="text-muted-foreground">
            → Add Testbed → Get &amp; Parse Config
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="pyats_source_id">
        <p>
          The pyATS shim source (configured under Settings → Sources) that
          downstream steps will call. Click{" "}
          <span className="font-medium text-foreground">Configure Source</span>{" "}
          to pick one.
        </p>
      </HelpSection>

      <HelpSection title="credential_reference">
        <p>
          A username/password credential from Settings → Credentials — either{" "}
          <HelpCode>ssh</HelpCode> or <HelpCode>generic</HelpCode> type both
          work, since the shim only needs a plain username/password over
          HTTP, not an SSH key.
        </p>
      </HelpSection>

      <HelpSection title="network_driver_override">
        <p>
          Optional. Overrides the pyATS <HelpCode>os</HelpCode> value
          resolved from each device&apos;s network driver / platform — useful
          when a device&apos;s Nautobot platform doesn&apos;t map cleanly.
        </p>
        <HelpExample>
          network_driver_override: iosxe
          <br />
          <span className="text-muted-foreground">
            → every device in this step uses os: iosxe, regardless of its own
            platform
          </span>
        </HelpExample>
      </HelpSection>
    </div>
  );
}
