"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Merge Config.
 * Covers every Configuration control with practical examples.
 */
export function MergeConfigHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Connects to each device in the workflow context over SSH and runs{" "}
          <HelpCode>copy &lt;source_filename&gt; running-config</HelpCode>,
          answering the{" "}
          <HelpCode>Destination filename [running-config]?</HelpCode> prompt
          with Enter. The file&apos;s lines are <strong>layered onto</strong>{" "}
          the running config in the device&apos;s non-interactive batch mode —
          this is an additive merge, not a replace, and there is no rollback
          timer. Lines already on the device that the file doesn&apos;t mention
          are left untouched.
        </p>
        <p>
          Use this step when the staged file is a <strong>partial</strong>{" "}
          config — a rendered Jinja template covering only a few sections, an
          ACL snippet, a handful of <HelpCode>interface</HelpCode> blocks. It
          requires devices from an upstream inventory step, a valid SSH
          credential from Settings → Credentials, and the file already present
          on the device (stage it with an upstream Upload Config step).
        </p>
      </HelpSection>

      <HelpSection title="Merge Config vs Configure Replace Config">
        <p>
          These are the two config-deploy steps; pick by what the file contains.
        </p>
        <p>
          <span className="font-medium">Merge Config</span> (this step) — the
          file holds only the lines that changed. It runs{" "}
          <HelpCode>copy … running-config</HelpCode> over SSH, adds those lines,
          and changes nothing else. No rollback timer.
        </p>
        <p>
          <span className="font-medium">Configure Replace Config</span> — the
          file is a <span className="font-medium">complete</span> device config
          (a full, edited <HelpCode>show running-config</HelpCode>). It runs{" "}
          <HelpCode>configure replace … force time N</HelpCode> +{" "}
          <HelpCode>configure confirm</HelpCode> so the running config ends up
          matching the file exactly, with a device-native rollback timer.
          Feeding it a partial file fails the step.
        </p>
      </HelpSection>

      <HelpSection title="Credential reference">
        <p>
          <span className="font-medium">Fixed</span> — pick an SSH credential by
          vault name. <span className="font-medium">Run parameter</span> — read
          the credential vault name from a run parameter (a workflow static
          attribute of type reference, ref kind credential), resolved per
          triggering user so one workflow can run under different teams&apos;
          credentials per schedule.
        </p>
      </HelpSection>

      <HelpSection title="source_filename">
        <p>
          The path passed verbatim to{" "}
          <HelpCode>copy &lt;source_filename&gt; running-config</HelpCode>,
          including the device filesystem prefix. It must match the file an
          upstream Upload Config step wrote (its{" "}
          <HelpCode>file_system</HelpCode> +{" "}
          <HelpCode>destination_filename</HelpCode>).
        </p>
        <HelpExample>
          flash:partial.cfg
          {"\n"}
          bootflash:snippets/acl-update.cfg
        </HelpExample>
      </HelpSection>

      <HelpSection title="network_driver_override">
        <p>
          Overrides each device&apos;s Netmiko device type for this step only.
          Leave blank to use the device&apos;s own network driver / platform.
          Example: <HelpCode>cisco_ios</HelpCode>, <HelpCode>cisco_xe</HelpCode>
          .
        </p>
      </HelpSection>

      <HelpSection title="read_timeout">
        <p>
          Seconds to wait for the prompt and for the device&apos;s response
          before failing with a Netmiko &ldquo;Pattern not detected&rdquo;
          timeout (5–600, default 60). Raise it for large files or slow devices.
        </p>
      </HelpSection>

      <HelpWarning title="The prompt is always auto-answered">
        <p>
          This step always presses Enter for the{" "}
          <HelpCode>Destination filename [running-config]?</HelpCode> prompt
          (and, defensively, for an unexpected extra{" "}
          <HelpCode>[confirm]</HelpCode> prompt, up to an internal limit). There
          is no opt-out. Only point it at files you have reviewed.
        </p>
      </HelpWarning>

      <HelpSection title="Outcomes">
        <p>
          <span className="font-medium">success</span> — the copy completed, the
          device returned to its prompt, and the transcript contained no{" "}
          <HelpCode>%Error</HelpCode>, <HelpCode>Invalid input</HelpCode>, or{" "}
          <HelpCode>%Warning</HelpCode> line. The full CLI transcript is stored
          as a <HelpCode>command_output</HelpCode> artifact.
        </p>
        <p>
          <span className="font-medium">failure</span> — SSH connect / auth
          error, missing credential, device has no hostname or IP, the copy
          reported an error / warning line, or the prompts never cleared within
          the internal answer limit.
        </p>
      </HelpSection>

      <HelpSection title="Typical setup">
        <HelpExample>
          Get Devices → Upload Config (destination_filename partial.cfg,
          file_system flash:)
          {"\n"}
          {"  "}→ Merge Config (source_filename flash:partial.cfg)
          {"\n"}
          {"  "}→ Get Configs / Compare Data (optional verification)
        </HelpExample>
      </HelpSection>
    </div>
  );
}
