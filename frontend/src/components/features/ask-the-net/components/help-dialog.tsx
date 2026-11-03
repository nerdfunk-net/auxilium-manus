"use client";

import { CircleHelp } from "lucide-react";
import { useCallback, useState } from "react";

import { useAssistantSessionStore } from "@/components/features/ai-assistant/store/assistant-session-store";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

import { ASK_THE_NET_SESSION_KEY } from "../constants/ask-the-net";
import { HELP_SECTIONS } from "../constants/help-content";

/**
 * The help button and its page: every tool group with its tools and questions to ask. Choosing a
 * question closes the window and puts it into the message box; the user sends it, nothing is
 * sent here.
 */
export function HelpDialog() {
  const [open, setOpen] = useState(false);

  const pick = useCallback((question: string) => {
    useAssistantSessionStore
      .getState()
      .setDraft(ASK_THE_NET_SESSION_KEY, question);
    setOpen(false);
  }, []);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button type="button" variant="outline" size="sm">
          <CircleHelp className="size-4" aria-hidden />
          Help
        </Button>
      </DialogTrigger>
      <DialogContent className="flex max-h-[85vh] max-w-3xl flex-col">
        <DialogHeader>
          <DialogTitle>What can I ask?</DialogTitle>
          <DialogDescription>
            The assistant answers with the tools below. Click a question to
            put it into the message box.
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-6 overflow-y-auto pr-1">
          {HELP_SECTIONS.map((section) => (
            <section key={section.id} aria-labelledby={`help-${section.id}`}>
              <h3 id={`help-${section.id}`} className="font-semibold">
                {section.title}
              </h3>
              <p className="text-sm text-muted-foreground">{section.summary}</p>
              {section.requirement ? (
                <p className="text-xs text-muted-foreground">
                  {section.requirement}
                </p>
              ) : null}
              <div className="mt-3 space-y-3">
                {section.tools.map((tool) => (
                  <div key={tool.name} className="space-y-1.5">
                    <p className="text-sm">
                      <code className="rounded bg-muted px-1 py-0.5 text-xs">
                        {tool.name}
                      </code>{" "}
                      <span className="text-muted-foreground">
                        {tool.description}
                      </span>
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {tool.questions.map((question) => (
                        <Button
                          key={question}
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-auto whitespace-normal py-1 text-left font-normal"
                          onClick={() => pick(question)}
                        >
                          {question}
                        </Button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
