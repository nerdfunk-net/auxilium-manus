"use client";

import { ChevronDown, ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";

import type { HelpSection } from "../constants/help-content";

/** The key of one tool in the tree: tool names repeat between sections only by accident. */
export function helpToolKey(sectionId: string, toolName: string): string {
  return `${sectionId}/${toolName}`;
}

interface HelpTreeProps {
  readonly sections: readonly HelpSection[];
  readonly expanded: ReadonlySet<string>;
  readonly selectedKey: string;
  readonly onToggle: (sectionId: string) => void;
  readonly onSelect: (sectionId: string, toolName: string) => void;
}

/** The left panel of the help window: tool groups that open to the tools they hold. */
export function HelpTree({
  sections,
  expanded,
  selectedKey,
  onToggle,
  onSelect,
}: HelpTreeProps) {
  return (
    <nav aria-label="Tools" className="text-sm">
      <ul className="space-y-0.5">
        {sections.map((section) => {
          const isOpen = expanded.has(section.id);
          const Chevron = isOpen ? ChevronDown : ChevronRight;
          return (
            <li key={section.id}>
              <button
                type="button"
                aria-expanded={isOpen}
                className="flex w-full items-center gap-1 rounded px-1.5 py-1 text-left font-medium hover:bg-muted"
                onClick={() => onToggle(section.id)}
              >
                <Chevron className="size-4 shrink-0" aria-hidden />
                <span className="flex-1">{section.title}</span>
                <span className="text-xs font-normal text-muted-foreground">
                  {section.tools.length}
                </span>
              </button>
              {isOpen ? (
                <ul className="ml-4 border-l pl-1">
                  {section.tools.map((tool) => {
                    const key = helpToolKey(section.id, tool.name);
                    const selected = key === selectedKey;
                    return (
                      <li key={key}>
                        <button
                          type="button"
                          aria-current={selected ? "true" : undefined}
                          className={cn(
                            "w-full break-all rounded px-1.5 py-1 text-left font-mono text-xs hover:bg-muted",
                            selected && "bg-muted font-semibold",
                          )}
                          onClick={() => onSelect(section.id, tool.name)}
                        >
                          {tool.name}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
