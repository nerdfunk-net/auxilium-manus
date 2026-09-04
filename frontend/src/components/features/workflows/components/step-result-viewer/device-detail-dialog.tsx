"use client";

import {
  Boxes,
  Braces,
  FileCode2,
  FileText,
  GitCompareArrows,
  Info,
  Layers,
  ScrollText,
  SquareTerminal,
  type LucideIcon,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import type { DeviceContext } from "@/lib/workflow-context-types";

import { CapabilityBadges } from "./capability-badges";
import { ContentViewer } from "./content-viewer";
import { DeviceCommandResultsContent } from "./device-command-results-content";
import { DeviceComparisonDiffsContent } from "./device-comparison-diff-content";
import { DeviceConfigSection } from "./device-config-section";
import { DeviceErrorList } from "./device-error-list";
import { DeviceParsedCommandOutputContent } from "./device-parsed-command-output-content";
import { DeviceParsedTemplatesContent } from "./device-parsed-templates-content";
import { DeviceSnapshotContent } from "./device-snapshot-content";
import { DeviceStatusIcon } from "./devices-section";
import {
  getComparisonDiffEntries,
  getComparisonResultEntries,
  getGenieParsedConfigEntries,
  getParsedCommandOutputEntries,
  getParsedTemplateEntries,
  getSnapshotEntries,
} from "./parsed-guards";

interface DetailSection {
  id: string;
  label: string;
  icon: LucideIcon;
  count?: number;
  render: () => ReactNode;
}

const EMPTY_ATTRIBUTE_BAGS: Record<string, Record<string, unknown>> = {};

export function DeviceDetailDialog({
  device,
  runId,
  open,
  onOpenChange,
}: {
  device: DeviceContext;
  runId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const attributeBags = device.attribute_bags ?? EMPTY_ATTRIBUTE_BAGS;
  const attributeBagNames = useMemo(
    () =>
      Object.keys(attributeBags).filter(
        (name) => Object.keys(attributeBags[name] ?? {}).length > 0,
      ),
    [attributeBags],
  );
  const parsedTemplateEntries = useMemo(
    () => getParsedTemplateEntries(device.parsed ?? {}),
    [device.parsed],
  );
  const comparisonResultEntries = useMemo(
    () => getComparisonResultEntries(device.parsed ?? {}),
    [device.parsed],
  );
  const comparisonDiffEntries = useMemo(
    () => getComparisonDiffEntries(device.parsed ?? {}),
    [device.parsed],
  );
  const genieConfigEntries = useMemo(
    () => getGenieParsedConfigEntries(device.parsed ?? {}),
    [device.parsed],
  );
  const snapshotEntries = useMemo(
    () => getSnapshotEntries(device.parsed ?? {}),
    [device.parsed],
  );
  const parsedCommandOutputEntries = useMemo(
    () => getParsedCommandOutputEntries(device.parsed ?? {}),
    [device.parsed],
  );
  const commandResultCount = useMemo(
    () =>
      Object.values(device.command_results).reduce(
        (total, results) => total + results.length,
        0,
      ),
    [device.command_results],
  );

  const sections = useMemo<DetailSection[]>(() => {
    const list: DetailSection[] = [
      {
        id: "overview",
        label: "Overview",
        icon: Info,
        render: () => (
          <div className="space-y-4 text-sm">
            <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5">
              <dt className="text-muted-foreground">Device ID</dt>
              <dd className="break-all font-mono text-xs">{device.id}</dd>
              <dt className="text-muted-foreground">Hostname</dt>
              <dd className="break-all">{device.hostname || "—"}</dd>
              <dt className="text-muted-foreground">Primary IPv4</dt>
              <dd className="font-mono text-xs">{device.primary_ip4 || "—"}</dd>
              <dt className="text-muted-foreground">Platform</dt>
              <dd>{device.platform || "—"}</dd>
              <dt className="text-muted-foreground">Network driver</dt>
              <dd>{device.network_driver || "—"}</dd>
              <dt className="text-muted-foreground">Source</dt>
              <dd>{device.source || "—"}</dd>
              <dt className="text-muted-foreground">Status</dt>
              <dd className="font-mono text-xs">{device.status}</dd>
            </dl>
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Capabilities
              </p>
              <CapabilityBadges capabilities={device.capabilities} />
            </div>
            <DeviceErrorList errors={device.errors} />
          </div>
        ),
      },
    ];

    if (attributeBagNames.length > 0) {
      list.push({
        id: "attribute-bags",
        label: "Attribute bags",
        icon: Boxes,
        count: attributeBagNames.length,
        render: () => (
          <div className="space-y-4">
            {attributeBagNames.map((name) => (
              <ContentViewer
                key={name}
                label={name}
                content={JSON.stringify(attributeBags[name], null, 2)}
                downloadName={`${device.name}-${name}`}
                height="full"
              />
            ))}
          </div>
        ),
      });
    }

    if (device.running_config_ref || device.startup_config_ref || genieConfigEntries.length > 0) {
      list.push({
        id: "configs",
        label: "Device configs",
        icon: FileText,
        count:
          (device.running_config_ref ? 1 : 0) +
          (device.startup_config_ref ? 1 : 0) +
          genieConfigEntries.length,
        render: () => (
          <DeviceConfigSection
            device={device}
            runId={runId}
            genieConfigEntries={genieConfigEntries}
          />
        ),
      });
    }

    if (commandResultCount > 0) {
      list.push({
        id: "command-output",
        label: "Command output",
        icon: SquareTerminal,
        count: commandResultCount,
        render: () => (
          <DeviceCommandResultsContent
            runId={runId}
            commandResults={device.command_results}
            expanded
          />
        ),
      });
    }

    if (parsedCommandOutputEntries.length > 0) {
      list.push({
        id: "parsed-command-output",
        label: "Parsed command output",
        icon: Braces,
        count: parsedCommandOutputEntries.reduce(
          (total, { entry }) => total + Object.keys(entry).length,
          0,
        ),
        render: () => (
          <DeviceParsedCommandOutputContent entries={parsedCommandOutputEntries} expanded />
        ),
      });
    }

    if (parsedTemplateEntries.length > 0) {
      list.push({
        id: "rendered-templates",
        label: "Rendered templates",
        icon: ScrollText,
        count: parsedTemplateEntries.length,
        render: () => (
          <DeviceParsedTemplatesContent
            runId={runId}
            parsedEntries={parsedTemplateEntries}
            expanded
          />
        ),
      });
    }

    if (comparisonResultEntries.length > 0 || comparisonDiffEntries.length > 0) {
      list.push({
        id: "comparisons",
        label: "Comparisons",
        icon: GitCompareArrows,
        count: comparisonResultEntries.length + comparisonDiffEntries.length,
        render: () => (
          <DeviceComparisonDiffsContent
            runId={runId}
            comparisonResults={comparisonResultEntries}
            comparisonDiffs={comparisonDiffEntries}
            expanded
          />
        ),
      });
    }

    if (snapshotEntries.length > 0) {
      list.push({
        id: "snapshot",
        label: "Genie snapshot",
        icon: Layers,
        count: snapshotEntries.length,
        render: () => (
          <DeviceSnapshotContent runId={runId} entries={snapshotEntries} expanded />
        ),
      });
    }

    // Parsed config lives inside the "Device configs" section (Raw / Parsed tabs);
    // surface it on its own too when it is the only structured output present.
    if (
      genieConfigEntries.length > 0 &&
      !device.running_config_ref &&
      !device.startup_config_ref
    ) {
      const configs = list.find((section) => section.id === "configs");
      if (configs) {
        configs.label = "Parsed config";
        configs.icon = FileCode2;
      }
    }

    return list;
  }, [
    attributeBagNames,
    attributeBags,
    commandResultCount,
    comparisonDiffEntries,
    comparisonResultEntries,
    device,
    genieConfigEntries,
    parsedCommandOutputEntries,
    parsedTemplateEntries,
    runId,
    snapshotEntries,
  ]);

  const [activeId, setActiveId] = useState<string | null>(null);
  const activeSection =
    sections.find((section) => section.id === activeId) ??
    sections.find((section) => section.id !== "overview") ??
    sections[0];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[85vh] max-h-[96vh] min-h-[20rem] w-[64rem] min-w-[30rem] max-w-[96vw] flex-col gap-0 overflow-hidden p-0 resize">
        <DialogHeader className="shrink-0 space-y-1 border-b p-4">
          <DialogTitle className="flex items-center gap-2">
            <DeviceStatusIcon status={device.status} />
            <span className="break-all">{device.name}</span>
            <Badge className="font-mono text-[10px]" variant="outline">
              {device.status}
            </Badge>
          </DialogTitle>
          <DialogDescription className="break-all font-mono text-xs">
            {device.hostname}
            {device.primary_ip4 ? ` · ${device.primary_ip4}` : ""}
          </DialogDescription>
        </DialogHeader>
        <div className="flex min-h-0 flex-1">
          <nav className="w-52 shrink-0 overflow-y-auto border-r p-2">
            {sections.map((section) => {
              const Icon = section.icon;
              const isActive = section.id === activeSection?.id;
              return (
                <button
                  key={section.id}
                  type="button"
                  onClick={() => setActiveId(section.id)}
                  className={cn(
                    "mb-0.5 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors",
                    isActive
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
                  )}
                  aria-current={isActive ? "page" : undefined}
                >
                  <Icon className="size-3.5 shrink-0" aria-hidden />
                  <span className="min-w-0 flex-1 truncate">{section.label}</span>
                  {section.count != null ? (
                    <Badge className="h-4 px-1 text-[10px]" variant="secondary">
                      {section.count}
                    </Badge>
                  ) : null}
                </button>
              );
            })}
          </nav>
          <div className="min-w-0 flex-1 overflow-y-auto p-4">
            {activeSection ? activeSection.render() : null}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
