"use client";

import { CircleHelp, Search } from "lucide-react";
import { useCallback, useState } from "react";

import { useAssistantSessionStore } from "@/components/features/ai-assistant/store/assistant-session-store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import { filterHelpSections } from "../utils/help-search";
import { HelpDetail } from "./help-detail";
import { HelpTree, helpToolKey } from "./help-tree";

const FIRST_SECTION = HELP_SECTIONS[0];
const FIRST_KEY = helpToolKey(FIRST_SECTION.id, FIRST_SECTION.tools[0].name);

function findSelected(key: string) {
  for (const section of HELP_SECTIONS) {
    for (const tool of section.tools) {
      if (helpToolKey(section.id, tool.name) === key) return { section, tool };
    }
  }
  return { section: FIRST_SECTION, tool: FIRST_SECTION.tools[0] };
}

/**
 * The help button and its page: a tree of tool groups on the left, the help text of the chosen tool on the right. Choosing a
 * question closes the window and puts it into the message box; the user sends it, nothing is
 * sent here.
 */
export function HelpDialog() {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(
    () => new Set([FIRST_SECTION.id]),
  );
  const [query, setQuery] = useState("");
  const [selectedKey, setSelectedKey] = useState(FIRST_KEY);

  const toggle = useCallback((sectionId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (!next.delete(sectionId)) next.add(sectionId);
      return next;
    });
  }, []);

  const select = useCallback((sectionId: string, toolName: string) => {
    setSelectedKey(helpToolKey(sectionId, toolName));
  }, []);

  const searching = query.trim() !== "";
  const visible = filterHelpSections(HELP_SECTIONS, query);
  const visibleKeys = visible.flatMap((section) =>
    section.tools.map((tool) => helpToolKey(section.id, tool.name)),
  );
  // A selection hidden by the search gives way to the first hit.
  const activeKey = visibleKeys.includes(selectedKey)
    ? selectedKey
    : (visibleKeys[0] ?? selectedKey);
  const selected = findSelected(activeKey);
  // While searching every group with a hit is open, so the hits are visible.
  const shownExpanded = searching
    ? new Set(visible.map((section) => section.id))
    : expanded;

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
      <DialogContent className="flex h-[85vh] max-w-5xl flex-col">
        <DialogHeader>
          <DialogTitle>What can I ask?</DialogTitle>
          <DialogDescription>
            Pick a tool on the left to see what it does. Click a question to put
            it into the message box.
          </DialogDescription>
        </DialogHeader>
        <div className="grid min-h-0 flex-1 grid-cols-[18rem_1fr] gap-4">
          <div className="flex min-h-0 flex-col gap-2 border-r pr-2">
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-2 top-2.5 size-4 text-muted-foreground"
                aria-hidden
              />
              <Input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Find in help…"
                aria-label="Find in help"
                className="pl-8"
              />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {visible.length === 0 ? (
                <p className="p-2 text-sm text-muted-foreground">
                  Nothing found for “{query.trim()}”.
                </p>
              ) : null}
              <HelpTree
                sections={visible}
                expanded={shownExpanded}
                selectedKey={activeKey}
                onToggle={toggle}
                onSelect={select}
              />
            </div>
          </div>
          <div className="min-h-0 overflow-y-auto pr-1">
            {visible.length > 0 ? (
              <HelpDetail
                section={selected.section}
                tool={selected.tool}
                onPick={pick}
              />
            ) : null}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
