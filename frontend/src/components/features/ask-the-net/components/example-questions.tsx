"use client";

import { useCallback } from "react";

import { useAssistantSessionStore } from "@/components/features/ai-assistant/store/assistant-session-store";
import { Button } from "@/components/ui/button";

import {
  ASK_THE_NET_SESSION_KEY,
  EXAMPLE_QUESTIONS,
} from "../constants/ask-the-net";

/** Example questions. A click fills the message box; the user sends it, nothing is sent here. */
export function ExampleQuestions() {
  const fill = useCallback((question: string) => {
    useAssistantSessionStore
      .getState()
      .setDraft(ASK_THE_NET_SESSION_KEY, question);
  }, []);

  return (
    <div className="flex flex-wrap gap-2" aria-label="Example questions">
      {EXAMPLE_QUESTIONS.map((question) => (
        <Button
          key={question}
          type="button"
          size="sm"
          variant="outline"
          className="h-auto whitespace-normal py-1.5 text-left font-normal"
          onClick={() => fill(question)}
        >
          {question}
        </Button>
      ))}
    </div>
  );
}
