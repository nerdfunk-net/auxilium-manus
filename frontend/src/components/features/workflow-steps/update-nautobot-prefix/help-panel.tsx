"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/** Built-in Help tab content for Update IP Prefix. */
export function UpdateNautobotPrefixHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Changes an existing IP prefix in Nautobot: its description, status,
          role and locations. A device whose prefix was updated, or already had
          every value, leaves through{" "}
          <span className="font-medium text-foreground">success</span>; a device
          that could not be served leaves through{" "}
          <span className="font-medium text-foreground">failure</span>.
        </p>
        <p>
          Only the fields you fill in are changed. An empty field is left as it
          is, and a value cannot be cleared with this step. Running the step
          again is safe: nothing is written when the prefix already has the
          values.
        </p>
      </HelpSection>

      <HelpSection title="nautobot_source_id">
        <p>The Nautobot source (Settings → Sources) to write to.</p>
      </HelpSection>

      <HelpSection title="prefix_id, prefix and namespace">
        <p>
          Select the prefix either by its Nautobot ID (
          <HelpCode>prefix_id</HelpCode>, a fixed UUID or a{" "}
          <HelpCode>{"{path}"}</HelpCode> expression) or by its network (
          <HelpCode>prefix</HelpCode>, for example 10.0.0.0/24). When{" "}
          <HelpCode>prefix_id</HelpCode> is set, <HelpCode>prefix</HelpCode> is
          ignored.
        </p>
        <p>
          The same network can exist in several namespaces. Narrow the lookup
          with <HelpCode>namespace</HelpCode> (name or UUID). No match fails the
          device with <HelpCode>prefix_not_found</HelpCode>; several matches
          fail it with <HelpCode>ambiguous_match</HelpCode> and nothing is
          written.
        </p>
        <p>
          An IPv6 network is looked up in the form Nautobot stores, so{" "}
          <HelpCode>2001:DB8::/32</HelpCode> finds{" "}
          <HelpCode>2001:db8::/32</HelpCode>.
        </p>
        <HelpExample>10.0.0.0/24</HelpExample>
      </HelpSection>

      <HelpSection title="description, status and role">
        <p>
          Fixed text or a <HelpCode>{"{path}"}</HelpCode> expression. An
          expression that resolves to nothing fails the device, and a value
          taken from a secret is refused. The status list shows the statuses
          your Nautobot defines for prefixes; the role is a name or UUID of a
          role that applies to prefixes.
        </p>
      </HelpSection>

      <HelpSection title="locations and locations_mode">
        <p>
          A prefix can belong to several locations.{" "}
          <HelpCode>locations</HelpCode> is a list of location names or UUIDs
          separated by commas or new lines; each entry can also be a{" "}
          <HelpCode>{"{path}"}</HelpCode> expression. Names are matched without
          regard to case. A name that contains a comma must be quoted, or given
          as its UUID. An empty list leaves the locations unchanged.
        </p>
        <p>
          <HelpCode>locations_mode</HelpCode> decides how the list is applied:{" "}
          <HelpCode>replace</HelpCode> makes it the complete set of locations,{" "}
          <HelpCode>add</HelpCode> keeps the current locations and adds these,
          and <HelpCode>remove</HelpCode> drops these from the current
          locations.
        </p>
        <HelpExample>{'Berlin, "Frankfurt, West"'}</HelpExample>
      </HelpSection>

      <HelpSection title="Prefixes from interfaces and dry_run">
        <p>
          Switch on <HelpCode>prefixes_from_interfaces</HelpCode> to update the
          prefixes of the device&apos;s own interfaces instead of one chosen
          prefix. The step reads the Nautobot attributes of each device (run{" "}
          <span className="font-medium text-foreground">
            Get Nautobot Attributes
          </span>{" "}
          with interfaces first): the parent prefix of every IP address on its
          interfaces and the device&apos;s location, both by UUID. It then makes
          sure each prefix has that location in its list of locations. Locations
          are only added, never removed, and a prefix that already has the
          location is not written.
        </p>
        <p>
          In this mode the prefix selector, the fields and{" "}
          <HelpCode>locations</HelpCode> must be empty. A device without a
          location or without interfaces in its attributes fails with{" "}
          <HelpCode>device_location_missing</HelpCode> or{" "}
          <HelpCode>interfaces_missing</HelpCode>; a prefix is written once per
          location however many devices and addresses use it. Attributes read
          before this mode existed carry no prefix data: read them again.
          Whether a prefix already has the location is always read from
          Nautobot, not from the attributes.
        </p>
        <p>
          <HelpCode>dry_run</HelpCode> writes nothing. Nautobot is read and each
          device gets a preview (<HelpCode>would_add_location</HelpCode>: prefix
          id, network and namespace, and <HelpCode>already_assigned</HelpCode>);
          the counts are in <HelpCode>update_prefix_counts</HelpCode>. Run it
          first. <HelpCode>dry_run</HelpCode> only works together with{" "}
          <HelpCode>prefixes_from_interfaces</HelpCode>; on its own the step
          refuses to run instead of writing.
        </p>
      </HelpSection>

      <HelpWarning title="A failed run can leave a prefix half-updated">
        <p>
          Nautobot cannot change a prefix and its locations in one step. If a
          location change fails after the other fields were written, the device
          leaves through{" "}
          <span className="font-medium text-foreground">failure</span> with{" "}
          <HelpCode>prefix_partially_updated</HelpCode>, and what was already
          written stays. Run the step again to complete it.
        </p>
      </HelpWarning>

      <HelpWarning title="Replace can drop locations">
        <p>
          With <HelpCode>replace</HelpCode> every location that is not in the
          list is removed from the prefix. Use <HelpCode>add</HelpCode> to
          attach a new site without touching the others.
        </p>
      </HelpWarning>

      <HelpWarning title="Several devices, one prefix">
        <p>
          If devices select the same prefix but resolve different values, the
          last write wins, and <HelpCode>add</HelpCode> /{" "}
          <HelpCode>remove</HelpCode> read the current locations first, so
          parallel runs on one prefix can overwrite each other.
        </p>
      </HelpWarning>
    </div>
  );
}
