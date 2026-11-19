import type { HelpSection } from "../constants/help-content";

/**
 * Keeps the tools whose text contains every word of the query (case-insensitive). A word found in
 * the group's title, summary or requirement keeps all tools of that group. Groups without a match
 * are left out; an empty query returns the sections unchanged.
 */
export function filterHelpSections(
  sections: readonly HelpSection[],
  query: string,
): readonly HelpSection[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return sections;
  const matches = (text: string) =>
    words.every((word) => text.toLowerCase().includes(word));

  const result: HelpSection[] = [];
  for (const section of sections) {
    const sectionText = [section.title, section.summary, section.requirement]
      .filter(Boolean)
      .join(" ");
    if (matches(sectionText)) {
      result.push(section);
      continue;
    }
    const tools = section.tools.filter((tool) =>
      matches(
        [sectionText, tool.name, tool.description, ...tool.questions].join(" "),
      ),
    );
    if (tools.length > 0) result.push({ ...section, tools });
  }
  return result;
}
