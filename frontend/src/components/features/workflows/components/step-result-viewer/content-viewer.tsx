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
import {
  memo,
  startTransition,
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type RefObject,
} from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { findMatches, wrapMatchIndex } from "./content-find";

interface ContentViewerProps {
  content: string;
  label: string;
  sizeBytes?: number | null;
  /** Filename stem for downloads (extension is appended). */
  downloadName?: string;
  /** "sm" keeps the inline preview height; "full" expands it for the detail dialog. */
  height?: "sm" | "full";
}

function isFindShortcut(event: KeyboardEvent | ReactKeyboardEvent): boolean {
  return (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "f";
}

function isFindNextShortcut(event: KeyboardEvent | ReactKeyboardEvent): boolean {
  return (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "g";
}

interface FindBarProps {
  label: string;
  matchCount: number;
  currentMatch: number;
  inputRef: RefObject<HTMLInputElement | null>;
  onQueryChange: (query: string) => void;
  onStep: (delta: number) => void;
  onClose: () => void;
}

/**
 * Uncontrolled search field so typing is handled by the browser, not by
 * re-rendering a huge result document (Extract Facts, configs, …) on every
 * keystroke. The parent learns the query through a transition.
 */
const FindBar = memo(function FindBar({
  label,
  matchCount,
  currentMatch,
  inputRef,
  onQueryChange,
  onStep,
  onClose,
}: FindBarProps) {
  const handleChange = (value: string) => {
    startTransition(() => {
      onQueryChange(value);
    });
  };

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      onStep(event.shiftKey ? -1 : 1);
    }
  };

  const summary = matchCount === 0 ? "0/0" : `${currentMatch + 1}/${matchCount}`;

  return (
    <div className="flex items-center gap-1.5" role="search" aria-label={`${label} find`}>
      <Input
        ref={inputRef}
        type="search"
        defaultValue=""
        onChange={(event) => handleChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Find in content…"
        className="h-7 appearance-none text-xs [&::-webkit-search-cancel-button]:appearance-none [&::-webkit-search-decoration]:appearance-none"
        autoFocus
        aria-label={`Find in ${label}`}
        autoComplete="off"
        spellCheck={false}
      />
      <span
        className="whitespace-nowrap text-[11px] tabular-nums text-muted-foreground"
        aria-live="polite"
      >
        {summary}
      </span>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="size-7 p-0 [&_svg]:size-3.5"
        disabled={matchCount === 0}
        onClick={() => onStep(-1)}
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
        onClick={() => onStep(1)}
        aria-label="Next match"
      >
        <ChevronDown aria-hidden />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="size-7 p-0 [&_svg]:size-3.5"
        onClick={onClose}
        aria-label="Close find"
      >
        <X aria-hidden />
      </Button>
    </div>
  );
});

const HighlightedContent = memo(function HighlightedContent({
  content,
  query,
  matchStart,
  matchLength,
  markRef,
}: {
  content: string;
  query: string;
  matchStart: number | null;
  matchLength: number;
  markRef: RefObject<HTMLElement | null>;
}) {
  if (matchStart == null || !query || matchLength === 0) {
    return content;
  }

  const matchEnd = matchStart + matchLength;
  return (
    <>
      {content.slice(0, matchStart)}
      <mark
        ref={(node) => {
          markRef.current = node;
        }}
        className="rounded-sm bg-warning text-warning-foreground"
      >
        {content.slice(matchStart, matchEnd)}
      </mark>
      {content.slice(matchEnd)}
    </>
  );
});

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
  const deferredQuery = useDeferredValue(query);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const markRef = useRef<HTMLElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const matchCountRef = useRef(0);

  const matches = useMemo(
    () => findMatches(content, deferredQuery),
    [content, deferredQuery],
  );
  const matchCount = matches.length;
  const currentMatch = wrapMatchIndex(activeMatch, matchCount);
  const current = matchCount === 0 ? null : (matches[currentMatch] ?? null);

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

  const openFind = useCallback(() => {
    setShowFind(true);
    window.requestAnimationFrame(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    });
  }, []);

  const closeFind = useCallback(() => {
    setShowFind(false);
    setQuery("");
    setActiveMatch(0);
  }, []);

  const handleQueryChange = useCallback((next: string) => {
    setQuery(next);
    setActiveMatch(0);
  }, []);

  const stepMatch = useCallback((delta: number) => {
    if (matchCountRef.current === 0) {
      return;
    }
    setActiveMatch((value) => value + delta);
  }, []);

  useEffect(() => {
    matchCountRef.current = matchCount;
  }, [matchCount]);

  useEffect(() => {
    if (current == null) {
      return;
    }
    const reduceMotion =
      typeof window.matchMedia === "function"
        ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
        : false;
    markRef.current?.scrollIntoView?.({
      block: "center",
      behavior: reduceMotion ? "auto" : "smooth",
    });
  }, [current, currentMatch]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const root = containerRef.current;
      if (!root) {
        return;
      }
      const target = event.target;
      const inside =
        target instanceof Node && (root.contains(target) || target === root);
      if (!inside) {
        return;
      }
      if (isFindShortcut(event)) {
        event.preventDefault();
        event.stopPropagation();
        openFind();
        return;
      }
      if (!showFind) {
        return;
      }
      if (isFindNextShortcut(event)) {
        event.preventDefault();
        event.stopPropagation();
        stepMatch(event.shiftKey ? -1 : 1);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        closeFind();
      }
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [openFind, closeFind, showFind, stepMatch]);

  return (
    <div ref={containerRef} className="space-y-1">
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
            onClick={() => (showFind ? closeFind() : openFind())}
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
        <FindBar
          label={label}
          matchCount={deferredQuery ? matchCount : 0}
          currentMatch={currentMatch}
          inputRef={inputRef}
          onQueryChange={handleQueryChange}
          onStep={stepMatch}
          onClose={closeFind}
        />
      ) : null}

      <pre
        tabIndex={-1}
        className={cn(
          "overflow-auto whitespace-pre-wrap break-all rounded bg-muted/40 p-2 text-[11px] font-mono focus-visible:outline-none",
          height === "full"
            ? "max-h-[calc(96vh-14rem)] min-h-32 resize-y"
            : "max-h-60",
        )}
      >
        <HighlightedContent
          content={content}
          query={deferredQuery}
          matchStart={current?.start ?? null}
          matchLength={current?.length ?? 0}
          markRef={markRef}
        />
      </pre>
    </div>
  );
}
