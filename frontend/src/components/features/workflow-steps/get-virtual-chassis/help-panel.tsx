"use client";

import {
  FanOutHelpSection,
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Get Virtual Chassis.
 * Covers every Configuration control with the LAB.local.zz example.
 */
export function GetVirtualChassisHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Reads virtual chassis (Cisco switch stacks) from Nautobot. A stack is one
          logical device with a single primary IPv4 — the one on the master member.
          The members are separate Nautobot devices, each with its own serial number
          and device type, but their names are unique, so non-master members carry a
          marker such as <HelpCode>LAB:2.local.zz</HelpCode> and cannot be used to
          connect.
        </p>
        <p>
          Every device this step produces connects through the master&apos;s primary
          IPv4. It is an inventory step: place it first, like Get from Nautobot.
        </p>
      </HelpSection>

      <HelpSection title="nautobot_source_id">
        <p>
          Choose a source from Settings → Sources → Nautobot. The URL and token are
          resolved at run time.
        </p>
      </HelpSection>

      <HelpSection title="name_filter and name_match">
        <p>Selects which virtual chassis to read. Empty reads all of them.</p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">Exact name</span> — sent to
            Nautobot as a filter.
          </li>
          <li>
            <span className="font-medium text-foreground">Contains</span> —
            case-insensitive substring.
          </li>
          <li>
            <span className="font-medium text-foreground">Regular expression</span> —
            searched in the name, e.g. <HelpCode>^LAB\.</HelpCode>.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="split_members">
        <p>
          <span className="font-medium text-foreground">Off (default)</span> — one
          device per stack. Its name is the chassis name, its id is the master
          member&apos;s device id, and all members are listed in the attribute bag.
        </p>
        <p>
          <span className="font-medium text-foreground">On</span> — one device per
          member. Each keeps its own name and Nautobot id, but uses the master&apos;s
          primary IPv4. Use this to run a command once per member or to process
          members in parallel with fan-out.
        </p>
        <HelpExample>
          virtual chassis LAB.local.zz
          <br />
          <span className="text-muted-foreground">
            → LAB.local.zz (stack_index 0) and LAB:2.local.zz (stack_index 1), both
            10.0.0.1
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="Stack number: index_regex, index_offset, index_default">
        <p>
          The regular expression runs on each member&apos;s name. The first capture
          group is the number; the offset is added to it. A name without a match gets
          the default.
        </p>
        <HelpExample>
          index_regex: :(\d+) &nbsp; index_offset: -1 &nbsp; index_default: 0
          <br />
          <span className="text-muted-foreground">
            LAB.local.zz → 0 (no match, default)
            <br />
            LAB:2.local.zz → 1 (2 − 1)
            <br />
            LAB:10.local.zz → 9
          </span>
        </HelpExample>
        <HelpWarning title="Keep the pattern short">
          <p>
            Patterns are limited to 200 characters. An invalid expression stops the
            step with a configuration error before anything is read from Nautobot.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="attribute_bag and index_key">
        <p>
          The number is stored in the attribute bag you name, under{" "}
          <HelpCode>index_key</HelpCode>. Later steps read it like any attribute, for
          example to pick one member out of a parsed command.
        </p>
        <HelpExample>
          attribute_bag: virtual_chassis &nbsp; index_key: stack_index
          <br />
          <span className="text-muted-foreground">
            → {"{virtual_chassis.stack_index}"}, {"{virtual_chassis.serial}"},{" "}
            {"{virtual_chassis.is_master}"}
          </span>
        </HelpExample>
        <p>
          In later steps the number can select the matching entry of a list, because a{" "}
          <HelpCode>{"{placeholder}"}</HelpCode> works inside brackets of an attribute
          path (Update Attribute, Route on Attribute). Lists are 0-based, so{" "}
          <HelpCode>{"serial[{virtual_chassis.stack_index}]"}</HelpCode> picks the
          member&apos;s serial from a parsed <HelpCode>show version</HelpCode>.
        </p>
        <HelpExample>
          parsed.k.show version.parsed[0].serial[{"{virtual_chassis.stack_index}"}]
          <br />
          parsed.k.show switch detail.parsed[switch={"{virtual_chassis.position}"}].role
          <br />
          <span className="text-muted-foreground">
            show switch detail numbers members from 1, so use position (1-based) there,
            or join on the MAC address.
          </span>
        </HelpExample>
        <p>
          With split off, the bag holds <HelpCode>vc_id</HelpCode>,{" "}
          <HelpCode>vc_name</HelpCode>, <HelpCode>member_count</HelpCode>,{" "}
          <HelpCode>master</HelpCode> and <HelpCode>members</HelpCode> (each with id,
          name, position, priority, serial, device type, primary IPv4, is_master and
          the number). With split on, it holds the same chassis fields plus that
          member&apos;s own number, position, priority, serial, device type,
          is_master and master_name.
        </p>
        <HelpWarning title="Reserved names">
          <p>
            <HelpCode>parsed</HelpCode>, <HelpCode>run_input</HelpCode> and device
            field names cannot be used as the bag name. Do not reuse{" "}
            <HelpCode>nautobot</HelpCode>: Get Nautobot Attributes replaces that bag.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <p>
          <span className="font-medium text-foreground">success</span> carries the
          devices. <span className="font-medium text-foreground">failure</span>{" "}
          carries stacks whose master has no primary IPv4 (or that have no members);
          they appear as failed devices with the error code{" "}
          <HelpCode>no_primary_ip</HelpCode>.
        </p>
      </HelpSection>

      <FanOutHelpSection />
    </div>
  );
}
