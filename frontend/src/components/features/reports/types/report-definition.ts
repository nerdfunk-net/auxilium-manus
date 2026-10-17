/** Mirrors backend/models/report_definitions.py. */

import type { QueryResult, ReportQuerySpec } from "./report-query";

export type Presentation = "table" | "number" | "bar" | "line";
export type SnapshotStatus = "complete" | "partial";

export const PRESENTATION_LABELS: Record<Presentation, string> = {
  table: "Table",
  number: "Single number",
  bar: "Bar chart",
  line: "Line chart",
};

export const MAX_SECTIONS = 20;

export interface ReportSection {
  id: string;
  title: string;
  query: ReportQuerySpec;
  presentation: Presentation;
  text: string | null;
}

export interface ReportDefinition {
  id: number;
  name: string;
  description: string | null;
  sections: ReportSection[];
  template_id: number | null;
  /** Addresses the Send dialog proposes. */
  default_recipients: string[];
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface ReportDefinitionSummary {
  id: number;
  name: string;
  description: string | null;
  section_count: number;
  updated_at: string;
  snapshot_count: number;
  last_generated_at: string | null;
}

export interface ReportDefinitionInput {
  name: string;
  description: string | null;
  sections: ReportSection[];
  /** Report template (category "report"); null uses the built-in default. */
  template_id: number | null;
  default_recipients: string[];
}

export interface SendSnapshotInput {
  to: string[];
  subject: string | null;
  message: string | null;
  include_pdf: boolean;
}

export interface SendSnapshotResult {
  sent_to: string[];
  pdf_attached: boolean;
}

export interface SnapshotSection {
  section: ReportSection;
  status: "ok" | "error";
  result: QueryResult | null;
  error: string | null;
  truncated: boolean;
}

/** The report rendered through its template: Markdown, or the reason there is none. */
export interface SnapshotBody {
  template_id: number | null;
  /** Empty for the built-in default template. */
  template_name: string;
  markdown: string | null;
  error: string | null;
}

export interface SnapshotContent {
  name: string;
  description: string | null;
  sections: SnapshotSection[];
  /** Absent in snapshots generated before report templates existed. */
  body?: SnapshotBody | null;
}

export interface TemplatePreview {
  markdown: string | null;
  error: string | null;
}

export interface ReportSnapshotSummary {
  id: number;
  definition_id: number | null;
  name: string;
  generated_by: string | null;
  status: SnapshotStatus;
  generated_at: string;
}

export interface ReportSnapshot extends ReportSnapshotSummary {
  content: SnapshotContent;
}
