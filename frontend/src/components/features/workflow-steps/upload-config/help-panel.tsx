"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Upload Config.
 * Covers every Configuration control with practical examples.
 */
export function UploadConfigHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Connects to each device over SSH and pushes a text file — the content
          produced by an earlier step, such as an Update Content edit — to the
          device&apos;s filesystem using Netmiko&apos;s secure-copy (SCP/SFTP)
          <HelpCode>file_transfer</HelpCode>, or its inline (non-SCP) text transfer
          mode.
        </p>
        <p>
          Requires devices from an upstream inventory step, a step earlier in the
          workflow producing the content to upload, and a valid SSH credential from
          Settings → Credentials.
        </p>
      </HelpSection>

      <HelpSection title="Credential reference">
        <p>
          Select an SSH credential from the dropdown. The step stores{" "}
          <HelpCode>credential_reference</HelpCode> as the credential&apos;s name
          (not its internal ID). Username and password/key are resolved at run time.
        </p>
        <HelpExample>
          credential_reference: prod-ssh-admin
          <br />
          <span className="text-muted-foreground">
            → uses username/password from Settings → Credentials
          </span>
        </HelpExample>
        <HelpWarning title="SSH credential required">
          <p>
            The step cannot connect without a non-expired SSH credential. Create one
            under Settings → Credentials if the dropdown is empty.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Content source">
        <p>
          <HelpCode>content_source</HelpCode> picks which upstream content to upload.
          The default, <span className="font-medium text-foreground">Updated content</span>,
          reads the result of an Update Content step. Other sources — running/startup
          config, command output, a rendered template, and more — are also supported
          for uploading content produced anywhere else in the workflow.
        </p>
        <p>
          <span className="font-medium text-foreground">Running configuration</span> reads
          whichever step last set the device&apos;s <HelpCode>running_config_ref</HelpCode> —
          Get Configs (live fetch) or Read Config (from disk/git) both populate it, so either one
          upstream is enough; no <HelpCode>source_step_node_id</HelpCode> is needed.
        </p>
        <p>
          Sources other than running/startup config and latest command output need{" "}
          <HelpCode>source_step_node_id</HelpCode> to pick which upstream step&apos;s
          output to use. When exactly one matching step exists in the workflow, it is
          selected automatically. Use <HelpCode>parsed_output_key</HelpCode> to
          disambiguate when a source step could produce more than one output (rendered
          template / pyATS snapshot only).
        </p>
        <HelpExample>
          content_source: updated_content
          <br />
          source_step_node_id: update-content-3
        </HelpExample>
      </HelpSection>

      <HelpSection title="Destination filename and filesystem">
        <p>
          <HelpCode>destination_filename</HelpCode> is the name the file is written
          under on the device. <HelpCode>file_system</HelpCode> is the destination
          filesystem — the value Netmiko&apos;s SCP transfer expects, e.g.{" "}
          <HelpCode>bootflash:</HelpCode>, <HelpCode>flash:</HelpCode>, or{" "}
          <HelpCode>nvram:</HelpCode> — and is platform-specific.
        </p>
        <HelpExample>
          destination_filename: startup-config-new.cfg
          <br />
          file_system: bootflash:
        </HelpExample>
      </HelpSection>

      <HelpSection title="Overwrite">
        <p>
          When <HelpCode>overwrite</HelpCode> is off (default), the transfer fails if
          a file already exists at the destination path. Enable it to replace an
          existing file.
        </p>
        <HelpWarning title="Destructive when enabled">
          <p>
            Enabling <HelpCode>overwrite</HelpCode> replaces the existing file on the
            device with no confirmation prompt. Only enable this when overwriting is
            intentional.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Inline transfer">
        <p>
          <HelpCode>inline_transfer</HelpCode> switches from Netmiko&apos;s SCP/SFTP
          file transfer to its inline (non-SCP) mode, which sends the file content as
          text over the CLI session instead of opening a separate SCP/SFTP channel.
          Use this when the device has no SCP server enabled, or for small text-only
          files. It does not work for binary files.
        </p>
        <HelpExample>
          inline_transfer: true
          <br />
          <span className="text-muted-foreground">
            → no SCP/SFTP subsystem required on the device
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Verify uploaded content">
        <p>
          <HelpCode>verify_content</HelpCode> compares a checksum computed locally over
          the uploaded content against the checksum the device itself computes for the
          file it just stored. When enabled, choose <HelpCode>verify_algorithm</HelpCode>{" "}
          — <span className="font-medium text-foreground">MD5</span> (default) or{" "}
          <span className="font-medium text-foreground">SHA-512</span>. After the
          transfer, the step runs the device&apos;s own{" "}
          <HelpCode>verify /&lt;algorithm&gt; &lt;file_system&gt;&lt;destination_filename&gt;</HelpCode>{" "}
          command and parses the fingerprint out of its output, ignoring everything
          else (banner lines, progress dots, etc.).
        </p>
        <HelpExample>
          verify_content: true
          <br />
          verify_algorithm: md5
          <br />
          <span className="text-muted-foreground">
            → runs: verify /md5 bootflash:startup-config-new.cfg
          </span>
        </HelpExample>
        <p>
          If the device&apos;s checksum doesn&apos;t match, or its output can&apos;t be
          parsed, the device is routed out the <HelpCode>failure</HelpCode> outcome even
          though the file transfer itself succeeded.
        </p>
        <HelpWarning title="Cisco IOS / IOS-XE always append an extra newline">
          <p>
            Cisco IOS and IOS-XE unconditionally add one more{" "}
            <span className="font-mono">\n</span> to whatever bytes were sent when
            storing a text file — on top of any newline the uploaded content already
            ended with. If the content already ended with a newline (the usual case),
            the stored file ends with a trailing blank line;{" "}
            <HelpCode>more</HelpCode> shows this as identical either way. On those
            platforms the step accounts for this automatically before comparing
            checksums. This adjustment only applies when the device&apos;s driver is{" "}
            <HelpCode>cisco_ios</HelpCode> or <HelpCode>cisco_xe</HelpCode>; other
            platforms are compared byte-for-byte.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Network driver override">
        <p>
          <HelpCode>network_driver_override</HelpCode> replaces each device&apos;s
          inferred Netmiko driver for this step only. Leave empty to use the driver
          from device context (usually set by inventory or platform metadata).
        </p>
        <HelpExample>
          network_driver_override: cisco_ios
          <br />
          <span className="text-muted-foreground">
            → forces Netmiko cisco_ios even if context says otherwise
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Socket timeout">
        <p>
          <HelpCode>socket_timeout</HelpCode> is how many seconds the SCP/SFTP
          transfer waits before giving up. Raise this for large configuration files
          or slow links.
        </p>
        <HelpExample>
          socket_timeout: 30
          <br />
          <span className="text-muted-foreground">
            → waits up to 30s for the transfer instead of the 10s default
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the file
            was uploaded to the device.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — SSH
            connection failed, no matching content was found for the configured
            source, the transfer itself failed (e.g. SCP disabled on the device,
            or the destination already exists and overwrite is off), or — when{" "}
            <HelpCode>verify_content</HelpCode> is enabled — the device&apos;s checksum
            didn&apos;t match or couldn&apos;t be parsed.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Ensure devices are in context from an inventory step.</li>
          <li>Chain this step after Get Configs → Update Content.</li>
          <li>Select an SSH credential.</li>
          <li>
            Confirm the content source is Updated content and points at the Update
            Content step.
          </li>
          <li>Set the destination filename and filesystem for the target platform.</li>
        </ol>
      </HelpSection>
    </div>
  );
}
