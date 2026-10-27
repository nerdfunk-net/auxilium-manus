"use client";

import { BookText } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAiGlossaryQuery } from "@/hooks/queries/use-ai-glossary-query";

import { AiGlossaryDialog } from "../dialogs/ai-glossary-dialog";

const COUNT_QUERY = { query: "", offset: 0, limit: 1 };

/** Administrator-only: the shared vocabulary of the assistants. The list opens in a dialog. */
export function AiGlossaryCard() {
  const [open, setOpen] = useState(false);
  // One row is enough to learn a total; the dialog does its own paging.
  const inventory = useAiGlossaryQuery({
    kind: "inventory_filter",
    ...COUNT_QUERY,
  });
  const steps = useAiGlossaryQuery({ kind: "workflow_step", ...COUNT_QUERY });
  const counts =
    inventory.data && steps.data
      ? ` ${inventory.data.total} inventory ${inventory.data.total === 1 ? "term" : "terms"} and ${steps.data.total} step ${steps.data.total === 1 ? "alias" : "aliases"} defined.`
      : "";

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Assistant glossary</CardTitle>
      </CardHeader>
      <CardContent className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Teach the assistants local words: acronyms for inventory filters
          (&quot;core&quot;, &quot;DC&quot;) and nicknames for workflow steps.
          {counts}
        </p>
        <Button type="button" variant="outline" onClick={() => setOpen(true)}>
          <BookText className="mr-2 size-4" />
          Open glossary
        </Button>
      </CardContent>
      <AiGlossaryDialog open={open} onOpenChange={setOpen} />
    </Card>
  );
}
