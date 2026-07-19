"use client";

import {
  FanOutHelpSection,
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Get from ISE.
 * Covers every Configuration control with practical examples.
 */
export function GetIseDevicesHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Looks up network devices already registered in Cisco ISE (as
          RADIUS/TACACS clients) and turns them into workflow targets. This is
          a different inventory than Nautobot — ISE only knows about devices
          someone explicitly registered for network access control, so it is
          normal for ISE to have far fewer devices than Nautobot for the same
          subnet.
        </p>
        <p>
          Downstream steps such as Get ISE TACACS Key, Update ISE TACACS Key,
          or Run Command run against the devices this step adds to context.
        </p>
      </HelpSection>

      <HelpSection title="ISE source">
        <p>
          Click{" "}
          <span className="font-medium text-foreground">Configure Source</span>{" "}
          (or Edit Source) and choose a source created under Settings → Sources
          → Cisco ISE. The step stores that source&apos;s ID as{" "}
          <HelpCode>ise_source_id</HelpCode>.
        </p>
        <p>
          Credentials (URL + credentials) are resolved from settings at preview and
          run time — they are not pasted into the step config.
        </p>
        <HelpExample>
          ise_source_id: prod-ise
          <br />
          <span className="text-muted-foreground">
            → resolves to https://ise.example.com with the stored credentials
          </span>
        </HelpExample>
        <HelpWarning title="Source required">
          <p>
            Without a valid source the step cannot preview or resolve devices.
            If the ID is missing from Settings, the Configuration panel shows
            &quot;Not configured&quot;.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Query mode">
        <p>
          <HelpCode>query_mode</HelpCode> selects how to find devices in ISE.
          Only the fields for the active mode are used at preview and run time.
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">Device name(s)</span>{" "}
            — <HelpCode>query_mode: name</HelpCode>. One ISE device name per
            line in <HelpCode>device_names</HelpCode>.
          </li>
          <li>
            <span className="font-medium text-foreground">
              IP address / CIDR
            </span>{" "}
            — <HelpCode>query_mode: cidr</HelpCode>. Single host or prefix in{" "}
            <HelpCode>cidr</HelpCode>.
          </li>
          <li>
            <span className="font-medium text-foreground">
              Network device group
            </span>{" "}
            — <HelpCode>query_mode: group</HelpCode>. Full NDG string in{" "}
            <HelpCode>group_name</HelpCode>.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Device name(s)">
        <p>
          One ISE device name per line, exactly as it&apos;s named in ISE. Each
          line does one direct lookup; a name that doesn&apos;t exist in ISE is
          silently skipped (check the run logs for a &quot;not found in ISE&quot;
          warning per name).
        </p>
        <HelpExample>
          device_names:
          <br />
          lab
          <br />
          lab-001
          <br />
          lab-002
        </HelpExample>
      </HelpSection>

      <HelpSection title="IP address / CIDR">
        <p>
          A single host address (e.g. <HelpCode>192.168.178.1</HelpCode> or{" "}
          <HelpCode>192.168.178.1/32</HelpCode>) does one fast, exact-match
          lookup.
        </p>
        <p>
          A wider prefix (e.g. <HelpCode>192.168.178.0/24</HelpCode>) has to
          scan every device ISE has registered and check each one&apos;s IP
          client-side — ISE has no native CIDR filter. Preview caps the scan at
          500 devices for speed; the full scan runs at workflow execution time.
        </p>
        <HelpExample>
          cidr: 192.168.178.0/24
        </HelpExample>
        <HelpWarning title="Wide CIDR scans are slow">
          <p>
            Prefer a single host IP when you know the target. Use a prefix only
            when you need every ISE device whose IP falls inside the range.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Network device group — naming (read this one)">
        <p>
          ISE has no separate parent-group field. A group&apos;s full hierarchy
          is one <HelpCode>#</HelpCode>-delimited string, and you must enter
          that{" "}
          <span className="font-medium text-foreground">exact full string</span>{" "}
          — not just the name you see on the device or in ISE&apos;s UI.
          Getting this wrong doesn&apos;t error, it just silently returns zero
          devices.
        </p>

        <p className="font-medium text-foreground">The pattern:</p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            The <span className="font-medium text-foreground">first</span>{" "}
            segment is the group&apos;s category (built-in categories:{" "}
            <HelpCode>Location</HelpCode>, <HelpCode>Device Type</HelpCode>,{" "}
            <HelpCode>IPSEC</HelpCode> — or a custom one your ISE admin created,
            e.g. <HelpCode>myGroup</HelpCode>).
          </li>
          <li>
            The <span className="font-medium text-foreground">root</span> member
            of any category repeats the category name:{" "}
            <HelpCode>{"{category}#{category}"}</HelpCode>. For a custom category{" "}
            <HelpCode>myGroup</HelpCode>, its root is{" "}
            <HelpCode>myGroup#myGroup</HelpCode> — not just{" "}
            <HelpCode>myGroup</HelpCode>.
          </li>
          <li>
            Every child appends its own name onto the parent&apos;s{" "}
            <span className="font-medium text-foreground">full</span> name:{" "}
            <HelpCode>{"{parent-full-name}#{child-name}"}</HelpCode>.
          </li>
        </ul>

        <p className="font-medium text-foreground">Worked example:</p>
        <p>
          A custom category <HelpCode>myGroup</HelpCode> with a child group
          named <HelpCode>my-test-001</HelpCode> has this full hierarchy:
        </p>
        <HelpExample>
          myGroup#myGroup{" "}
          <span className="text-muted-foreground">(the root)</span>
          <br />
          myGroup#myGroup#my-test-001{" "}
          <span className="text-muted-foreground">
            (child &quot;my-test-001&quot;)
          </span>
        </HelpExample>
        <p>
          To find devices tagged with the child group, enter{" "}
          <HelpCode>myGroup#myGroup#my-test-001</HelpCode> — the full 3-segment
          string, including the repeated <HelpCode>myGroup</HelpCode>.
        </p>

        <p>Some built-in examples, for comparison:</p>
        <HelpExample>
          Location#All Locations
          <br />
          Location#All Locations#Building1
          <br />
          Device Type#All Device Types
          <br />
          IPSEC#Is IPSEC Device#No
        </HelpExample>

        <HelpWarning title="Common mistakes that return 0 devices">
          <ul className="list-disc space-y-0.5 pl-4">
            <li>
              Entering just the leaf name (<HelpCode>my-test-001</HelpCode>) with
              no category prefix at all.
            </li>
            <li>
              Entering <HelpCode>{"{category}#{child}"}</HelpCode> without
              repeating the category (
              <HelpCode>myGroup#my-test-001</HelpCode> instead of{" "}
              <HelpCode>myGroup#myGroup#my-test-001</HelpCode>).
            </li>
            <li>
              Group membership is a flat tag, not an inherited tree — querying
              the root (<HelpCode>myGroup#myGroup</HelpCode>) only returns
              devices tagged with that exact root string, not devices tagged with
              its children too (and vice versa).
            </li>
          </ul>
        </HelpWarning>

        <p className="font-medium text-foreground">How to find the exact name:</p>
        <p>
          Under Settings → Sources → Cisco ISE, or directly in ISE&apos;s admin
          console (Administration → Network Resources → Network Device Groups)
          — the <HelpCode>Name</HelpCode> column there is already the full
          hierarchical string to paste in here. You can also switch to{" "}
          <span className="font-medium text-foreground">Device name(s)</span>{" "}
          mode, preview a device you know is in the group, and read the group
          name straight off its <HelpCode>NetworkDeviceGroupList</HelpCode>{" "}
          entries.
        </p>
      </HelpSection>

      <HelpSection title="Resolve to devices">
        <p>
          When <HelpCode>resolve_to_devices</HelpCode> is enabled, ISE entries
          whose IP uses a netmask other than <HelpCode>/32</HelpCode> may
          represent a subnet or group rather than one host. The step expands
          such entries into individual devices by matching Nautobot&apos;s{" "}
          <span className="font-medium text-foreground">Primary Prefix</span>{" "}
          filter against the CIDR.
        </p>
        <p>
          This requires a Nautobot source — click{" "}
          <span className="font-medium text-foreground">
            Configure Nautobot Source
          </span>{" "}
          to set <HelpCode>nautobot_source_id</HelpCode>. If nothing matches in
          Nautobot, the raw ISE entry is kept as-is rather than dropped.
        </p>
        <HelpExample>
          resolve_to_devices: true
          <br />
          nautobot_source_id: prod-lab
        </HelpExample>
        <HelpWarning title="Nautobot source required">
          <p>
            When resolve is on but no Nautobot source is configured, the
            Configuration panel shows &quot;Nautobot source required for
            resolve_to_devices&quot;.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Show Preview">
        <p>
          <span className="font-medium text-foreground">Show Preview</span> runs
          the current query against the configured ISE source and lists matching
          devices before you save or run the workflow. The button stays disabled
          until a source and the active query fields are ready.
        </p>
        <p>
          Preview is read-only — it does not change the workflow context. For
          CIDR mode, preview caps the scan at 500 devices; a truncated result
          is flagged in the preview dialog.
        </p>
      </HelpSection>

      <FanOutHelpSection />

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the
            ISE query finished. Matched devices (including zero) are in context
            for downstream steps.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — the
            step could not run (missing source, bad credentials, or an
            unexpected error). Fix Configuration and check run logs.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Configure a Cisco ISE source (Settings → Sources).</li>
          <li>
            Choose query mode and fill in device names, CIDR, or the full NDG
            string.
          </li>
          <li>
            Optionally enable resolve_to_devices and configure a Nautobot source.
          </li>
          <li>Preview the device list, then enable fan-out if needed.</li>
        </ol>
      </HelpSection>
    </div>
  );
}
