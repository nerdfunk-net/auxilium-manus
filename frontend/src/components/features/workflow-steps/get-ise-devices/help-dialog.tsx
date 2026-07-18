"use client";

import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface IseDevicesHelpDialogProps {
  open: boolean;
  onClose: () => void;
}

function Code({ children }: { children: string }) {
  return (
    <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
      {children}
    </code>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold">{title}</h3>
      <div className="space-y-2 text-xs leading-5 text-muted-foreground">
        {children}
      </div>
    </div>
  );
}

export function IseDevicesHelpDialog({ open, onClose }: IseDevicesHelpDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="flex max-h-[85vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl">
        <DialogHeader className="shrink-0 border-b bg-white px-6 py-4">
          <DialogTitle>Get from ISE — Help</DialogTitle>
          <DialogDescription>
            How each lookup mode works, with examples — including the part
            that trips people up if they haven&apos;t used Cisco ISE&apos;s
            network device groups before.
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
          <Section title="What this step does">
            <p>
              Looks up network devices already registered in Cisco ISE (as
              RADIUS/TACACS clients) and turns them into workflow targets.
              This is a different device inventory than Nautobot — ISE only
              knows about devices someone explicitly registered with it for
              network access control, so it&apos;s normal for ISE to have far
              fewer devices than Nautobot for the same subnet.
            </p>
            <p>
              A source must be configured first via the{" "}
              <span className="font-medium text-foreground">
                Configure Source
              </span>{" "}
              button (Settings → Sources → Cisco ISE).
            </p>
          </Section>

          <Section title="Device name(s)">
            <p>
              One ISE device name per line, exactly as it&apos;s named in
              ISE. Each line does one direct lookup; a name that doesn&apos;t
              exist in ISE is silently skipped (check the run logs for a
              &quot;not found in ISE&quot; warning per name).
            </p>
            <div className="rounded-md border bg-muted/40 p-2 font-mono text-[11px]">
              lab
              <br />
              lab-001
              <br />
              lab-002
            </div>
          </Section>

          <Section title="IP address / CIDR">
            <p>
              A single host address (e.g. <Code>192.168.178.1</Code> or{" "}
              <Code>192.168.178.1/32</Code>) does one fast, exact-match
              lookup.
            </p>
            <p>
              A wider prefix (e.g. <Code>192.168.178.0/24</Code>) has to scan
              every device ISE has registered and check each one&apos;s IP
              client-side — ISE has no native CIDR filter. This is
              intentionally the full scan at run time; the &quot;Show
              Preview&quot; button caps the scan at 500 devices for speed.
            </p>
          </Section>

          <Section title="Network device group — naming (read this one)">
            <p>
              ISE has no separate parent-group field. A group&apos;s full
              hierarchy is one <Code>#</Code>-delimited string, and you must
              enter that{" "}
              <span className="font-medium text-foreground">
                exact full string
              </span>{" "}
              — not just the name you see on the device or in ISE&apos;s UI.
              Getting this wrong doesn&apos;t error, it just silently
              returns zero devices.
            </p>

            <p className="font-medium text-foreground">The pattern:</p>
            <ul className="list-disc space-y-1 pl-4">
              <li>
                The <span className="font-medium text-foreground">first</span>{" "}
                segment is the group&apos;s category (built-in categories:{" "}
                <Code>Location</Code>, <Code>Device Type</Code>,{" "}
                <Code>IPSEC</Code> — or a custom one your ISE admin created,
                e.g. <Code>myGroup</Code>).
              </li>
              <li>
                The <span className="font-medium text-foreground">root</span>{" "}
                member of any category repeats the category name:{" "}
                <Code>{"{category}#{category}"}</Code>. For a custom category{" "}
                <Code>myGroup</Code>, its root is <Code>myGroup#myGroup</Code>{" "}
                — not just <Code>myGroup</Code> (ISE rejects a bare
                single-segment name for a new category).
              </li>
              <li>
                Every child appends its own name onto the parent&apos;s{" "}
                <span className="font-medium text-foreground">full</span>{" "}
                name: <Code>{"{parent-full-name}#{child-name}"}</Code>.
              </li>
            </ul>

            <p className="font-medium text-foreground">Worked example:</p>
            <p>
              A custom category <Code>myGroup</Code> with a child group named{" "}
              <Code>my-test-001</Code> has this full hierarchy:
            </p>
            <div className="rounded-md border bg-muted/40 p-2 font-mono text-[11px] leading-5">
              myGroup#myGroup{" "}
              <span className="text-muted-foreground">(the root)</span>
              <br />
              myGroup#myGroup#my-test-001{" "}
              <span className="text-muted-foreground">
                (child &quot;my-test-001&quot;)
              </span>
            </div>
            <p>
              To find devices tagged with the child group, enter{" "}
              <Code>myGroup#myGroup#my-test-001</Code> — the full 3-segment
              string, including the repeated <Code>myGroup</Code>.
            </p>

            <p>Some built-in examples, for comparison:</p>
            <div className="rounded-md border bg-muted/40 p-2 font-mono text-[11px] leading-5">
              Location#All Locations
              <br />
              Location#All Locations#Building1
              <br />
              Device Type#All Device Types
              <br />
              IPSEC#Is IPSEC Device#No
            </div>

            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800">
              <p className="font-medium">Common mistakes that return 0 devices</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                <li>
                  Entering just the leaf name (<Code>my-test-001</Code>) with
                  no category prefix at all.
                </li>
                <li>
                  Entering <Code>{"{category}#{child}"}</Code> without
                  repeating the category (
                  <Code>myGroup#my-test-001</Code> instead of{" "}
                  <Code>myGroup#myGroup#my-test-001</Code>).
                </li>
                <li>
                  Group membership is a flat tag, not an inherited tree —
                  querying the root (<Code>myGroup#myGroup</Code>) only
                  returns devices tagged with that exact root string, not
                  devices tagged with its children too (and vice versa).
                </li>
              </ul>
            </div>

            <p className="font-medium text-foreground">
              How to find the exact name:
            </p>
            <p>
              Under Settings → Sources → Cisco ISE, or directly in ISE&apos;s
              own admin console (Administration → Network Resources →
              Network Device Groups) — the <Code>Name</Code> column there is
              already the full hierarchical string to paste in here. You can
              also switch this step to{" "}
              <span className="font-medium text-foreground">
                Device name(s)
              </span>{" "}
              mode, preview a device you know is in the group, and read the
              group name straight off its{" "}
              <Code>NetworkDeviceGroupList</Code> entries.
            </p>
          </Section>

          <Section title="Resolve to devices">
            <p>
              When an ISE entry&apos;s IP uses a netmask other than{" "}
              <Code>/32</Code>, it may represent a subnet or group rather
              than one host. Enabling this expands such entries into
              individual devices by matching Nautobot&apos;s{" "}
              <span className="mx-0.5 inline-flex h-4 items-center rounded-md border border-transparent bg-secondary px-1 text-[10px] font-medium text-secondary-foreground">
                Primary Prefix
              </span>{" "}
              filter against the CIDR — requires a Nautobot source to be
              configured too. If nothing matches in Nautobot, the raw ISE
              entry is kept as-is rather than dropped.
            </p>
          </Section>
        </div>

        <DialogFooter className="shrink-0 border-t bg-white px-6 py-3">
          <Button type="button" variant="outline" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
