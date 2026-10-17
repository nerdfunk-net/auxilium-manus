"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Split Virtual Chassis.
 * Walks through the stack → commands → split → update recipe.
 */
export function SplitVirtualChassisHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          A switch stack is reachable on one IP, so a command only needs to run{" "}
          <span className="font-medium text-foreground">once per stack</span>.
          This step comes after that command and replaces each stack device with
          one device per member, so later steps can act on the members
          individually — for example to update every member&apos;s serial number
          in Nautobot.
        </p>
        <p>
          Each member gets its own Nautobot name and device id (the UUID Update
          Device needs). It keeps the stack&apos;s IP and its parsed command
          output, so you still read the output after the split.
        </p>
        <p>
          How a member is numbered is not configured here. Get Virtual Chassis
          already applied its <HelpCode>index_regex</HelpCode>,{" "}
          <HelpCode>index_offset</HelpCode>, <HelpCode>index_default</HelpCode>{" "}
          and <HelpCode>index_key</HelpCode> when it wrote each member into the
          attribute bag. This step copies those values onto the member devices.
        </p>
      </HelpSection>

      <HelpSection title="Typical workflow">
        <HelpExample>
          Get Virtual Chassis (split_members off)
          <br />→ Run Command (parser: textfsm; show version, show switch
          detail)
          <br />→ Split Virtual Chassis
          <br />→ Update Attribute (serial, device type per member)
          <br />→ Update Device (serial, device_type)
        </HelpExample>
      </HelpSection>

      <HelpSection title="Picking a member's values (Update Attribute)">
        <p>
          After the split every member still holds the whole parsed output. Use
          the member&apos;s stack number — the value Get Virtual Chassis stored
          under <HelpCode>index_key</HelpCode> — to pick its entry from a list.
          Lists are 0-based. With the default Get Virtual Chassis settings,{" "}
          <HelpCode>stack_index</HelpCode> is 0 for the master.
        </p>
        <HelpExample>
          source_path:
          <br />
          parsed.parsed.show version.parsed[0].serial[
          {"{virtual_chassis.stack_index}"}]
          <br />
          destination_path: virtual_chassis.detected_serial
          <br />
          <span className="text-muted-foreground">
            Update Device then uses {"{virtual_chassis.detected_serial}"} as the
            serial.
          </span>
        </HelpExample>
        <p>
          <HelpCode>show switch detail</HelpCode> numbers members from 1, so
          select its rows with <HelpCode>position</HelpCode>:
        </p>
        <HelpExample>
          parsed.parsed.show switch detail.parsed[switch=
          {"{virtual_chassis.position}"}].role
        </HelpExample>
        <HelpWarning title="Check that the lists line up with the members">
          <p>
            TextFSM fills the serial and hardware lists of{" "}
            <HelpCode>show version</HelpCode> in the order the switch prints
            them. Compare the MAC address at the same index with the one in{" "}
            <HelpCode>show switch detail</HelpCode> before writing anything to
            Nautobot. Update Attribute skips a path it cannot resolve instead of
            failing the device, so test for an empty result (Route on Attribute)
            if a missing value must stop the update.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="attribute_bag">
        <p>
          Must match <HelpCode>attribute_bag</HelpCode> on the upstream Get
          Virtual Chassis step (default <HelpCode>virtual_chassis</HelpCode>).
          After the split the bag holds that member&apos;s number under the{" "}
          <HelpCode>index_key</HelpCode> from Get Virtual Chassis, plus{" "}
          <HelpCode>position</HelpCode>, <HelpCode>priority</HelpCode>,{" "}
          <HelpCode>serial</HelpCode> and <HelpCode>device_type</HelpCode> as
          stored in Nautobot, <HelpCode>is_master</HelpCode> and{" "}
          <HelpCode>master_name</HelpCode>.
        </p>
        <HelpWarning title="Get Virtual Chassis must run with split_members off">
          <p>
            This step unpacks the <HelpCode>members</HelpCode> list that Get
            Virtual Chassis wrote. With <HelpCode>split_members</HelpCode> on,
            that list is already gone and every device is routed to failure.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the
            member devices of every stack that could be split.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> —
            devices that are not an unsplit stack (for example Get Virtual
            Chassis ran with <HelpCode>split_members</HelpCode> on), devices
            that already failed, and a stack whose member ids appear in another
            stack.
          </li>
        </ul>
      </HelpSection>
    </div>
  );
}
