"use client";

import ReactMarkdown from "react-markdown";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

// Tailwind's preflight strips default heading/list spacing, so a plain
// ReactMarkdown render looks flat — these arbitrary-variant utilities restore
// just enough structure (heading weight/size, list bullets, code background)
// without pulling in the @tailwindcss/typography plugin.
export const MARKDOWN_PREVIEW_CLASSES =
  "text-sm leading-relaxed " +
  "[&_h1]:mt-3 [&_h1]:mb-2 [&_h1]:text-lg [&_h1]:font-semibold [&_h1]:first:mt-0 " +
  "[&_h2]:mt-3 [&_h2]:mb-2 [&_h2]:text-base [&_h2]:font-semibold [&_h2]:first:mt-0 " +
  "[&_h3]:mt-2 [&_h3]:mb-1 [&_h3]:text-sm [&_h3]:font-semibold " +
  "[&_p]:mb-2 [&_ul]:mb-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:mb-2 [&_ol]:list-decimal [&_ol]:pl-5 " +
  "[&_li]:mb-0.5 [&_a]:text-primary [&_a]:underline " +
  "[&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs " +
  "[&_pre]:mb-2 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-muted [&_pre]:p-2 " +
  "[&_blockquote]:mb-2 [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground";

const DEFAULT_TEXTAREA_CLASSES = "h-full min-h-[280px] resize-none font-mono text-sm";

interface MarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  /** Merged onto the root <Tabs> element. */
  className?: string;
  /** Merged onto the write-tab <Textarea>. */
  textareaClassName?: string;
}

/**
 * Presentational Markdown editor: a "Write" textarea and a "Preview" tab that
 * renders the draft with react-markdown. Holds no state of its own — the caller
 * owns `value`/`onChange` and any Save affordance.
 */
export function MarkdownEditor({
  value,
  onChange,
  placeholder,
  className,
  textareaClassName,
}: MarkdownEditorProps) {
  return (
    <Tabs
      defaultValue="write"
      className={cn("flex min-h-0 flex-1 flex-col gap-2", className)}
    >
      <TabsList className="w-fit">
        <TabsTrigger value="write">Write</TabsTrigger>
        <TabsTrigger value="preview">Preview</TabsTrigger>
      </TabsList>
      <TabsContent value="write" className="min-h-0 flex-1">
        <Textarea
          className={cn(DEFAULT_TEXTAREA_CLASSES, textareaClassName)}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          value={value}
        />
      </TabsContent>
      <TabsContent
        value="preview"
        className="min-h-0 flex-1 overflow-y-auto rounded-md border p-3"
      >
        {value.trim() ? (
          <div className={MARKDOWN_PREVIEW_CLASSES}>
            <ReactMarkdown>{value}</ReactMarkdown>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Nothing to preview yet.</p>
        )}
      </TabsContent>
    </Tabs>
  );
}
