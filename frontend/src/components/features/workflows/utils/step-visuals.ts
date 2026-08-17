import {
  Bell,
  Camera,
  CheckCircle2,
  Combine,
  Database,
  Diff,
  Eye,
  FileArchive,
  FileText,
  Filter,
  FlaskConical,
  GitBranch,
  GitMerge,
  HardDriveDownload,
  HardDriveUpload,
  Key,
  List,
  LogIn,
  Replace,
  Router,
  Scale,
  SearchCode,
  Settings2,
  ShieldCheck,
  Square,
  Table2,
  Tags,
  TerminalSquare,
  Type,
  type LucideIcon,
  CloudCog,
  Wifi,
} from "lucide-react";

// Shared with the canvas node renderer, the step catalog, and the properties
// panel so every surface agrees on icon/colour per artifact_type or step kind.

export const ARTIFACT_TYPE_ORDER = [
  "nautobot",
  "cisco",
  "pyats",
  "inventory_selector",
  "routing",
  "attributes",
  "content_tools",
  "debug",
  "template_rendering",
  "command_execution",
  "configuration_retrieval",
  "persistent_artifact",
];

export const PALETTE_CATEGORY_LABELS: Record<string, string> = {
  nautobot: "Nautobot",
  cisco: "Cisco",
  pyats: "PyATS",
  configuration_retrieval: "Configuration Management",
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
  "route-on-content": SearchCode,
  "fan-in": GitMerge,
  "filter-output": Filter,
  "merge-content": Combine,
  "update-nautobot-device": CloudCog,
  "set-default-attributes": Settings2,
  "update-attribute": Tags,
  "update-content": Replace,
  "log-attributes": Eye,
  "log-message": List,
  "show-summary": Table2,
  notify: Bell,
  label: Type,
  background: Square,
  "get-ise-devices": ShieldCheck,
  "get-ise-tacacs-key": Key,
  reachable: Wifi,
  "login-successful": LogIn,
  "add-pyats-testbed": FlaskConical,
  // resolveStepIcon's artifact_type fallback is keyed off palette_category
  // (not the step's real artifact_type) once a custom palette_category is
  // set, so any pyats-category step needs an explicit entry here too.
  "get-pyats-config": HardDriveDownload,
  "get-pyats-snapshot": Camera,
  "compare-pyats-snapshot": Diff,
  "upload-config": HardDriveUpload,
};

const nodeIconsByType: Record<string, LucideIcon> = {
  command_execution: TerminalSquare,
  configuration_retrieval: HardDriveDownload,
  control_flow: GitBranch,
  routing: GitBranch,
  attributes: Tags,
  content_tools: Combine,
  debug: Eye,
  canvas_decoration: Square,
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
  routing: "bg-amber-100 text-amber-700",
  attributes: "bg-pink-100 text-pink-700",
  content_tools: "bg-lime-100 text-lime-700",
  debug: "bg-purple-100 text-purple-700",
  canvas_decoration: "bg-purple-100 text-purple-700",
  inventory_selector: "bg-sky-100 text-sky-700",
  nautobot: "bg-step-surface text-step-muted-foreground",
  cisco: "bg-cyan-100 text-cyan-700",
  pyats: "bg-fuchsia-100 text-fuchsia-700",
  persistent_artifact: "bg-violet-100 text-violet-700",
  template_rendering: "bg-orange-100 text-orange-700",
  trigger: "bg-muted text-muted-foreground",
  result: "bg-step-surface text-step-muted-foreground",
};

export const CATEGORY_TILE_FALLBACK = "bg-muted text-muted-foreground";

/** Canvas node left accent border, colour-matched to the category's darker shade. */
export const categoryBorderAccentClasses: Record<string, string> = {
  command_execution: "border-l-emerald-700",
  configuration_retrieval: "border-l-indigo-700",
  control_flow: "border-l-amber-700",
  routing: "border-l-amber-700",
  attributes: "border-l-pink-700",
  content_tools: "border-l-lime-700",
  debug: "border-l-purple-700",
  canvas_decoration: "border-l-purple-700",
  inventory_selector: "border-l-sky-700",
  nautobot: "border-l-step-hover",
  cisco: "border-l-cyan-700",
  pyats: "border-l-fuchsia-700",
  persistent_artifact: "border-l-violet-700",
  template_rendering: "border-l-orange-700",
};

export const CATEGORY_BORDER_FALLBACK = "border-l-border";

export function outcomeClasses(name: string): string {
  const lower = name.toLowerCase();
  if (lower === "success" || lower === "match" || lower === "pass") {
    return "bg-success text-success-foreground border border-success-border";
  }
  if (lower === "failure" || lower === "fail" || lower === "error" || lower === "mismatch") {
    return "bg-error text-error-foreground border border-error-border";
  }
  if (lower === "default") {
    return "bg-warning text-warning-foreground border border-warning-border";
  }
  return "bg-info text-info-foreground border border-info-border";
}

export function outcomeHandleClasses(name: string): string {
  const lower = name.toLowerCase();
  if (lower === "success" || lower === "match" || lower === "pass") {
    return "!bg-success-foreground !border-success-foreground";
  }
  if (lower === "failure" || lower === "fail" || lower === "error" || lower === "mismatch") {
    return "!bg-error-foreground !border-error-foreground";
  }
  if (lower === "default") {
    return "!bg-warning-foreground !border-warning-foreground";
  }
  return "!bg-info-foreground !border-info-foreground";
}

export function outcomeDotClasses(name: string): string {
  const lower = name.toLowerCase();
  if (lower === "success" || lower === "match" || lower === "pass") return "bg-success-foreground";
  if (lower === "failure" || lower === "fail" || lower === "error" || lower === "mismatch") {
    return "bg-error-foreground";
  }
  if (lower === "default") return "bg-warning-foreground";
  return "bg-info-foreground";
}
