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
          {"version: 1.0"}
          <br />
          {"nodes:"}
          <br />
          {"  lab:"}
          <br />
          {"    Hostname: lab"}
          <br />
          {"    Domain_Name: local.zz"}
          <br />
          {"    NTP:"}
          <br />
          {"      NTP_Servers:"}
          <br />
          {"        - 10.0.0.1"}
          <br />
          {"        - 10.0.0.2"}
          <br />
          {"    Syslog:"}
          <br />
          {"      Logging_Servers:"}
          <br />
          {"        - 192.168.178.254"}
          <br />
          {"      Logging_Source_Interface: Loopback0"}
          <br />
          {"    Interfaces:"}
          <br />
          {"      Ethernet0/0:"}
          <br />
          {"        Active: true"}
          <br />
          {"      Loopback0:"}
          <br />
          {"        Active: true"}
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
          &quot;does this device have the right domain name&quot;).{" "}
          <HelpCode>fact_value</HelpCode> is a Jinja template rendered per device and may
          resolve to a scalar or a YAML/JSON list.
        </p>
        <HelpExample>
          fact_key: Domain_Name
          <br />
          fact_value: {"{{ nautobot.custom_fields.domain_name }}"}
        </HelpExample>
        <HelpWarning title="Some fact keys don't work in field mode">
          <p>
            This mode always writes <HelpCode>fact_key</HelpCode> as a flat, top-level field.
            That only matches Batfish&apos;s actual facts for keys that stay top-level
            (<HelpCode>Hostname</HelpCode>, <HelpCode>Domain_Name</HelpCode>,{" "}
            <HelpCode>Configuration_Format</HelpCode>, <HelpCode>VRFs</HelpCode>,{" "}
            <HelpCode>Zones</HelpCode>, the access-list/routing-policy list keys, etc.). Keys
            Batfish nests under a category — <HelpCode>NTP_Servers</HelpCode>,{" "}
            <HelpCode>NTP_Source_Interface</HelpCode>, <HelpCode>Logging_Servers</HelpCode>,{" "}
            <HelpCode>Logging_Source_Interface</HelpCode>, <HelpCode>TACACS_Servers</HelpCode>,{" "}
            <HelpCode>TACACS_Source_Interface</HelpCode>, <HelpCode>SNMP_Trap_Servers</HelpCode>,{" "}
            <HelpCode>SNMP_Source_Interface</HelpCode>, <HelpCode>DNS_Servers</HelpCode>,{" "}
            <HelpCode>DNS_Source_Interface</HelpCode>, and the IKE/IPsec keys — will never match
            here. Use <HelpCode>rendered_yaml</HelpCode> or <HelpCode>git</HelpCode> for those,
            with the nested shape shown above.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="facts_source: git">
        <p>
          Reads expected-facts YAML files from a Git repository (
          <HelpCode>git_repository_id</HelpCode>, <HelpCode>base_path</HelpCode>,{" "}
          <HelpCode>glob_pattern</HelpCode>) instead of an upstream step or an inline field —
          useful when expected facts are authored as data files in the same repository a
          config-backup or intended-state job already writes into. Every matched file must have
          the same top-level <HelpCode>nodes</HelpCode> mapping shape as{" "}
          <HelpCode>rendered_yaml</HelpCode>; all matched files&apos; node maps are merged into
          one corpus before any device is checked — later files (sorted by path) win on a
          node-key collision.
        </p>
        <HelpWarning title="A malformed matched file fails the whole step, not just one device">
          <p>
            Unlike <HelpCode>rendered_yaml</HelpCode> (where a bad artifact only fails the one
            device that owns it), a file that fails to parse, or lacks a top-level{" "}
            <HelpCode>nodes</HelpCode> mapping, fails the entire step before any device is
            checked. A device whose name simply isn&apos;t present in the resolved corpus still
            fails individually with <HelpCode>node_key_mismatch</HelpCode>, same as{" "}
            <HelpCode>rendered_yaml</HelpCode>.
          </p>
        </HelpWarning>
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
        <HelpWarning title="Some keys must be nested under a category, not written flat">
          <p>
            This is Batfish&apos;s own convention, not something this step adds: its actual
            facts group <HelpCode>NTP_Servers</HelpCode>/<HelpCode>NTP_Source_Interface</HelpCode>{" "}
            under <HelpCode>NTP</HelpCode>; <HelpCode>Logging_Servers</HelpCode>/
            <HelpCode>Logging_Source_Interface</HelpCode> under <HelpCode>Syslog</HelpCode>;{" "}
            <HelpCode>TACACS_Servers</HelpCode>/<HelpCode>TACACS_Source_Interface</HelpCode> under{" "}
            <HelpCode>TACACS</HelpCode>; <HelpCode>SNMP_Trap_Servers</HelpCode>/
            <HelpCode>SNMP_Source_Interface</HelpCode> under <HelpCode>SNMP</HelpCode>;{" "}
            <HelpCode>DNS_Servers</HelpCode>/<HelpCode>DNS_Source_Interface</HelpCode> under{" "}
            <HelpCode>DNS</HelpCode>; and the IKE/IPsec keys under <HelpCode>IPsec</HelpCode>.
            Expected-facts YAML is never reorganized to match — write these keys nested exactly
            as Batfish does (see the example above), or they&apos;ll always report{" "}
            <HelpCode>key_present: false</HelpCode> even when the device is actually correct.
            Plain keys like <HelpCode>Hostname</HelpCode>, <HelpCode>Domain_Name</HelpCode>, and{" "}
            <HelpCode>Interfaces</HelpCode> stay flat/top-level and are unaffected.
          </p>
          <p>
            Not sure of the exact nested shape for a given fact? Run an{" "}
            <span className="font-medium text-foreground">Extract Facts</span> step against a
            real device first — its output shows precisely how Batfish structures every fact
            for that node. Copy that structure straight into your expected-facts YAML.
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
