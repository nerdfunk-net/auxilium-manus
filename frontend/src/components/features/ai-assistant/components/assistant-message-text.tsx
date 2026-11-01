"use client";

import { memo } from "react";

import { MarkdownView } from "@/components/ui/markdown-view";

// A wide table scrolls inside the bubble instead of widening the panel, and the last block
// leaves no extra space at the bottom of the bubble.
const MESSAGE_CLASSES = "overflow-x-auto break-words [&>*:last-child]:mb-0";

interface AssistantMessageTextProps {
  markdown: string;
}

/**
 * The model's answer as formatted text (tables, lists, code). Model output is untrusted, so this
 * goes through `MarkdownView`: raw HTML is not rendered, images are blocked and links open in a
 * new tab without the opener. Memoised on the text, so while a reply streams in only the message
 * that changes is parsed again.
 */
export const AssistantMessageText = memo(function AssistantMessageText({
  markdown,
}: AssistantMessageTextProps) {
  return (
    <MarkdownView
      markdown={markdown}
      className={MESSAGE_CLASSES}
      preserveLineBreaks
    />
  );
});
