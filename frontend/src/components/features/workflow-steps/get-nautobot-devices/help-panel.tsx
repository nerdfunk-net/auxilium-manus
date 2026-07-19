"use client";

import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Get from Nautobot.
 * Covers every Configuration control with practical examples.
 */
export function GetNautobotDevicesHelpPanel(_props: PluginConfigPanelProps) {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Selects target devices from a Nautobot inventory and adds them to the
          workflow context as identity (device name, primary IP, and related
          attributes). Downstream steps such as Get Device Configs, Run Command,
          or Get Nautobot Attributes run against those devices.
        </p>
        <p>
          This is usually the first step in a device-oriented workflow. Configure
          a Nautobot source, pick a saved inventory (filter definition), optionally
          preview the match set, then decide whether to fan out execution per
          device.
        </p>
      </HelpSection>

      <HelpSection title="Nautobot source">
        <p>
          Click{" "}
          <span className="font-medium text-foreground">Configure Source</span>{" "}
          (or Edit Source) and choose a source created under Settings → Sources →
          Nautobot. The step stores that source&apos;s ID as{" "}
          <HelpCode>nautobot_source_id</HelpCode>.
        </p>
        <p>
          Credentials (URL + token) are resolved from settings at preview and run
          time — they are not pasted into the step config.
        </p>
        <HelpExample>
          nautobot_source_id: prod-lab
          <br />
          <span className="text-muted-foreground">
            → resolves to https://nautobot.example.com with the stored token
          </span>
        </HelpExample>
        <HelpWarning title="Source required">
          <p>
            Without a valid source the step cannot preview or resolve devices.
            If the ID is missing from Settings, the Configuration panel shows
            &quot;Source not found in settings&quot;.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Inventory">
        <p>
          Click{" "}
          <span className="font-medium text-foreground">Select inventory</span>{" "}
          to choose a saved inventory. Inventories are filter definitions you
          maintain in the inventory manager (device name, site, role, status,
          tags, custom fields, and nested AND/OR groups).
        </p>
        <p>
          In the picker, use the left sidebar to browse inventory groups, then
          select one inventory on the right. The step stores{" "}
          <HelpCode>inventory_id</HelpCode>,{" "}
          <HelpCode>inventory_name</HelpCode>, and a snapshot of the filter tree
          as <HelpCode>device_filter</HelpCode>. At run time Nautobot is queried
          with that snapshot — editing the saved inventory later does not change
          an already-configured step until you select it again.
        </p>
        <p className="font-medium text-foreground">Example inventories:</p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">Core routers</span> —
            role is <HelpCode>router</HelpCode> AND status is{" "}
            <HelpCode>Active</HelpCode>
          </li>
          <li>
            <span className="font-medium text-foreground">Lab leafs</span> — site
            is <HelpCode>LAB</HelpCode> AND name contains{" "}
            <HelpCode>leaf</HelpCode>
          </li>
          <li>
            <span className="font-medium text-foreground">Tagged backups</span> —
            has tag <HelpCode>backup-eligible</HelpCode>
          </li>
        </ul>
        <HelpExample>
          inventory_id: 42
          <br />
          inventory_name: Core routers
          <br />
          device_filter: {"{"} logic: AND, items: […] {"}"}
        </HelpExample>
        <p>
          Use <span className="font-medium text-foreground">Clear</span> to
          remove the inventory and filter from the step. Use{" "}
          <span className="font-medium text-foreground">Change inventory</span>{" "}
          to pick a different saved definition.
        </p>
      </HelpSection>

      <HelpSection title="Preview devices">
        <p>
          <span className="font-medium text-foreground">Preview devices</span>{" "}
          runs the current filter against the configured Nautobot source and
          lists matching devices before you save or run the workflow. The button
          stays disabled until both a source and an inventory (or legacy filter)
          are ready.
        </p>
        <p>
          Preview is read-only — it does not change the workflow context. Use it
          to validate that your inventory returns the expected set (and roughly
          the right count) before a long run.
        </p>
      </HelpSection>

      <HelpSection title="Fan-out">
        <p>
          When <HelpCode>fan_out</HelpCode> is off (default), the whole workflow
          runs once with every matched device sharing a single context.
        </p>
        <p>
          When enabled, each device — or each chunk of devices — is processed as
          an independent Hatchet child workflow. That parallelises per-device work
          and isolates failures. Place a{" "}
          <span className="font-medium text-foreground">Fan In</span> node before
          any git / shared store steps so those run once on the merged result.
        </p>

        <p className="font-medium text-foreground">Mode</p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-foreground">
              Per device (1 child per device)
            </span>{" "}
            — <HelpCode>mode: per_device</HelpCode>. Best when each device does
            independent SSH/API work (get configs, run commands). Example: 50
            routers → 50 child workflows.
          </li>
          <li>
            <span className="font-medium text-foreground">
              Chunked (N devices per child)
            </span>{" "}
            — <HelpCode>mode: chunked</HelpCode>. Groups devices into batches of{" "}
            <HelpCode>chunk_size</HelpCode>. Useful when you want fewer children
            or mild batching. Example: 50 devices with chunk size{" "}
            <HelpCode>10</HelpCode> → 5 child workflows.
          </li>
        </ul>

        <p className="font-medium text-foreground">Chunk size</p>
        <p>
          Only shown when mode is chunked. Minimum <HelpCode>1</HelpCode>. Larger
          chunks mean fewer children and less orchestration overhead; smaller
          chunks isolate failures more tightly.
        </p>

        <p className="font-medium text-foreground">Max concurrency</p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>0</HelpCode> — unlimited (default). Children may run fully
            in parallel subject to Hatchet/worker capacity.
          </li>
          <li>
            <HelpCode>1</HelpCode> — sequential. One child at a time (gentlest on
            devices and Nautobot/ISE).
          </li>
          <li>
            <HelpCode>5</HelpCode> — at most five children at once. Use when you
            need parallelism but must cap load on the network or controllers.
          </li>
        </ul>

        <HelpExample>
          fan_out:
          <br />
          {"  "}enabled: true
          <br />
          {"  "}mode: per_device
          <br />
          {"  "}chunk_size: 1
          <br />
          {"  "}max_concurrency: 5
        </HelpExample>

        <HelpWarning title="Git and shared stores are not fan-out-safe">
          <ul className="list-disc space-y-0.5 pl-4">
            <li>
              Do not put <HelpCode>store-artifact</HelpCode> (git) or{" "}
              <HelpCode>git-push</HelpCode> on the fanned-out branch — concurrent
              children race on the same working tree.
            </li>
            <li>
              Pattern: inventory (fan-out on) → per-device steps → Fan In →
              store / git-push once.
            </li>
          </ul>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the
            Nautobot query finished. Matched devices (including zero) are in
            context with identity for downstream steps. Always preview if you
            expect a non-empty set.
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
          <li>Configure a Nautobot source (Settings → Sources).</li>
          <li>
            Create or reuse a saved inventory with the filters you need.
          </li>
          <li>
            On this step: select the source, select the inventory, preview the
            device list.
          </li>
          <li>
            Leave fan-out off for a simple linear run, or enable per-device fan-out
            when the next steps are expensive per device — and add Fan In before
            any shared git/export step.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
