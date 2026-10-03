"use client";

import {
  FanOutHelpSection,
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Get from Catalyst Center.
 * Covers every Configuration control with practical examples.
 */
export function GetCatalystCenterDevicesHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Selects devices from a Cisco Catalyst Center (formerly DNA Center)
          inventory and turns them into workflow targets. Catalyst Center can
          manage thousands of devices, so the filters you set here are applied{" "}
          <span className="font-medium text-foreground">on the controller</span>
          : only matching devices are transferred.
        </p>
        <p>
          Each device gets its management IP as the SSH target, and its software
          type (IOS-XE, IOS-XR, NX-OS, IOS) is mapped to a network driver so
          Run Command and other SSH steps work without extra setup. The full
          Catalyst Center inventory record is available to later steps as the{" "}
          <HelpCode>catalyst_center</HelpCode> attribute bag, for example{" "}
          <HelpCode>{"{catalyst_center.role}"}</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Catalyst Center source">
        <p>
          Click{" "}
          <span className="font-medium text-foreground">Configure Source</span>{" "}
          (or Edit Source) and choose a source created under Settings → Sources
          → Cisco Catalyst Center. The step stores that source&apos;s ID as{" "}
          <HelpCode>catalyst_center_source_id</HelpCode>; the URL and
          credentials are resolved from settings at preview and run time and are
          never stored on the step.
        </p>
        <HelpExample>
          catalyst_center_source_id: lab-catalyst
        </HelpExample>
      </HelpSection>

      <HelpSection title="Filters">
        <p>
          Use <span className="font-medium text-foreground">Add filter…</span>{" "}
          to add a filter, enter one value per line, and remove it with the ×
          button. Rules that apply to every filter:
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">
              Several lines in one filter are OR-ed
            </span>
            : <HelpCode>sw1</HelpCode> and <HelpCode>sw2</HelpCode> on two
            lines selects either device.
          </li>
          <li>
            <span className="font-medium text-foreground">
              Different filters are AND-ed
            </span>
            : hostname <HelpCode>sw.*</HelpCode> and role{" "}
            <HelpCode>ACCESS</HelpCode> selects only access-role devices whose
            name starts with <HelpCode>sw</HelpCode>.
          </li>
          <li>
            <span className="font-medium text-foreground">
              Case-sensitive, whole value
            </span>
            : <HelpCode>sw</HelpCode> does not match <HelpCode>sw1</HelpCode>,
            and <HelpCode>SW1</HelpCode> does not match <HelpCode>sw1</HelpCode>.
          </li>
          <li>
            <span className="font-medium text-foreground">
              <HelpCode>.*</HelpCode> is the only wildcard
            </span>
            . <HelpCode>sw.*</HelpCode> matches every name starting with{" "}
            <HelpCode>sw</HelpCode>; <HelpCode>.*-core</HelpCode> every name
            ending in <HelpCode>-core</HelpCode>. Regular-expression features
            such as <HelpCode>|</HelpCode>, <HelpCode>[12]</HelpCode>,{" "}
            <HelpCode>^</HelpCode> or <HelpCode>$</HelpCode> are not supported
            by Catalyst Center and match nothing.
          </li>
        </ul>
        <HelpExample>
          hostnames: sw.*
          <br />
          roles: ACCESS, DISTRIBUTION
          <br />
          reachability_statuses: Reachable
          <br />
          <span className="text-muted-foreground">
            → reachable access or distribution devices whose name starts with
            &quot;sw&quot;
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Available filters">
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <HelpCode>hostnames</HelpCode> — device hostname, e.g.{" "}
            <HelpCode>sw.*</HelpCode>.
          </li>
          <li>
            <HelpCode>management_ips</HelpCode> — management IP. A dot is
            literal, so to match a whole range write the prefix, a dot, then{" "}
            <HelpCode>.*</HelpCode>: <HelpCode>10.10.20..*</HelpCode> matches
            every <HelpCode>10.10.20.x</HelpCode>.
          </li>
          <li>
            <HelpCode>cidr</HelpCode> — one subnet, e.g.{" "}
            <HelpCode>10.10.20.0/24</HelpCode>. Catalyst Center has no subnet
            filter, so the step first narrows by the shared address prefix on
            the controller and then checks the exact range itself. A /31 such as{" "}
            <HelpCode>10.10.20.176/31</HelpCode> selects exactly .176 and .177.
            If you also set management_ips, both must match.
          </li>
          <li>
            <HelpCode>families</HelpCode> — e.g.{" "}
            <HelpCode>Switches and Hubs</HelpCode>.
          </li>
          <li>
            <HelpCode>roles</HelpCode> — e.g. <HelpCode>ACCESS</HelpCode>,{" "}
            <HelpCode>CORE</HelpCode>, <HelpCode>DISTRIBUTION</HelpCode>.
          </li>
          <li>
            <HelpCode>software_types</HelpCode> — e.g.{" "}
            <HelpCode>IOS-XE</HelpCode>; <HelpCode>software_versions</HelpCode>{" "}
            — e.g. <HelpCode>17.12.*</HelpCode>.
          </li>
          <li>
            <HelpCode>platform_ids</HelpCode>,{" "}
            <HelpCode>serial_numbers</HelpCode>, <HelpCode>series</HelpCode>,{" "}
            <HelpCode>device_types</HelpCode> — hardware identity, e.g.{" "}
            <HelpCode>C9300-.*</HelpCode>.
          </li>
          <li>
            <HelpCode>reachability_statuses</HelpCode> — e.g.{" "}
            <HelpCode>Reachable</HelpCode>;{" "}
            <HelpCode>collection_statuses</HelpCode> — e.g.{" "}
            <HelpCode>Managed</HelpCode>.
          </li>
        </ul>
        <HelpWarning title="No site filter yet">
          <p>
            Catalyst Center&apos;s device list cannot be filtered by site, and
            the location fields on the device are deprecated. Select by name,
            IP/CIDR, or the attributes above. A site filter may be added later.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Safety guard for large inventories">
        <p>
          <HelpCode>allow_all</HelpCode> is off by default. With no filter set
          the step <span className="font-medium text-foreground">fails</span>{" "}
          instead of pulling every device. Turn it on only when you really want
          the whole inventory.
        </p>
        <p>
          <HelpCode>max_devices</HelpCode> is an optional cap. If more devices
          match, the step fails with a clear message — it never silently
          truncates, which would make a workflow act on an incomplete target
          list. Leave it empty for no cap.
        </p>
        <HelpExample>
          filters: roles = ACCESS
          <br />
          max_devices: 200
          <br />
          <span className="text-muted-foreground">
            → fails if more than 200 access devices exist, so you can tighten
            the filters
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Show Preview">
        <p>
          Lists the first 25 devices the current filters would select
          (hostname, management IP, family/role, software, reachability) and
          tells you if more exist. It runs on the backend with the saved source
          and does not change the workflow. The button is enabled once a source
          and at least one filter (or allow_all) are set.
        </p>
      </HelpSection>

      <FanOutHelpSection />
    </div>
  );
}
