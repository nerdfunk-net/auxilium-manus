"use client";

import { BookText } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAiGlossaryQuery } from "@/hooks/queries/use-ai-glossary-query";

import { AiGlossaryDialog } from "../dialogs/ai-glossary-dialog";

/** Administrator-only: the shared vocabulary of the inventory assistant. The list opens in a dialog. */
export function AiGlossaryCard() {
  const [open, setOpen] = useState(false);
  // One row is enough to learn the total; the dialog does its own paging.
  const { data } = useAiGlossaryQuery({ query: "", offset: 0, limit: 1 });
  const total = data?.total;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Inventory glossary</CardTitle>
      </CardHeader>
      <CardContent className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Teach the inventory assistant local words and acronyms
          (&quot;core&quot;, &quot;DC&quot;) by mapping them to a filter.
          {total !== undefined &&
            ` ${total} ${total === 1 ? "term" : "terms"} defined.`}
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
