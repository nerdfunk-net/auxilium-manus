"use client";

import {
  ArrowDownToLine,
  ChevronsRight,
  GitBranch,
  MoveRight,
  Settings2,
  type LucideIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { TabsContent } from "@/components/ui/tabs";

import type {
  PluginDefinition,
  PluginIOField,
  PluginStepOutcome,
} from "../types/plugin-registry";
import type { PersistedCanvasNode } from "../types/workflow-canvas";

const MODAL_TAB_CONTENT_CLASS = "mt-0 min-h-0 flex-1 overflow-y-auto p-6";

function formatArtifactType(artifactType: string) {
  return artifactType
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function SectionHeader({
  icon: Icon,
  label,
}: {
  icon: LucideIcon;
  label: string;
}) {
  return (
    <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
      <Icon className="size-3.5" />
      {label}
    </div>
  );
}

function FieldRow({ field }: { field: PluginIOField }) {
  return (
    <div className="rounded-lg border bg-background/60 px-3 py-2">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs font-medium">{field.name}</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          {field.data_type}
        </Badge>
        {field.required && (
          <span className="ml-auto text-[10px] text-destructive">required</span>
        )}
      </div>
      {field.description ? (
        <p className="mt-1 text-[11px] leading-4 text-muted-foreground">{field.description}</p>
      ) : null}
    </div>
  );
}

function OutcomeRow({ outcome }: { outcome: PluginStepOutcome }) {
  return (
    <div className="rounded-lg border bg-background/60 px-3 py-2">
      <span className="font-mono text-xs font-medium">{outcome.name}</span>
    </div>
  );
}

function CapabilityList({
  icon: Icon,
  label,
  values,
}: {
  icon: LucideIcon;
  label: string;
  values: string[];
}) {
  if (values.length === 0) {
    return null;
  }

  return (
    <div className="space-y-1.5">
      <SectionHeader icon={Icon} label={label} />
      <div className="flex flex-wrap gap-1.5">
        {values.map((value) => (
          <Badge key={value} className="font-mono text-[10px]" variant="secondary">
            {value}
          </Badge>
        ))}
      </div>
    </div>
  );
}

export function MockConfigRow({ field }: { field: PluginIOField }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs font-medium">{field.name}</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          {field.data_type}
        </Badge>
        {field.required && (
          <span className="ml-auto text-[10px] text-destructive">required</span>
        )}
      </div>
      <div className="rounded border bg-muted/40 px-2 py-1.5 text-[11px] text-muted-foreground">
        {field.example != null
          ? String(field.example)
          : field.default != null
            ? String(field.default)
            : "—"}
      </div>
    </div>
  );
}

interface NodeConfigDescriptionTabProps {
  activeNode: PersistedCanvasNode;
  plugin: PluginDefinition | undefined;
}

export function NodeConfigDescriptionTab({ activeNode, plugin }: NodeConfigDescriptionTabProps) {
  return (
    <TabsContent className={MODAL_TAB_CONTENT_CLASS} value="description">
      <div className="space-y-4">
        <div>
          {activeNode.data.artifactType ? (
            <Badge className="mb-2" variant="secondary">
              {formatArtifactType(activeNode.data.artifactType)}
            </Badge>
          ) : null}
          <h2 className="text-base font-semibold">{activeNode.data.title}</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {activeNode.data.description}
          </p>
        </div>

        {plugin ? (
          <>
            {(plugin.produces.length > 0 ||
              plugin.produces_parsed.length > 0 ||
              plugin.consumes.length > 0) ? (
              <div className="space-y-3 rounded-lg border bg-muted/20 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Capabilities
                </p>
                <CapabilityList icon={MoveRight} label="Produces" values={plugin.produces} />
                {plugin.produces_parsed.length > 0 ? (
                  <CapabilityList
                    icon={MoveRight}
                    label="Produces parsed"
                    values={plugin.produces_parsed}
                  />
                ) : null}
                <CapabilityList icon={ChevronsRight} label="Consumes" values={plugin.consumes} />
              </div>
            ) : null}

            {(plugin.metadata.configuration_input.length > 0 ||
              plugin.requires.length > 0 ||
              plugin.requires_parsed.length > 0 ||
              plugin.outcomes.length > 0) ? (
              <div className="space-y-4 rounded-lg border bg-muted/20 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Schema
                </p>
                {plugin.metadata.configuration_input.length > 0 ? (
                  <div className="space-y-1.5">
                    <SectionHeader icon={Settings2} label="Configuration inputs" />
                    {plugin.metadata.configuration_input.map((field) => (
                      <FieldRow field={field} key={field.name} />
                    ))}
                  </div>
                ) : null}
                {plugin.requires.length > 0 ? (
                  <CapabilityList
                    icon={ArrowDownToLine}
                    label="Requires"
                    values={plugin.requires}
                  />
                ) : null}
                {plugin.requires_parsed.length > 0 ? (
                  <CapabilityList
                    icon={ArrowDownToLine}
                    label="Requires parsed"
                    values={plugin.requires_parsed}
                  />
                ) : null}
                {plugin.outcomes.length > 0 ? (
                  <div className="space-y-1.5">
                    <SectionHeader icon={GitBranch} label="Outcomes" />
                    {plugin.outcomes.map((outcome) => (
                      <OutcomeRow key={outcome.name} outcome={outcome} />
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
          </>
        ) : (
          <p className="text-xs text-muted-foreground">Plugin metadata not available.</p>
        )}
      </div>
    </TabsContent>
  );
}
