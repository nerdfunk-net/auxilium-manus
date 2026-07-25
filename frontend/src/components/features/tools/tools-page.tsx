"use client";

import { Database, KeyRound, Wrench } from "lucide-react";
import Link from "next/link";
import type { LucideIcon } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ToolLink {
  title: string;
  description: string;
  href: string;
  icon: LucideIcon;
}

const TOOL_LINKS: ToolLink[] = [
  {
    title: "Database Migration",
    description: "Compare the live schema against the models and apply changes, or re-seed RBAC.",
    href: "/tools/database-migration",
    icon: Database,
  },
  {
    title: "Add Certificate",
    description: "Upload and install CA certificates into the system trust store.",
    href: "/tools/add-certificate",
    icon: KeyRound,
  },
];

export function ToolsPage() {
  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 p-8">
      <div className="flex items-center gap-3">
        <div className="flex size-10 items-center justify-center rounded-lg bg-muted">
          <Wrench className="size-5 text-muted-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold">Developer Tools</h1>
          <p className="text-sm text-muted-foreground">
            Debugging and administrative tools for Auxilium Manus.
          </p>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {TOOL_LINKS.map((tool) => (
          <Link key={tool.href} href={tool.href}>
            <Card className="h-full transition-colors hover:border-primary/50">
              <CardHeader className="flex flex-row items-center gap-3 pb-2">
                <tool.icon className="size-5 text-muted-foreground" />
                <CardTitle className="text-base">{tool.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">{tool.description}</p>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      <Card className="border-amber-500/40 bg-amber-50 dark:bg-amber-950/30">
        <CardContent className="pt-6 text-sm text-amber-800 dark:text-amber-300">
          These tools are intended for debugging and administrative purposes. They are not shown
          in the main navigation and require the relevant permissions to use.
        </CardContent>
      </Card>
    </div>
  );
}
