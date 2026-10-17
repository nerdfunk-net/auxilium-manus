export const REPORT_CATEGORY = "report";

/**
 * Starting text of a new report template. It mirrors the built-in default template in
 * backend/services/reports/report_renderer.py (`DEFAULT_TEMPLATE`), so the author starts from what a
 * report without a template would show.
 */
export const REPORT_TEMPLATE_STARTER = `# {{ report.name }}
{% if report.description %}

{{ report.description }}
{% endif %}
{% for s in section_list %}

## {{ s.title }}
{% if s.text %}

{{ s.text }}
{% endif %}
{% if s.status == "error" %}

> This section could not be generated: {{ s.error }}
{% else %}

{{ s.table }}
{% endif %}
{% endfor %}
`;

export interface ReportVariableDoc {
  name: string;
  description: string;
}

/** The variables a report template can use (doc/REPORTS.md, "Report templates"). */
export const REPORT_VARIABLES: ReportVariableDoc[] = [
  {
    name: "report",
    description: "name, description, generated_at (ISO 8601) and generated_by of the snapshot",
  },
  {
    name: "sections",
    description: 'the sections by id, for example sections["per-site"] (use brackets when the id has a “-”)',
  },
  { name: "section_list", description: "the same sections in report order" },
  { name: "<section>.title / .text", description: "title and text of the section" },
  { name: "<section>.status / .error", description: '"ok" or "error", and the reason when it failed' },
  { name: "<section>.rows", description: "list of rows; each row is a dict keyed by column key" },
  { name: "<section>.columns", description: "key, label and type of each column" },
  { name: "<section>.row_count / .truncated", description: "number of stored rows, and whether more matched" },
  { name: "<section>.first", description: "the first row, or none" },
  { name: "<section>.value", description: "first numeric cell of the first row, or none (single numbers)" },
  { name: "<section>.table", description: "the result as a ready-made Markdown table" },
];
