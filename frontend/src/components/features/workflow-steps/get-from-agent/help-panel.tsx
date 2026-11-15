"use client";

import {
  FanOutHelpSection,
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/** Help tab for Get from Agent: every Configuration control with examples. */
export function GetFromAgentHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Asks an external agent for the devices of the workflow. The agent is a small Python
          service configured under Settings → Sources → Agents; it runs one named handler, which
          builds the device list from the attributes you send. The returned rows become workflow
          targets exactly like the rows of Get from List.
        </p>
      </HelpSection>

      <HelpSection title="agent_source_id">
        <p>
          The agent to call. The status line under the selector shows whether the agent is
          reachable. Agents are created under Settings → Sources → Agents.
        </p>
      </HelpSection>

      <HelpSection title="handler">
        <p>
          Name of the handler the agent runs (letters, digits, <HelpCode>_</HelpCode>,{" "}
          <HelpCode>.</HelpCode>, <HelpCode>-</HelpCode>). The app sends data, never code. The
          handler must answer with a <HelpCode>devices</HelpCode> list:
        </p>
        <HelpExample>
          {`{"devices": [
  {"name": "ber-sw01", "ip_address": "10.1.0.11", "network_driver": "cisco_ios"},
  {"name": "ber-sw02"}
]}`}
        </HelpExample>
        <p>
          Each row needs a <HelpCode>name</HelpCode> and/or an <HelpCode>ip_address</HelpCode>.{" "}
          <HelpCode>network_driver</HelpCode> defaults to <HelpCode>cisco_ios</HelpCode>. No
          other key is accepted next to <HelpCode>devices</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="attributes">
        <p>
          Name/value rows the agent receives as <HelpCode>inputs[&quot;attributes&quot;]</HelpCode>.
          Use them to tell the handler which devices to return. A value is fixed text, or a whole
          value reference to a run input, which an operator or a schedule supplies for each run.
        </p>
        <HelpExample>
          {`site  = berlin
role  = {run_input.role}`}
        </HelpExample>
        <p>
          Names may contain letters, digits, <HelpCode>_</HelpCode> and <HelpCode>-</HelpCode> and
          must be unique.
        </p>
        <HelpWarning title="Secrets are never sent">
          <p>
            Names that look like secrets (password, token, key, …) and secret-type run inputs fail
            the step.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="timeout_seconds">
        <p>
          How long to wait for the answer (1–600). It may not exceed the maximum set on the agent
          source.
        </p>
      </HelpSection>

      <HelpSection title="When the step fails">
        <p>
          An unreachable agent, a handler error, a malformed answer, one invalid row or an empty
          list all fail the step, so a workflow never runs on a partial inventory.
        </p>
      </HelpSection>

      <FanOutHelpSection />
    </div>
  );
}
