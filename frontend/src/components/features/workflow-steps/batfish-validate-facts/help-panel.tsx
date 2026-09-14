"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";
import { BATFISH_FACT_KEYS } from "../shared/batfish-fact-keys";

/**
 * Built-in Help tab content for Validate Facts.
 * Covers every Configuration control with practical examples.
 */
export function BatfishValidateFactsHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Checks expected configuration facts against what Batfish actually parsed from
          each device&apos;s config in an already-initialized snapshot, via Batfish&apos;s{" "}
          <HelpCode>validate_facts</HelpCode> question. Every device is checked
          independently and routed to <HelpCode>match</HelpCode> or{" "}
          <HelpCode>mismatch</HelpCode>; a device whose expected facts couldn&apos;t be
          resolved routes to <HelpCode>failure</HelpCode> instead.
        </p>
      </HelpSection>

      <HelpSection title="facts_source: rendered_yaml">
        <p>
          Reads a YAML fragment produced by an upstream Render Jinja Template step (
          <HelpCode>source_step_node_id</HelpCode>, picked from a dropdown of the Render Jinja
          Template steps already on this canvas — it auto-selects when there is exactly one).
          The rendered YAML must have a top-level <HelpCode>nodes</HelpCode> mapping
          keyed by each device&apos;s own name (case-insensitive) — a device whose rendered
          YAML has no matching key routes to <HelpCode>failure</HelpCode>.
        </p>
        <HelpExample>
          {"nodes:"}
          <br />
          {"  as1border1:"}
          <br />
          {"    Hostname: as1border1"}
          <br />
          {"    TACACS_Servers:"}
          <br />
          {"    - 10.0.0.1"}
          <br />
          {"    - 10.0.0.2"}
        </HelpExample>
        <p>
          The typical workflow: Get from Nautobot → Get Nautobot Attributes → Render Jinja
          Template (builds this YAML per device) → Validate Facts.
        </p>
      </HelpSection>

      <HelpSection title="facts_source: field">
        <p>
          Builds a single <HelpCode>{"{fact_key: fact_value}"}</HelpCode> fact per device,
          with no upstream render step needed — useful for a quick single-value check (e.g.
          &quot;does this device have the right TACACS server&quot;).{" "}
          <HelpCode>fact_value</HelpCode> is a Jinja template rendered per device and may
          resolve to a scalar or a YAML/JSON list.
        </p>
        <HelpExample>
          fact_key: TACACS_Servers
          <br />
          fact_value: {"{{ nautobot.custom_fields.tacacs_servers }}"}
        </HelpExample>
      </HelpSection>

      <HelpSection title="Supported fact keys">
        <p className="leading-5">{BATFISH_FACT_KEYS.join(", ")}</p>
      </HelpSection>

      <HelpSection title="output_key">
        <p>
          The aggregate mismatch result (a JSON artifact plus counts) is stored under this
          key in the run&apos;s metadata. Each checked device also gets its own mismatch
          detail (empty on a match) written to{" "}
          <HelpCode>{"device.parsed[\"{node_id}.<output_key>\"]"}</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Gotchas">
        <HelpWarning title="Node names are matched case-insensitively, but exactly">
          <p>
            Batfish canonicalizes hostnames to lowercase internally. This step always
            lowercases node keys before comparing, so casing in your rendered YAML or device
            names never matters — but the name itself must match exactly.
          </p>
        </HelpWarning>
        <HelpWarning title="Never set a top-level 'version' key yourself">
          <p>
            If your rendered YAML includes a <HelpCode>version</HelpCode> key, this step
            drops it before validating — Batfish&apos;s own actual-facts output always uses
            an internal version tag unrelated to any convention you might write in your own
            YAML, and passing one through would make every device appear mismatched.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Querying a network directly">
        <p>
          Leave <HelpCode>batfish_source_id</HelpCode>/<HelpCode>network</HelpCode> blank to
          use the snapshot from an upstream Init Batfish Snapshot step in this run (default).
          Set both to query any network directly — e.g. a production network refreshed
          nightly by a Schedule — with no Init step needed in this workflow.
        </p>
        <p>
          Leave <HelpCode>snapshot</HelpCode> blank to use the most recently created snapshot
          in that network.
        </p>
      </HelpSection>
    </div>
  );
}
