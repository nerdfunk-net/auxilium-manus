"use client";

import {
  FanOutHelpSection,
  HelpCode,
  HelpExample,
  HelpSection,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Get from ACI.
 * Covers every Configuration control with practical examples.
 */
export function GetAciDevicesHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Selects the{" "}
          <span className="font-medium text-foreground">
            leaf and spine switches
          </span>{" "}
          of a Cisco ACI fabric through its APIC and turns them into workflow
          targets. The step is read-only: it never writes anything to ACI. The
          APIC controllers themselves are never selected.
        </p>
        <p>
          Later steps can read the switch data as the <HelpCode>aci</HelpCode>{" "}
          attribute bag, for example <HelpCode>{"{aci.role}"}</HelpCode>,{" "}
          <HelpCode>{"{aci.model}"}</HelpCode>,{" "}
          <HelpCode>{"{aci.software_version}"}</HelpCode> or{" "}
          <HelpCode>{"{aci.pod_id}"}</HelpCode>. The raw APIC attributes are
          under <HelpCode>aci.raw</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Management IP and SSH">
        <p>
          A switch has a management IP only if the fabric has node management
          addresses configured: the out-of-band address is used, else the
          in-band one. Without either, the device has{" "}
          <span className="font-medium text-foreground">no IP address</span>{" "}
          and its name is used as the host name. The fabric-internal TEP
          address is never used as an address; it is kept as{" "}
          <HelpCode>aci.tep_address</HelpCode>.
        </p>
        <p>
          ACI is a data source for now: the step does not set a network
          driver, so SSH steps need an explicit driver override.
        </p>
      </HelpSection>

      <HelpSection title="ACI source">
        <p>
          Click{" "}
          <span className="font-medium text-foreground">Configure Source</span>{" "}
          (or Edit Source) and choose a source created under Settings → Sources
          → Cisco ACI. The step stores that source&apos;s ID as{" "}
          <HelpCode>aci_source_id</HelpCode>; the URL and credentials are
          resolved from settings at preview and run time and are never stored
          on the step.
        </p>
        <HelpExample>aci_source_id: lab-aci</HelpExample>
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
            : <HelpCode>leaf-1</HelpCode> and <HelpCode>leaf-2</HelpCode> on two
            lines selects either switch.
          </li>
          <li>
            <span className="font-medium text-foreground">
              Different filters are AND-ed
            </span>
            : name <HelpCode>dc1-*</HelpCode> and role{" "}
            <HelpCode>leaf</HelpCode> selects only leaves whose name starts
            with <HelpCode>dc1-</HelpCode>.
          </li>
          <li>
            <span className="font-medium text-foreground">
              Case-sensitive, whole value
            </span>
            : <HelpCode>leaf</HelpCode> does not match{" "}
            <HelpCode>leaf-1</HelpCode>, and <HelpCode>Leaf-1</HelpCode> does
            not match <HelpCode>leaf-1</HelpCode>.
          </li>
          <li>
            <span className="font-medium text-foreground">
              <HelpCode>*</HelpCode> and <HelpCode>?</HelpCode> are the only
              wildcards
            </span>
            . <HelpCode>*</HelpCode> matches any text, <HelpCode>?</HelpCode>{" "}
            exactly one character. Every other character is literal, so{" "}
            <HelpCode>.</HelpCode>, <HelpCode>|</HelpCode> or{" "}
            <HelpCode>[12]</HelpCode> have no special meaning.
          </li>
        </ul>
        <HelpExample>
          names: dc1-leaf-*
          <br />
          roles: leaf
          <br />
          pod_ids: 1
          <br />
          <span className="text-muted-foreground">
            → the leaves of pod 1 whose name starts with &quot;dc1-leaf-&quot;
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Available filters">
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <HelpCode>names</HelpCode> — node name, e.g.{" "}
            <HelpCode>dc1-leaf-*</HelpCode>.
          </li>
          <li>
            <HelpCode>roles</HelpCode> — tick <HelpCode>leaf</HelpCode>,{" "}
            <HelpCode>spine</HelpCode> or both. With none ticked, the row does
            not count as a filter: leaf and spine are both taken only when
            another filter or <HelpCode>allow_all</HelpCode> is set.
          </li>
          <li>
            <HelpCode>pod_ids</HelpCode>, <HelpCode>node_ids</HelpCode> —
            whole numbers, e.g. <HelpCode>101</HelpCode>.
          </li>
          <li>
            <HelpCode>models</HelpCode>, <HelpCode>serials</HelpCode>,{" "}
            <HelpCode>versions</HelpCode> — hardware model, serial number and
            software version exactly as the APIC reports them, e.g.{" "}
            <HelpCode>N9K-C93*</HelpCode> or{" "}
            <HelpCode>n9000-16.1(4h)</HelpCode>.
          </li>
          <li>
            <HelpCode>fabric_states</HelpCode> — e.g.{" "}
            <HelpCode>active</HelpCode>.
          </li>
          <li>
            <HelpCode>cidr</HelpCode> — one subnet, e.g.{" "}
            <HelpCode>10.1.1.0/24</HelpCode>, checked against the management
            IP. A switch without a management IP never matches.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Safety guard">
        <p>
          <HelpCode>allow_all</HelpCode> is off by default. With no filter set
          the step <span className="font-medium text-foreground">fails</span>{" "}
          instead of selecting every switch of the fabric, which a later step
          might then act on. Turn it on only when you really want the whole
          fabric.
        </p>
        <p>
          <HelpCode>max_devices</HelpCode> is an optional cap. If more switches
          match, the step fails with a clear message — it never silently
          truncates, which would make a workflow act on an incomplete target
          list. Leave it empty for no cap.
        </p>
        <HelpExample>
          filters: roles = leaf
          <br />
          max_devices: 100
          <br />
          <span className="text-muted-foreground">
            → fails if more than 100 leaves exist, so you can tighten the
            filters
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Show Preview">
        <p>
          Lists the first 25 switches the current filters would select (name,
          node and pod, role and model, software, management IP, fabric state)
          and tells you if more exist. It runs on the backend with the saved
          source and does not change the workflow. The button is enabled once a
          source and at least one filter (or allow_all) are set.
        </p>
      </HelpSection>

      <FanOutHelpSection />
    </div>
  );
}
