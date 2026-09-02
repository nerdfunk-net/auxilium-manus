"use client";

import {
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  Download,
  Search,
  X,
} from "lucide-react";
import { Fragment, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface ContentViewerProps {
  content: string;
  label: string;
  sizeBytes?: number | null;
  /** Filename stem for downloads (extension is appended). */
  downloadName?: string;
  /** "sm" keeps the inline preview height; "full" expands it for the detail dialog. */
  height?: "sm" | "full";
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

interface Segment {
  text: string;
  /** Zero-based ordinal among all matches, or null for non-matching text. */
  matchIndex: number | null;
}

function splitOnQuery(content: string, query: string): Segment[] {
  if (!query) {
    return [{ text: content, matchIndex: null }];
  }

  const segments: Segment[] = [];
  const regex = new RegExp(escapeRegExp(query), "gi");
  let lastIndex = 0;
  let matchOrdinal = 0;
  let result: RegExpExecArray | null;

  while ((result = regex.exec(content)) !== null) {
    if (result.index > lastIndex) {
      segments.push({ text: content.slice(lastIndex, result.index), matchIndex: null });
    }
    segments.push({ text: result[0], matchIndex: matchOrdinal });
    matchOrdinal += 1;
    lastIndex = result.index + result[0].length;
    if (result[0].length === 0) {
      regex.lastIndex += 1;
    }
  }

  if (lastIndex < content.length) {
    segments.push({ text: content.slice(lastIndex), matchIndex: null });
  }

  return segments;
}

export function ContentViewer({
  content,
  label,
  sizeBytes,
  downloadName,
  height = "sm",
}: ContentViewerProps) {
  const [copied, setCopied] = useState(false);
  const [showFind, setShowFind] = useState(false);
  const [query, setQuery] = useState("");
  const [activeMatch, setActiveMatch] = useState(0);
  const activeMarkRef = useRef<HTMLElement | null>(null);

  const segments = useMemo(() => splitOnQuery(content, query), [content, query]);
  const matchCount = useMemo(
    () => segments.reduce((total, segment) => total + (segment.matchIndex != null ? 1 : 0), 0),
    [segments],
  );
  const currentMatch =
    matchCount === 0 ? 0 : ((activeMatch % matchCount) + matchCount) % matchCount;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API unavailable (e.g. non-secure context) — silently ignore.
    }
  };

  const handleDownload = () => {
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${
      downloadName ?? label.toLowerCase().replace(/\s+/g, "-")
    }.txt`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  };

  const stepMatch = (delta: number) => {
    if (matchCount === 0) {
      return;
    }
    setActiveMatch((value) => value + delta);
    window.requestAnimationFrame(() => {
      activeMarkRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
    });
  };

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
          {sizeBytes != null ? (
            <span className="ml-1.5 font-normal normal-case tracking-normal">
              · {sizeBytes.toLocaleString()} bytes
            </span>
          ) : null}
        </p>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 gap-1 px-1.5 text-[11px] [&_svg]:size-3"
            onClick={() => setShowFind((value) => !value)}
            aria-pressed={showFind}
          >
            <Search aria-hidden />
            Find
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 gap-1 px-1.5 text-[11px] [&_svg]:size-3"
            onClick={handleCopy}
          >
            {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
            {copied ? "Copied" : "Copy"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 gap-1 px-1.5 text-[11px] [&_svg]:size-3"
            onClick={handleDownload}
          >
            <Download aria-hidden />
            Download
          </Button>
        </div>
      </div>

      {showFind ? (
        <div className="flex items-center gap-1.5">
          <Input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActiveMatch(0);
            }}
            placeholder="Find in content…"
            className="h-7 text-xs"
            autoFocus
          />
          <span className="whitespace-nowrap text-[11px] tabular-nums text-muted-foreground">
            {query ? `${matchCount === 0 ? 0 : currentMatch + 1}/${matchCount}` : "0/0"}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="size-7 p-0 [&_svg]:size-3.5"
            disabled={matchCount === 0}
            onClick={() => stepMatch(-1)}
            aria-label="Previous match"
          >
            <ChevronUp aria-hidden />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="size-7 p-0 [&_svg]:size-3.5"
            disabled={matchCount === 0}
            onClick={() => stepMatch(1)}
            aria-label="Next match"
          >
            <ChevronDown aria-hidden />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="size-7 p-0 [&_svg]:size-3.5"
            onClick={() => {
              setShowFind(false);
              setQuery("");
            }}
            aria-label="Close find"
          >
            <X aria-hidden />
          </Button>
        </div>
      ) : null}

      <pre
        className={cn(
          "overflow-auto whitespace-pre-wrap break-all rounded bg-muted/40 p-2 text-[11px] font-mono",
          height === "full" ? "max-h-[calc(85vh-13rem)]" : "max-h-60",
        )}
      >
        {segments.map((segment, index) => {
          if (segment.matchIndex == null) {
            return <Fragment key={index}>{segment.text}</Fragment>;
          }
          const isActive = segment.matchIndex === currentMatch;
          return (
            <mark
              key={index}
              ref={
                isActive
                  ? (node) => {
                      activeMarkRef.current = node;
                    }
                  : undefined
              }
              className={cn(
                "rounded-sm",
                isActive
                  ? "bg-warning text-warning-foreground"
                  : "bg-warning/40 text-foreground",
              )}
            >
              {segment.text}
            </mark>
          );
        })}
      </pre>
    </div>
  );
}
