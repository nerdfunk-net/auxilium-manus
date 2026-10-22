"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "@/components/features/workflow-steps/shared/step-help";

export function RouteToAgentHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Sends the attributes and content you select, one request per device, to an{" "}
          <span className="font-medium text-foreground">agent</span>: a Python service you run
          that executes a named handler and returns JSON. The declared keys of the answer are
          written to <HelpCode>destination_path</HelpCode>, so later steps can use them like any
          other attribute.
        </p>
        <p>
          Typical use: send the Nautobot attributes to an agent whose code derives a location
          name, then route or render on <HelpCode>agent.geo.location</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Security">
        <p>
          Every message is encrypted and authenticated with a secret shared between the app and
          that agent, over HTTP (agent on the same Docker host) or Redis (agent on another host).
          The Redis keys and the content stay unreadable even to other Redis users. The app never
          sends code; the agent only runs handlers it already contains.
        </p>
        <HelpWarning title="Secrets are never sent">
          Only the inputs you select leave the app, and secrets are not among them. A path that
          is, contains or lies within known secret data (for example{" "}
          <HelpCode>nautobot.config_context</HelpCode>, or the whole bag{" "}
          <HelpCode>nautobot</HelpCode> that includes it) or has a segment such as{" "}
          <HelpCode>password</HelpCode> fails the step at start: select the specific non-secret
          values instead. A sealed secret, or a value under a key such as{" "}
          <HelpCode>password</HelpCode> inside a selected structure, fails that device with code{" "}
          <HelpCode>source_sealed</HelpCode> or <HelpCode>source_secret</HelpCode>.
        </HelpWarning>
      </HelpSection>

      <HelpSection title="What the handler receives">
        <HelpExample>{`handle(params, inputs)

params = {"strict": true}
inputs = {
  "attributes": {"nautobot.location.name": "Berlin-DC1"},
  "content": {"running_config": "hostname r1\\n..."}
}`}</HelpExample>
        <p>
          Paths that do not resolve on a device are left out of{" "}
          <HelpCode>attributes</HelpCode>; content a device does not have is left out of{" "}
          <HelpCode>content</HelpCode>. The output of a Run Command step arrives as a list of{" "}
          <HelpCode>{`{"command", "output"}`}</HelpCode> entries in execution order, so a
          command that ran twice appears twice.
        </p>
      </HelpSection>

      <HelpSection title="What the handler returns">
        <p>
          A JSON object. Only the keys listed in <HelpCode>output_keys</HelpCode> are accepted:
          an extra key, a missing key (unless <HelpCode>allow_missing_outputs</HelpCode> is set),
          a key with a dot in its name, a value above{" "}
          <HelpCode>STEP_OUTPUT_VALUE_MAX_BYTES</HelpCode> or one nested deeper than 8 levels
          fails that device with code <HelpCode>output_rejected</HelpCode>.
        </p>
        <HelpExample>{`{"location": "Berlin"}   ->   agent.geo.location = "Berlin"`}</HelpExample>
      </HelpSection>

      <HelpSection title="destination_path">
        <p>
          <HelpCode>bag.field</HelpCode>, for example <HelpCode>agent.geo</HelpCode>. The agent
          cannot change the device itself: paths starting with <HelpCode>device</HelpCode>, a
          device field such as <HelpCode>name</HelpCode>, <HelpCode>parsed</HelpCode>,{" "}
          <HelpCode>run_input</HelpCode> or <HelpCode>error</HelpCode> are rejected.
        </p>
      </HelpSection>

      <HelpSection title="Outcomes and failures">
        <p>
          Devices the agent answered go to <HelpCode>success</HelpCode>; the others go to{" "}
          <HelpCode>failure</HelpCode> with a code such as <HelpCode>agent_offline</HelpCode>,{" "}
          <HelpCode>agent_timeout</HelpCode>, <HelpCode>agent_auth_failed</HelpCode>,{" "}
          <HelpCode>agent_handler_error</HelpCode>, <HelpCode>payload_too_large</HelpCode> or{" "}
          <HelpCode>output_rejected</HelpCode>.
        </p>
        <p>
          If the agent is offline or rejects the shared secret, the devices not yet sent fail
          immediately with the same cause instead of waiting for a timeout each. An answer that
          arrives too late counts only as a timeout for that device. Calls to one agent run in
          parallel up to the agent&apos;s limit (Settings → Sources), and{" "}
          <HelpCode>timeout_seconds</HelpCode> above that agent&apos;s maximum fails the step.
        </p>
        <HelpWarning title="Handler error messages are shown">
          When a handler raises, its exception class and message (200 characters at most) are
          stored on the device and shown in the run view. Do not put secrets or device content
          into exception messages.
        </HelpWarning>
      </HelpSection>
    </div>
  );
}
