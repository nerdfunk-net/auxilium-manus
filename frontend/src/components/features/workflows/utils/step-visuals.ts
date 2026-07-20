import {
  CheckCircle2,
  Combine,
  Database,
  Eye,
  FileArchive,
  FileText,
  Filter,
  GitBranch,
  GitMerge,
  HardDriveDownload,
  Key,
  List,
  Router,
  Scale,
  ShieldCheck,
  Tags,
  TerminalSquare,
  type LucideIcon,
  CloudCog,
} from "lucide-react";

// Shared with the canvas node renderer, the step catalog, and the properties
// panel so every surface agrees on icon/colour per artifact_type or step kind.

export const ARTIFACT_TYPE_ORDER = [
  "nautobot",
  "cisco",
  "inventory_selector",
  "control_flow",
  "template_rendering",
  "command_execution",
  "configuration_retrieval",
  "persistent_artifact",
];

export const PALETTE_CATEGORY_LABELS: Record<string, string> = {
  nautobot: "Nautobot",
  cisco: "Cisco",
};

export function formatPaletteCategory(category: string): string {
  return (
    PALETTE_CATEGORY_LABELS[category] ??
    formatArtifactType(category)
  );
}

export function formatArtifactType(artifactType: string): string {
  return artifactType
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

const nodeIconsByKind: Record<string, LucideIcon> = {
  "compare-data": Scale,
  "fan-in": GitMerge,
  "filter-output": Filter,
  "merge-content": Combine,
  "update-nautobot-device": CloudCog,
  "update-attribute": Tags,
  "log-attributes": Eye,
  "workflow-log": List,
  "get-ise-devices": ShieldCheck,
  "get-ise-tacacs-key": Key,
};

const nodeIconsByType: Record<string, LucideIcon> = {
  command_execution: TerminalSquare,
  configuration_retrieval: HardDriveDownload,
  control_flow: GitBranch,
  inventory_selector: Router,
  persistent_artifact: FileArchive,
  template_rendering: FileText,
  trigger: GitBranch,
  result: CheckCircle2,
};

export function resolveStepIcon(kind: string, artifactType: string): LucideIcon {
  return nodeIconsByKind[kind] ?? nodeIconsByType[artifactType] ?? Database;
}

/** Icon tile background/text — canvas node icon, catalog tiles, properties header. */
export const categoryTileClasses: Record<string, string> = {
  command_execution: "bg-emerald-100 text-emerald-700",
  configuration_retrieval: "bg-indigo-100 text-indigo-700",
  control_flow: "bg-amber-100 text-amber-700",
  inventory_selector: "bg-sky-100 text-sky-700",
  nautobot: "bg-teal-100 text-teal-700",
  cisco: "bg-cyan-100 text-cyan-700",
  persistent_artifact: "bg-violet-100 text-violet-700",
  template_rendering: "bg-orange-100 text-orange-700",
  trigger: "bg-slate-100 text-slate-700",
  result: "bg-teal-100 text-teal-700",
};

export const CATEGORY_TILE_FALLBACK = "bg-muted text-muted-foreground";

/** Canvas node left accent border, colour-matched to the category's darker shade. */
export const categoryBorderAccentClasses: Record<string, string> = {
  command_execution: "border-l-emerald-700",
  configuration_retrieval: "border-l-indigo-700",
  control_flow: "border-l-amber-700",
  inventory_selector: "border-l-sky-700",
  nautobot: "border-l-teal-700",
  cisco: "border-l-cyan-700",
  persistent_artifact: "border-l-violet-700",
  template_rendering: "border-l-orange-700",
};

export const CATEGORY_BORDER_FALLBACK = "border-l-border";

export function outcomeClasses(name: string): string {
  const lower = name.toLowerCase();
  if (lower === "success" || lower === "match" || lower === "pass") {
    return "bg-green-50 text-green-700 border border-green-200";
  }
  if (lower === "failure" || lower === "fail" || lower === "error" || lower === "mismatch") {
    return "bg-red-50 text-red-700 border border-red-200";
  }
  if (lower === "default") {
    return "bg-amber-50 text-amber-700 border border-amber-200";
  }
  return "bg-sky-50 text-sky-700 border border-sky-200";
}

export function outcomeHandleClasses(name: string): string {
  const lower = name.toLowerCase();
  if (lower === "success" || lower === "match" || lower === "pass") {
    return "!bg-green-500 !border-green-600";
  }
  if (lower === "failure" || lower === "fail" || lower === "error" || lower === "mismatch") {
    return "!bg-red-500 !border-red-600";
  }
  if (lower === "default") {
    return "!bg-amber-500 !border-amber-600";
  }
  return "!bg-sky-500 !border-sky-600";
}

export function outcomeDotClasses(name: string): string {
  const lower = name.toLowerCase();
  if (lower === "success" || lower === "match" || lower === "pass") return "bg-green-500";
  if (lower === "failure" || lower === "fail" || lower === "error" || lower === "mismatch") {
    return "bg-red-500";
  }
  if (lower === "default") return "bg-amber-500";
  return "bg-sky-500";
}
