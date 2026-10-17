"use client";

import { Database, KeyRound, Shield, Wrench } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";
import type { LucideIcon } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";
import type { AuthUser } from "@/lib/auth";

interface ToolLink {
  title: string;
  description: string;
  href: string;
  icon: LucideIcon;
  canShow: (user: AuthUser | null) => boolean;
}

const MIGRATION_TOOL: ToolLink = {
  title: "Database Migration",
  description: "Compare the live schema against the models and apply changes, or re-seed RBAC.",
  href: "/tools/database-migration",
  icon: Database,
  canShow: (user) =>
    hasPermission(user, "system.database", "read") ||
    hasPermission(user, "system.database", "write"),
};

const CERTIFICATE_TOOL: ToolLink = {
  title: "Add Certificate",
  description: "Upload and install CA certificates into the system trust store.",
  href: "/tools/add-certificate",
  icon: KeyRound,
  canShow: (user) =>
    hasPermission(user, "system.certificates", "read") ||
    hasPermission(user, "system.certificates", "write"),
};

const OIDC_TOOL: ToolLink = {
  title: "OIDC Test Dashboard",
  description: "Debug OIDC provider configuration and test SSO login flows.",
  href: "/tools/oidc-test",
  icon: Shield,
  canShow: (user) => hasPermission(user, "system.oidc", "read"),
};

interface ToolsPageProps {
  oidcTestEnabled?: boolean;
}

export function ToolsPage({ oidcTestEnabled = false }: ToolsPageProps) {
  const user = useAuthStore((state) => state.user);

  const toolLinks = useMemo(() => {
    const links: ToolLink[] = [];
    if (MIGRATION_TOOL.canShow(user)) {
      links.push(MIGRATION_TOOL);
    }
    if (CERTIFICATE_TOOL.canShow(user)) {
      links.push(CERTIFICATE_TOOL);
    }
    if (oidcTestEnabled && OIDC_TOOL.canShow(user)) {
      links.push(OIDC_TOOL);
    }
    return links;
  }, [oidcTestEnabled, user]);

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
        {toolLinks.map((tool) => (
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

      <Card className="border-warning-border bg-warning">
        <CardContent className="pt-6 text-sm text-warning-foreground">
          These tools are intended for debugging and administrative purposes. They are not shown
          in the main navigation and require the relevant permissions to use.
        </CardContent>
      </Card>
    </div>
  );
}
