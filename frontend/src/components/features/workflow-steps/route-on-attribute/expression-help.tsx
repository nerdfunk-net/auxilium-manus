"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";
import { EXPRESSION_EXAMPLES } from "./route-config";

const FUNCTION_GROUPS = [
  {
    group: "State",
    functions: "exists()  isEmpty()  isNull()  isAbsent()",
    example: "{:isEmpty()}",
    note: "first in the chain only",
  },
  {
    group: "List size",
    functions: "count()",
    example: "{parsed.k.serial:count():gt(2)}",
    note: "list length, dict keys; 0 if empty or absent; first only",
  },
  {
    group: "Compare",
    functions: "equals  equalsIgnoreCase  startsWith  endsWith  contains  in(a, b, …)",
    example: "{custom.site:in('ams', 'fra')}",
    note: "",
  },
  {
    group: "Numbers",
    functions: "gt  ge  lt  le  toNumber()  plus  minus  multiply  mod",
    example: "{custom.value:plus(1):le(10)}",
    note: "a non-numeric value is simply false",
  },
  {
    group: "Text",
    functions: "toLower()  toUpper()  trim()  length()  substring(from, to)  replace(a, b)  append  prepend",
    example: "{device.name:toLower():startsWith('lab')}",
    note: "",
  },
  {
    group: "Logic",
    functions: "not()  and({…})  or({…})",
    example: "{:exists():and({custom.x:gt(1)})}",
    note: "the argument is another {…} expression",
  },
  {
    group: "Regex",
    functions: "matches('re')  find('re')",
    example: "{:matches('sw\\d+')}",
    note: "whole value / anywhere in it",
  },
] as const;

/** Full reference for the route expression language (Routes tab dialog and the Help tab). */
export function ExpressionLanguageHelp() {
  return (
    <div className="space-y-5">
      <HelpSection title="Plain values and expressions">
        <p>
          The <span className="font-medium text-foreground">Expression</span> column
          takes values separated by commas. A device takes the route when{" "}
          <span className="font-medium text-foreground">any</span> value matches, and
          routes are checked top to bottom: the first match wins.
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            A plain value such as <HelpCode>cisco_ios</HelpCode> must equal the
            step&apos;s <HelpCode>attribute_path</HelpCode> (case is ignored unless{" "}
            <HelpCode>case_sensitive</HelpCode> is on).
          </li>
          <li>
            A value in braces is an expression, a yes/no question about the device.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Writing an expression">
        <HelpExample>
          {"{ custom.value : gt(10) }"}
          <br />
          {"  └─ key       └─ function(s), left to right"}
        </HelpExample>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">key</span> is any attribute
            path, like <HelpCode>device.name</HelpCode> or{" "}
            <HelpCode>parsed.k.serial</HelpCode>. Leave it empty —{" "}
            <HelpCode>{"{:gt(10)}"}</HelpCode> — to use the step&apos;s{" "}
            <HelpCode>attribute_path</HelpCode>.
          </li>
          <li>
            Functions are chained with <HelpCode>:</HelpCode> and work on the result of
            the one before. The <span className="font-medium text-foreground">last</span>{" "}
            one must answer true or false.
          </li>
          <li>
            Arguments are <HelpCode>&apos;quoted text&apos;</HelpCode>, numbers,{" "}
            <HelpCode>true</HelpCode>/<HelpCode>false</HelpCode>, or another attribute in
            braces, e.g. <HelpCode>{"{custom.a:equals({custom.b})}"}</HelpCode>.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Functions">
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="h-7 px-2 text-[11px]">Group</TableHead>
                <TableHead className="h-7 px-2 text-[11px]">Functions</TableHead>
                <TableHead className="h-7 px-2 text-[11px]">Example</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {FUNCTION_GROUPS.map((row) => (
                <TableRow key={row.group}>
                  <TableCell className="px-2 py-1.5 align-top text-[11px] font-medium text-foreground">
                    {row.group}
                  </TableCell>
                  <TableCell className="whitespace-normal px-2 py-1.5 align-top font-mono text-[11px]">
                    {row.functions}
                    {row.note ? (
                      <span className="block font-sans text-[10px] text-muted-foreground">
                        {row.note}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell className="whitespace-normal break-all px-2 py-1.5 align-top font-mono text-[11px]">
                    {row.example}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </HelpSection>

      <HelpSection title="Examples">
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="h-7 px-2 text-[11px]">Expression</TableHead>
                <TableHead className="h-7 px-2 text-[11px]">Routes a device when…</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {EXPRESSION_EXAMPLES.map((example) => (
                <TableRow key={example.value}>
                  <TableCell className="whitespace-normal break-all px-2 py-1.5 align-top font-mono text-[11px]">
                    {example.value}
                  </TableCell>
                  <TableCell className="whitespace-normal px-2 py-1.5 align-top text-[11px]">
                    {example.meaning}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </HelpSection>

      <HelpSection title="Good to know">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            A missing or non-numeric value makes a comparison false; it never fails the
            device. <HelpCode>count()</HelpCode> of a missing path is 0.
          </li>
          <li>
            In quoted text <HelpCode>{"\\\\"}</HelpCode> is one backslash and{" "}
            <HelpCode>{"\\'"}</HelpCode> a quote; any other backslash stays, so{" "}
            <HelpCode>{"'sw\\d+'"}</HelpCode> is the regular expression{" "}
            <HelpCode>sw\d+</HelpCode>.
          </li>
          <li>
            A regular expression that is invalid or takes too long fails only the devices
            it is checked for (<HelpCode>failure</HelpCode> outcome); the rest still route.
          </li>
          <li>
            A mistake in an expression is reported when the workflow is saved.
          </li>
        </ul>
        <HelpWarning title="The old shortcuts are gone">
          <p>
            <HelpCode>{"{exists}"}</HelpCode>, <HelpCode>{"{empty}"}</HelpCode>,{" "}
            <HelpCode>{"{null}"}</HelpCode> and <HelpCode>{"{absent}"}</HelpCode> are now{" "}
            <HelpCode>{"{:exists()}"}</HelpCode>, <HelpCode>{"{:isEmpty()}"}</HelpCode>,{" "}
            <HelpCode>{"{:isNull()}"}</HelpCode> and <HelpCode>{"{:isAbsent()}"}</HelpCode>.
          </p>
        </HelpWarning>
      </HelpSection>
    </div>
  );
}

interface ExpressionHelpDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ExpressionHelpDialog({ open, onOpenChange }: ExpressionHelpDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] max-w-2xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="shrink-0 border-b px-6 py-4">
          <DialogTitle className="text-base">Route expressions</DialogTitle>
          <DialogDescription className="text-xs">
            How to write the Expression column, and what you can ask.
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          <ExpressionLanguageHelp />
        </div>
      </DialogContent>
    </Dialog>
  );
}
