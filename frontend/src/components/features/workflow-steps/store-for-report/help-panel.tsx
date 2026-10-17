"use client";

import { HelpCode, HelpExample, HelpSection } from "../shared/step-help";

/**
 * Built-in Help tab content for Store for Report.
 * Covers every Configuration control with practical examples.
 */
export function StoreForReportHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Records named facts per device in the application database so reports can
          summarize all devices at once (table <HelpCode>report_data_records</HelpCode>).
          Every collection adds rows, so the history is kept for trends. Each row also
          remembers which run wrote it.
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <HelpCode>device</HelpCode> mode — one row per device: serial number, OS
            version, <em>number of</em> shutdown interfaces, …
          </li>
          <li>
            <HelpCode>items</HelpCode> mode — one row per element of a list: every
            interface with its status, every NTP server, every local user, …
          </li>
        </ul>
        <p>
          Writing the same dataset for the same device again in one run replaces that
          run&apos;s earlier rows instead of adding more (a retry does not duplicate).
        </p>
      </HelpSection>

      <HelpSection title="dataset">
        <p>
          Name that groups the fields. Reports read data by dataset name and field
          names, never by workflow step. Keep device rows and list-item rows in separate
          datasets (for example <HelpCode>inventory</HelpCode> and{" "}
          <HelpCode>interfaces</HelpCode>).
        </p>
        <HelpExample>dataset: inventory</HelpExample>
      </HelpSection>

      <HelpSection title="Where paths come from">
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <HelpCode>nautobot.…</HelpCode>, <HelpCode>git.…</HelpCode> — attribute bags
            filled by source steps such as Get Nautobot Attributes.
          </li>
          <li>
            <HelpCode>parsed.…</HelpCode> — structured output of earlier steps: Run
            Command with a parser, Parse Cisco Config, Catalyst Center steps.
          </li>
          <li>
            <HelpCode>name</HelpCode>, <HelpCode>hostname</HelpCode>,{" "}
            <HelpCode>platform</HelpCode>, <HelpCode>primary_ip4</HelpCode> — fields of
            the device itself.
          </li>
          <li>
            <HelpCode>run.id</HelpCode> (the run&apos;s UUID, as in every other step),{" "}
            <HelpCode>run.date</HelpCode> — the current run.
          </li>
        </ul>
        <p>
          Raw (unparsed) command output is not an attribute and cannot be stored here.
          Run the command with a parser first. Use{" "}
          <span className="font-medium text-foreground">Browse attributes</span> to pick
          a real path from the workflow&apos;s most recent run.
        </p>
      </HelpSection>

      <HelpSection title="Device mode: fields">
        <p>
          One entry per fact: a <HelpCode>name</HelpCode> (lowercase letters, digits and
          &apos;_&apos;, starting with a letter) and the <HelpCode>attribute_path</HelpCode> to
          read it from.
        </p>
        <HelpExample>
          serial_number ← nautobot.serial
          <br />
          device_type ← nautobot.device_type.model
          <br />
          location ← nautobot.location.name
        </HelpExample>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            Only strings (up to 2000 characters), numbers, booleans and null are stored.
          </li>
          <li>
            Secrets are refused, because the table keeps every collection and cannot
            take a value back. A field whose name or path contains a secret-looking name
            (<HelpCode>password</HelpCode>, <HelpCode>secret</HelpCode>,{" "}
            <HelpCode>token</HelpCode>, <HelpCode>community</HelpCode>,{" "}
            <HelpCode>api_key</HelpCode>, <HelpCode>*_password</HelpCode>, …) is a
            configuration error. A sealed value, or a cleartext secret this run has
            handled, fails that device.
          </li>
          <li>A path that resolves to nothing is stored as null.</li>
          <li>
            A list or object value fails that device and routes it to the failure
            outcome. Point the path at one value inside the
            list, or count the list (below).
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Example: parsed command output">
        <p>
          Add a Run Command step before this one with <HelpCode>parser: textfsm</HelpCode>{" "}
          and the command <HelpCode>show version</HelpCode>. The result is stored at{" "}
          <HelpCode>parsed.&lt;parsed_output_key&gt;.&lt;command&gt;.parsed</HelpCode> —
          with the default key <HelpCode>parsed</HelpCode> that is{" "}
          <HelpCode>parsed.parsed.show version.parsed</HelpCode>. TextFSM returns a
          list with one record per row, so a single-row command like{" "}
          <HelpCode>show version</HelpCode> is read with <HelpCode>[0]</HelpCode>.
        </p>
        <HelpExample>
          dataset: inventory
          <br />
          os_version ← parsed.parsed.show version.parsed[0].version
          <br />
          uptime ← parsed.parsed.show version.parsed[0].uptime
          <br />
          serial_number ← parsed.parsed.show version.parsed[0].serial[0]
        </HelpExample>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            The field names inside a record come from the ntc-templates template for the
            device&apos;s platform, so check them with Browse attributes. Some fields are
            lists (for example <HelpCode>serial</HelpCode> in the Cisco IOS{" "}
            <HelpCode>show version</HelpCode> template). A list fails the device, so add{" "}
            <HelpCode>[0]</HelpCode> to take the first element.
          </li>
          <li>
            A command with no matching template has <HelpCode>parsed: null</HelpCode>, so
            its fields are stored as null.
          </li>
          <li>
            The command text is part of the path, so a command containing a dot (for
            example one with an IP address) cannot be addressed.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Example: parsed config">
        <p>
          Add a Parse Cisco Config step before this one. Its output key defaults to{" "}
          <HelpCode>cisco_config</HelpCode> and is always split into{" "}
          <HelpCode>running</HelpCode> and <HelpCode>startup</HelpCode>; the side that
          was not parsed is null (so its fields are stored as null).
        </p>
        <HelpExample>
          dataset: config_facts
          <br />
          hostname ← parsed.cisco_config.running.hostname
          <br />
          startup_hostname ← parsed.cisco_config.startup.hostname
        </HelpExample>
        <p>
          Parsed configs contain lists (VLANs, interfaces, ACLs). Pick one element with a
          filter written as <HelpCode>list[field=value]</HelpCode>, then read a single
          value from it:
        </p>
        <HelpExample>
          mgmt_ip ← parsed.cisco_config.running.l3_interfaces[name=Vlan10].ip_address
          <br />
          mgmt_interface ← parsed.cisco_config.running.l3_interfaces[ip_address=10.0.10.1].name
          <br />
          first_l3_interface ← parsed.cisco_config.running.l3_interfaces[0].name
        </HelpExample>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            The names of the fields inside a parsed config come from the config parser
            and can differ between platforms; check them with Browse attributes.
          </li>
          <li>
            <HelpCode>[field=value]</HelpCode> selects the first list item whose field
            equals the value. If nothing matches, the field is stored as null.
          </li>
          <li>
            <HelpCode>[0]</HelpCode> selects by position.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Counting list items">
        <p>
          Choose <span className="font-medium text-foreground">Count list items</span> for
          a field to store how many items the list at the path has, instead of the list
          itself. Optionally count only the items whose field equals a value
          (<HelpCode>where</HelpCode> = <HelpCode>value</HelpCode>). Run Command with a
          parser on <HelpCode>show interfaces status</HelpCode> first:
        </p>
        <HelpExample>
          dataset: inventory
          <br />
          interface_count ← parsed.parsed.show interfaces status.parsed (count)
          <br />
          shutdown_interfaces ← parsed.parsed.show interfaces status.parsed (count, where
          status = disabled)
          <br />
          connected_interfaces ← parsed.parsed.show interfaces status.parsed (count, where
          status = connected)
        </HelpExample>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            The path must point at the list itself, not at one element. The{" "}
            <HelpCode>where</HelpCode> field is read inside each element.
          </li>
          <li>
            The value is compared as text and must match exactly, including case. Numbers
            compare as written (<HelpCode>10</HelpCode>), booleans as{" "}
            <HelpCode>true</HelpCode>/<HelpCode>false</HelpCode>. Check the real status
            texts of your platform with Browse attributes (they differ between commands,
            for example <HelpCode>disabled</HelpCode> in{" "}
            <HelpCode>show interfaces status</HelpCode> but{" "}
            <HelpCode>administratively down</HelpCode> in{" "}
            <HelpCode>show ip interface brief</HelpCode>).
          </li>
          <li>
            An empty list counts 0. A path that resolves to nothing (for example the
            command had no template) stores null, not 0, so a report can tell
            &quot;none&quot; from &quot;unknown&quot;.
          </li>
          <li>A path that resolves to something that is not a list fails the device.</li>
        </ul>
      </HelpSection>

      <HelpSection title="Items mode: one row per list element">
        <p>
          Use this when you need the items themselves, for example which interface is
          shut down. Set <HelpCode>mode</HelpCode> to{" "}
          <HelpCode>One row per list item</HelpCode>, put the path to the list into{" "}
          <HelpCode>items_path</HelpCode>, and map fields{" "}
          <span className="font-medium text-foreground">relative to one element</span>.
        </p>
        <HelpExample>
          dataset: interfaces
          <br />
          items_path: parsed.parsed.show interfaces status.parsed
          <br />
          name ← port
          <br />
          status ← status
          <br />
          vlan ← vlan
        </HelpExample>
        <p>
          The same works with a parsed config list, for example the layer-3 interfaces
          with their addresses:
        </p>
        <HelpExample>
          dataset: l3_interfaces
          <br />
          items_path: parsed.cisco_config.running.l3_interfaces
          <br />
          name ← name
          <br />
          ip_address ← ip_address
        </HelpExample>
        <p>
          For device <HelpCode>sw1</HelpCode> this stores one row per interface, such as{" "}
          <HelpCode>{"{name: Gi1/0/1, status: connected}"}</HelpCode> and{" "}
          <HelpCode>{"{name: Gi1/0/2, status: disabled}"}</HelpCode>. Store all
          items with their status and let the report filter for{" "}
          <HelpCode>disabled</HelpCode> — do not try to store only the shutdown ones.
        </p>
        <p>
          If the list holds plain values (such as <HelpCode>[&quot;10.0.0.1&quot;, &quot;10.0.0.2&quot;]</HelpCode>)
          instead of records, use <HelpCode>.</HelpCode> for the element itself. The path
          to such a list depends on the step that produced it:
        </p>
        <HelpExample>
          dataset: ntp_servers
          <br />
          items_path: &lt;path to the list of server addresses&gt;
          <br />
          address ← .
        </HelpExample>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            Field paths inside an element can use the same filters and positions as
            elsewhere, for example <HelpCode>ports[0].name</HelpCode>. The Browse
            attributes button is only available for <HelpCode>items_path</HelpCode>. For
            a field, pick a path of one element there (for example{" "}
            <HelpCode>…parsed[0].port</HelpCode>) and use only its last part (
            <HelpCode>port</HelpCode>).
          </li>
          <li>
            A missing value inside an element is stored as null; a list/object value or
            a secret fails the device.
          </li>
          <li>
            An <span className="font-medium text-foreground">empty list</span> is stored
            as &quot;none found&quot;, so a device whose NTP servers were removed no
            longer shows its old servers. A path that resolves to{" "}
            <span className="font-medium text-foreground">nothing</span> (command not
            parsed, section not present) fails the device instead, because that is not
            the same as an empty list.
          </li>
          <li>
            At most 5000 items per device and collection. Aggregation (count) is not
            available in items mode; count the rows in the report.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Reusing fields across workflows">
        <p>
          Reports read data by dataset and field name, so use the same dataset and field
          names wherever the same fact is collected. Different workflows can write to one
          dataset; the table keeps every collection, but a report that wants the current
          state takes the <span className="font-medium text-foreground">newest collection
          per device</span>. Its field set wins: fields that only an older collection had
          are not merged in.
        </p>
        <p>
          So put <span className="font-medium text-foreground">all fields of a dataset
          into one Store for Report step</span>. If two steps in the same run write the
          same dataset for the same device, the second one replaces the first one&apos;s
          rows, and the first one&apos;s fields are lost. Use a different dataset for each
          step if their fields really are separate.
        </p>
      </HelpSection>
    </div>
  );
}
