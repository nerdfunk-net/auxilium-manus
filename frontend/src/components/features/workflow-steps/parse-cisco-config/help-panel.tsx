"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Parse Cisco Config.
 * Covers every Configuration control with practical examples.
 */
export function ParseCiscoConfigHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Parses each device&apos;s running and/or startup configuration (fetched by an
          upstream Get Configs step) into structured data using the cisco-config-parser
          library — hostname, VRFs, VLANs, L2/L3 interfaces, ACLs, prefix lists,
          route maps, FHRP groups, port channels, and routing (static/OSPF/EIGRP/BGP).
          Cisco IOS, IOS-XE, NXOS, and IOS-XR are supported.
        </p>
        <p>
          The parsed result is written to{" "}
          <HelpCode>device.parsed.{"{output_key}"}</HelpCode> for downstream Render
          Jinja Template or Log Attributes steps.
        </p>
      </HelpSection>

      <HelpSection title="Config source">
        <p>
          Choose which fetched config to parse: <HelpCode>running</HelpCode>,{" "}
          <HelpCode>startup</HelpCode>, or <HelpCode>both</HelpCode>. A device is
          routed to <span className="font-medium text-foreground">failure</span> if
          the config it needs was never fetched (add a Get Configs step upstream with
          the matching option enabled).
        </p>
        <HelpExample>
          config_source: both
          <br />
          <span className="text-muted-foreground">
            → parses both device.running_config and device.startup_config
          </span>
        </HelpExample>
        <HelpWarning title="Both requires both configs to succeed">
          <p>
            When <HelpCode>config_source</HelpCode> is <HelpCode>both</HelpCode>, the
            whole device is marked failed if either side fails to parse — there is no
            partial (running-only or startup-only) success.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Output key">
        <p>
          <HelpCode>output_key</HelpCode> names the slot where the parsed model is
          stored on each device. Downstream steps and templates reference{" "}
          <HelpCode>device.parsed.{"{output_key}"}</HelpCode>.
        </p>
        <p>
          When <HelpCode>config_source</HelpCode> is <HelpCode>running</HelpCode> or{" "}
          <HelpCode>startup</HelpCode>, the value at that key is the parsed model
          directly. When it is <HelpCode>both</HelpCode>, the running and startup
          models are nested under <HelpCode>running</HelpCode> /{" "}
          <HelpCode>startup</HelpCode> sub-keys.
        </p>
        <HelpExample>
          output_key: cisco_config
          <br />
          {"{{ parsed.cisco_config.hostname }}"}
          <br />
          {"{{ parsed.cisco_config.vlans }}"}
          <br />
          <span className="text-muted-foreground">
            — with config_source: both, use parsed.cisco_config.running.hostname /
            parsed.cisco_config.startup.hostname
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Using the parsed config downstream">
        <p>
          <HelpCode>parsed.{"{output_key}"}</HelpCode> sits alongside the device&apos;s
          own identity fields — <HelpCode>device.name</HelpCode>,{" "}
          <HelpCode>device.hostname</HelpCode>, <HelpCode>device.primary_ip4</HelpCode> —
          in the same context. A Render Jinja Template or Deploy Rendered Template step
          can reference both together to build a report or a follow-up command that
          says which device it&apos;s about, not just what was parsed off it:
        </p>
        <HelpExample>
          Audit for {"{{ device.name }}"} ({"{{ device.primary_ip4 }}"})
          <br />
          Configured hostname: {"{{ parsed.cisco_config.hostname }}"}
          <br />
          VLANs configured: {"{{ parsed.cisco_config.vlans | length }}"}
        </HelpExample>
        <p>
          Log Attributes can print the same fields for troubleshooting without
          rendering a template — add{" "}
          <HelpCode>device.name</HelpCode>, <HelpCode>device.primary_ip4</HelpCode>, and{" "}
          <HelpCode>parsed.cisco_config.hostname</HelpCode> as the attributes to log.
        </p>
        <HelpWarning title="device.name can just be the IP address">
          <p>
            If the device entered the workflow via Get from List with an IP address and
            no name (no DNS entry, no Nautobot record yet), <HelpCode>device.name</HelpCode>{" "}
            falls back to that IP — it is not the box&apos;s real hostname. Compare it
            with <HelpCode>parsed.{"{output_key}"}.hostname</HelpCode>, which comes from
            the actual <HelpCode>hostname</HelpCode> line in the fetched config, to see
            the device&apos;s true configured name.
          </p>
          <HelpExample>
            Get from List: ip_address: 10.0.0.5{" "}
            <span className="text-muted-foreground">(no name)</span>
            <br />
            → device.name = 10.0.0.5, device.primary_ip4 = 10.0.0.5
            <br />
            → after this step: parsed.cisco_config.hostname = core-sw-1
            <br />
            <span className="text-muted-foreground">
              — the workflow still calls it &quot;10.0.0.5&quot;; the config says
              &quot;core-sw-1&quot;. Use the parsed hostname (e.g. in Add to Nautobot&apos;s
              name field template) once you need the device&apos;s real name.
            </span>
          </HelpExample>
          <p>
            When Get from List instead has{" "}
            <HelpCode>name: router1.example.com</HelpCode> (with or without an IP),{" "}
            <HelpCode>device.name</HelpCode> is that name from the start and usually
            already matches <HelpCode>parsed.{"{output_key}"}.hostname</HelpCode>.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Using parsed data in Route on Attribute / Update Attribute">
        <p>
          Route on Attribute and Update Attribute can also read{" "}
          <HelpCode>parsed.{"{output_key}"}...</HelpCode> paths, not just Jinja
          templates. A leaf holding a scalar (e.g.{" "}
          <HelpCode>parsed.cisco_config.hostname</HelpCode>) can be matched by exact
          value. A leaf holding a list or dict (e.g.{" "}
          <HelpCode>parsed.cisco_config.aaa_servers.servers</HelpCode>, a list of
          configured AAA servers) can&apos;t be matched by value, but Route on
          Attribute can still branch on <HelpCode>{"{exists}"}</HelpCode> /{" "}
          <HelpCode>{"{empty}"}</HelpCode> / <HelpCode>{"{absent}"}</HelpCode> to
          check whether it&apos;s populated at all.
        </p>
        <HelpExample>
          attribute_path: parsed.cisco_config.aaa_servers.servers
          <br />
          routes: [{"{"} outcome: has_tacacs, values: [{"{exists}"}] {"}"}]
          <br />
          <span className="text-muted-foreground">
            → routes devices with at least one parsed AAA server to has_tacacs
          </span>
        </HelpExample>
        <HelpWarning title="Checking for one specific server (or ACL entry)">
          <p>
            To check whether a <span className="font-medium text-foreground">
              specific
            </span>{" "}
            TACACS server (by name or address) is present — not just whether the
            list is non-empty — use the{" "}
            <span className="font-medium text-foreground">List Contains</span> step
            instead of Route on Attribute. For example, to check whether ACL{" "}
            <HelpCode>MGMT_100</HelpCode> permits source{" "}
            <HelpCode>172.16.9.100</HelpCode>:
          </p>
          <HelpExample>
            list_path: parsed.{"{output_key}"}.access_lists[name=MGMT_100].entries
            <br />
            field: source
            <br />
            value: 172.16.9.100
          </HelpExample>
          <p>
            The <HelpCode>[name=MGMT_100]</HelpCode> filter segment picks out one
            ACL by its <HelpCode>name</HelpCode> field before continuing into its{" "}
            <HelpCode>entries</HelpCode> list — see List Contains&apos; help for
            details.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the
            requested config(s) parsed; the model is available at{" "}
            <HelpCode>device.parsed.{"{output_key}"}</HelpCode>. Sections the parser
            doesn&apos;t support for the detected platform are listed under{" "}
            <HelpCode>unsupported</HelpCode>; individual section failures are
            collected under <HelpCode>parse_errors</HelpCode> without failing the
            whole device.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — the
            requested config wasn&apos;t fetched upstream, or the platform
            (IOS/IOS-XE/NXOS/XR) couldn&apos;t be determined from the config text.
            Setting the device&apos;s network driver (e.g. via Get from Nautobot) helps
            the parser when the config text lacks a recognizable platform banner.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Add a Get Configs step upstream and enable the config(s) you need.</li>
          <li>Add this step after it; set config_source and output_key.</li>
          <li>
            Use Log Attributes to inspect the parsed structure, or reference{" "}
            <HelpCode>parsed.{"{output_key}"}</HelpCode> fields from a Render Jinja
            Template step.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
