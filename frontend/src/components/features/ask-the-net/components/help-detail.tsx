"use client";

import { Button } from "@/components/ui/button";

import type { HelpSection, HelpTool } from "../constants/help-content";

interface HelpDetailProps {
  readonly section: HelpSection;
  readonly tool: HelpTool;
  readonly onPick: (question: string) => void;
}

/** The right panel of the help window: the chosen tool, its group and questions that use it. */
export function HelpDetail({ section, tool, onPick }: HelpDetailProps) {
  return (
    <article className="space-y-4">
      <header className="space-y-1">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          {section.title}
        </p>
        <h3 className="break-all font-mono text-base font-semibold">
          {tool.name}
        </h3>
      </header>
      <p className="text-sm">{tool.description}</p>
      <div className="space-y-2">
        <h4 className="text-sm font-medium">Questions to try</h4>
        <div className="flex flex-wrap gap-2">
          {tool.questions.map((question) => (
            <Button
              key={question}
              type="button"
              size="sm"
              variant="outline"
              className="h-auto whitespace-normal py-1 text-left font-normal"
              onClick={() => onPick(question)}
            >
              {question}
            </Button>
          ))}
        </div>
      </div>
      <div className="space-y-1 rounded-md border bg-muted/40 p-3 text-xs text-muted-foreground">
        <p className="font-medium text-foreground">About {section.title}</p>
        <p>{section.summary}</p>
        {section.requirement ? <p>{section.requirement}</p> : null}
      </div>
    </article>
  );
}
