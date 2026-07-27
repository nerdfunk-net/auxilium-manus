"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Deploy rendered Template.
 * Covers every Configuration control with practical examples.
 */
export function DeployRenderedTemplateHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Connects to each device over SSH and executes the commands produced by an
          upstream Render Jinja Template step — the same rendered config the user
          built from Nautobot config/attributes plus variables. Optionally saves the
          running configuration to startup afterward.
        </p>
        <p>
          Requires devices from an upstream inventory step, a Render Jinja Template
          step earlier in the workflow, and a valid SSH credential from Settings →
          Credentials.
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

      <HelpSection title="Source step / rendered template">
        <p>
          <HelpCode>source_step_node_id</HelpCode> picks which Render Jinja Template
          step&apos;s output to deploy. When exactly one Render Jinja Template step
          exists in the workflow, it is selected automatically. Use{" "}
          <HelpCode>parsed_output_key</HelpCode> to disambiguate when a render step
          could produce more than one output; leave it empty to use the template
          produced by the selected step.
        </p>
        <HelpExample>
          source_step_node_id: render-jinja-template-3
          <br />
          parsed_output_key: device_config
        </HelpExample>
      </HelpSection>

      <HelpSection title="Execution mode">
        <p>
          <HelpCode>execution_mode</HelpCode> controls how rendered lines are sent:{" "}
          <span className="font-medium text-foreground">Configuration mode</span>{" "}
          enters config mode once, sends every rendered line, then exits — the right
          choice for pushing device configuration (interface stanzas, ACL lines,
          etc.). <span className="font-medium text-foreground">Exec mode</span> sends
          each rendered line individually as an exec-level command, identical
          mechanics to Run Command — use this when the rendered template is a list of
          show/exec commands rather than configuration.
        </p>
        <HelpExample>
          execution_mode: config_mode
          <br />
          <span className="text-muted-foreground">
            → configure terminal → each rendered line → end
          </span>
        </HelpExample>
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

      <HelpSection title="Read timeout">
        <p>
          <HelpCode>read_timeout</HelpCode> is how many seconds the step waits for each
          command&apos;s response before giving up. A Netmiko{" "}
          <HelpCode>&quot;Pattern not detected&quot;</HelpCode> error means a command
          never returned a recognizable prompt within this window — a confirmation
          prompt, a slow or multi-line response, or the device landing in an
          unexpected sub-mode can all cause this. Raise the value rather than retrying
          blindly.
        </p>
        <HelpExample>
          read_timeout: 120
          <br />
          <span className="text-muted-foreground">
            → waits up to 120s per command instead of the 60s default
          </span>
        </HelpExample>
        <HelpWarning title="Diagnosing a timeout">
          <p>
            When a device fails with a pattern-not-detected error, the step stores the
            raw Netmiko session log captured up to the failure as an additional
            artifact on that device (visible alongside the command output in the run
            detail view) — it shows exactly what the device sent back right before the
            timeout.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Auto-confirm prompts">
        <p>
          Some commands raise a Cisco-style interactive confirmation instead of
          returning straight to the prompt — for example{" "}
          <HelpCode>no username kannweg</HelpCode> triggers &ldquo;This operation
          will remove all username related configurations with same
          name.&nbsp;Do you want to continue?&nbsp;[confirm]&rdquo;. By default the
          step has no way to answer this and the command fails with a Netmiko
          &ldquo;Pattern not detected&rdquo; timeout. Enabling{" "}
          <HelpCode>auto_confirm_prompts</HelpCode> presses Enter (the IOS default
          / yes response) whenever this cue appears, for every command in the
          rendered template.
        </p>
        <HelpExample>
          auto_confirm_prompts: true
          <br />
          <span className="text-muted-foreground">
            → &ldquo;...[confirm]&rdquo; is answered automatically; commands that
            never prompt behave exactly as before
          </span>
        </HelpExample>
        <HelpWarning title="This is a blind accept — review before enabling">
          <p>
            Any command that raises a confirmation is accepted with no human in
            the loop, including destructive ones you did not anticipate. Only turn
            this on when every command the template can produce is known and safe
            to auto-accept. Commands that were actually auto-confirmed are recorded
            in the step&apos;s output summary and in the worker logs
            (&ldquo;auto-confirmed N prompt(s)&rdquo;) so you can audit what
            happened after the fact.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Write config after execution">
        <p>
          When <HelpCode>write_config_after_execution</HelpCode> is enabled, the step
          runs <HelpCode>copy running-config startup-config</HelpCode> after a
          successful deployment and automatically confirms any destination-filename
          prompt the device shows. If the deployment itself fails on a device, the
          save step is skipped for that device to avoid persisting a partial or bad
          configuration.
        </p>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the
            rendered template was deployed for the device (and saved, if enabled).
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — SSH
            connection failed, no rendered template was found for the configured
            source step, deployment failed, or the config save failed.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Ensure devices are in context from an inventory step.</li>
          <li>Chain this step after a Render Jinja Template step.</li>
          <li>Select an SSH credential.</li>
          <li>
            Confirm the source step and (optionally) output key; pick the execution
            mode matching the rendered content.
          </li>
          <li>
            Enable write_config_after_execution when the deployment should persist
            across a reload.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
