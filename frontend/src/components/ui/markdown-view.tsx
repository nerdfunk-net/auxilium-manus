"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

import { MARKDOWN_PREVIEW_CLASSES } from "./markdown-editor";

const TABLE_CLASSES =
  "[&_table]:mb-3 [&_table]:w-full [&_table]:border-collapse [&_table]:text-xs " +
  "[&_th]:border [&_th]:bg-muted [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:font-semibold " +
  "[&_td]:border [&_td]:px-2 [&_td]:py-1";

interface MarkdownViewProps {
  markdown: string;
  className?: string;
}

/**
 * Read-only Markdown with GitHub-style tables. Raw HTML in the text is not rendered (react-markdown
 * ignores it unless a plugin enables it) and unsafe link protocols are dropped, so text that came
 * from a user-written template cannot inject markup.
 */
export function MarkdownView({ markdown, className }: MarkdownViewProps) {
  return (
    <div className={cn(MARKDOWN_PREVIEW_CLASSES, TABLE_CLASSES, className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        // Data values can contain Markdown: an image would make the browser fetch an address
        // chosen by whoever wrote the value, and a link would lead there.
        disallowedElements={["img"]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer nofollow">
              {children}
            </a>
          ),
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
