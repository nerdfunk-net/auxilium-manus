"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/** Built-in Help tab content for Update VLAN. */
export function UpdateNautobotVlanHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Changes an existing VLAN in Nautobot: its name, description, status,
          role and locations. A device whose VLAN was updated, or already had
          every value, leaves through{" "}
          <span className="font-medium text-foreground">success</span>; a device
          that could not be served leaves through{" "}
          <span className="font-medium text-foreground">failure</span>.
        </p>
        <p>
          Only the fields you fill in are changed. An empty field is left as it
          is, and a value cannot be cleared with this step. Running the step
          again is safe: nothing is written when the VLAN already has the
          values.
        </p>
      </HelpSection>

      <HelpSection title="nautobot_source_id">
        <p>The Nautobot source (Settings → Sources) to write to.</p>
      </HelpSection>

      <HelpSection title="vlan_id, vid and vlan_group">
        <p>
          Select the VLAN either by its Nautobot ID (
          <HelpCode>vlan_id</HelpCode>, a fixed UUID or a{" "}
          <HelpCode>{"{path}"}</HelpCode> expression) or by its VLAN ID (
          <HelpCode>vid</HelpCode>, 1-4094). When <HelpCode>vlan_id</HelpCode>{" "}
          is set, <HelpCode>vid</HelpCode> is ignored.
        </p>
        <p>
          The same VID can exist several times in Nautobot. Narrow the lookup
          with <HelpCode>vlan_group</HelpCode> (name or UUID). No match fails
          the device with <HelpCode>vlan_not_found</HelpCode>; several matches
          fail it with <HelpCode>ambiguous_match</HelpCode> and nothing is
          written.
        </p>
        <HelpExample>{"{custom.vlan_id}"}</HelpExample>
      </HelpSection>

      <HelpSection title="name and description">
        <p>
          Fixed text or a <HelpCode>{"{path}"}</HelpCode> expression. An
          expression that resolves to nothing fails the device. A value taken
          from a secret is refused.
        </p>
        <HelpExample>CLIENT-ACCESS</HelpExample>
      </HelpSection>

      <HelpSection title="status">
        <p>
          The new status. The list shows the statuses your Nautobot defines for
          VLANs (for example Active and Deprecated). You can also type a name or
          a <HelpCode>{"{path}"}</HelpCode> expression.
        </p>
      </HelpSection>

      <HelpSection title="role">
        <p>
          The name or UUID of a Nautobot role that applies to VLANs. An unknown
          role fails the device with <HelpCode>role_not_found</HelpCode>.
        </p>
        <HelpExample>Client access</HelpExample>
      </HelpSection>

      <HelpSection title="locations and locations_mode">
        <p>
          A VLAN can belong to several locations, for example a client VLAN 100
          that is used in every site. <HelpCode>locations</HelpCode> is a list
          of location names or UUIDs separated by commas or new lines; each
          entry can also be a <HelpCode>{"{path}"}</HelpCode> expression. Names
          are matched without regard to case. A name that contains a comma must
          be quoted, or given as its UUID. An empty list leaves the locations
          unchanged.
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

      <HelpSection title="VLANs from interfaces and dry_run">
        <p>
          Switch on <HelpCode>vlans_from_interfaces</HelpCode> to update the
          VLANs of the device&apos;s own interfaces instead of one chosen VLAN.
          The step reads the Nautobot attributes of each device (run{" "}
          <span className="font-medium text-foreground">
            Get Nautobot Attributes
          </span>{" "}
          with interfaces first): the tagged and untagged VLAN of every
          interface and the device&apos;s location, both by UUID. It then makes
          sure each VLAN has that location in its list of locations. Locations
          are only added, never removed, and a VLAN that already has the
          location is not written.
        </p>
        <p>
          In this mode the VLAN selector, the fields and{" "}
          <HelpCode>locations</HelpCode> must be empty. A device without a
          location or without interfaces in its attributes fails with{" "}
          <HelpCode>device_location_missing</HelpCode> or{" "}
          <HelpCode>interfaces_missing</HelpCode>; a VLAN is written once per
          location however many devices and interfaces use it. Whether a VLAN
          already has the location is always read from Nautobot, not from the
          attributes, so attributes that are out of date do not matter.
        </p>
        <p>
          <HelpCode>dry_run</HelpCode> writes nothing. Nautobot is read and each
          device gets a preview (<HelpCode>would_add_location</HelpCode>: VLAN
          id, VID and name, and <HelpCode>already_assigned</HelpCode>); the
          counts are in <HelpCode>update_vlan_counts</HelpCode>. Run it first.
          <HelpCode>dry_run</HelpCode> only works together with{" "}
          <HelpCode>vlans_from_interfaces</HelpCode>; on its own the step
          refuses to run instead of writing.
        </p>
      </HelpSection>

      <HelpWarning title="A failed run can leave a VLAN half-updated">
        <p>
          Nautobot cannot change a VLAN and its locations in one step. If a
          location change fails after the other fields were written, the device
          leaves through{" "}
          <span className="font-medium text-foreground">failure</span> with{" "}
          <HelpCode>vlan_partially_updated</HelpCode>, and what was already
          written stays. Run the step again to complete it.
        </p>
      </HelpWarning>

      <HelpWarning title="Replace can drop locations">
        <p>
          With <HelpCode>replace</HelpCode> every location that is not in the
          list is removed from the VLAN. Use <HelpCode>add</HelpCode> to attach
          a new site without touching the others.
        </p>
      </HelpWarning>

      <HelpWarning title="Several devices, one VLAN">
        <p>
          If devices select the same VLAN but resolve different values, the last
          write wins, and <HelpCode>add</HelpCode> / <HelpCode>remove</HelpCode>{" "}
          read the current locations first, so parallel runs on one VLAN can
          overwrite each other. Use one VLAN per device or keep the step out of
          a fan-out that shares it.
        </p>
      </HelpWarning>
    </div>
  );
}
