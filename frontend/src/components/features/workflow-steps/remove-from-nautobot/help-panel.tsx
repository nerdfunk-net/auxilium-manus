"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/** Built-in Help tab content for Remove from Nautobot. */
export function RemoveFromNautobotHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Deletes a device from Nautobot. The device is identified by its Nautobot ID (UUID) only,
          so a name or address can never select the wrong device. A device that was removed leaves
          through <span className="font-medium text-foreground">success</span>; a device that could
          not be removed leaves through{" "}
          <span className="font-medium text-foreground">failure</span> with the reason in its
          error (<HelpCode>device_not_found</HelpCode>, <HelpCode>device_id_invalid</HelpCode>,{" "}
          <HelpCode>ip_delete_failed</HelpCode>, …).
        </p>
      </HelpSection>

      <HelpSection title="nautobot_source_id">
        <p>The Nautobot source (Settings → Sources) to delete from.</p>
      </HelpSection>

      <HelpSection title="device_id">
        <p>
          The Nautobot ID of the device: a fixed UUID or a per-device <HelpCode>{"{path}"}</HelpCode>{" "}
          expression. The default <HelpCode>{"{device.id}"}</HelpCode> is the id of a device that
          came from Nautobot. A value that is not a UUID fails the device with{" "}
          <HelpCode>device_id_invalid</HelpCode>; an unknown UUID fails it with{" "}
          <HelpCode>device_not_found</HelpCode> and nothing is deleted.
        </p>
        <HelpExample>{"{device.id}"}</HelpExample>
        <HelpExample>{"{custom.nautobot_id}"}</HelpExample>
      </HelpSection>

      <HelpSection title="remove_ip_addresses">
        <p>
          When enabled, each IP address assigned to the device&apos;s interfaces is checked first.
          An address that another device or a virtual machine also holds is kept; the step counts
          it in <HelpCode>ips_shared_skipped</HelpCode>. An address only this device holds is
          deleted, then the device. If an answer from Nautobot cannot confirm that the device is
          the only holder, the address is kept.
        </p>
        <p>
          Devices are removed one after another, so when two devices of the same run share an
          address, the second one to go is the last holder and removes it.
        </p>
        <p>
          When disabled (the default), only the device is deleted. Nautobot then keeps its
          addresses as unassigned.
        </p>
      </HelpSection>

      <HelpWarning title="Nautobot cannot delete a device and its addresses together">
        <p>
          The addresses are deleted before the device. If the device delete then fails, the
          addresses stay deleted. The device leaves through <span className="font-medium">failure</span>{" "}
          and its error (<HelpCode>device_delete_failed</HelpCode>) lists the addresses that were
          removed, so you can check and restore them in Nautobot. If an address cannot be deleted
          the device is not removed (<HelpCode>ip_delete_failed</HelpCode>); running the step again
          continues where it stopped.
        </p>
      </HelpWarning>

      <HelpWarning title="Removal is permanent">
        <p>
          Nautobot has no recycle bin. Deleting a device also deletes its interfaces and other
          objects that belong to it. Put a check (for example Route on Attribute) in front of this
          step when the device list is not fixed.
        </p>
      </HelpWarning>

      <HelpWarning title="Several devices, one UUID">
        <p>
          If two devices resolve to the same UUID, the second one fails with{" "}
          <HelpCode>device_not_found</HelpCode> because the first already removed it.
        </p>
      </HelpWarning>
    </div>
  );
}
