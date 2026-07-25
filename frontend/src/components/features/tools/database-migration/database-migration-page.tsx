"use client";

import { ArrowLeft, Database } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useRbacSeedMutation, type RbacSeedResult } from "@/hooks/queries/use-rbac-seed-mutation";
import { useSchemaMutations, type SchemaMigrationResult } from "@/hooks/queries/use-schema-mutations";
import { useSchemaStatusQuery } from "@/hooks/queries/use-schema-query";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";

import { RbacSeedCard } from "./components/rbac-seed-card";
import { SchemaStatusCard } from "./components/schema-status-card";
import { ForceApplyDialog } from "./dialogs/force-apply-dialog";
import { RbacSeedPromptDialog } from "./dialogs/rbac-seed-prompt-dialog";
import { RbacSeedResultDialog } from "./dialogs/rbac-seed-result-dialog";

export function DatabaseMigrationPage() {
  const user = useAuthStore((state) => state.user);
  const canWriteSchema = hasPermission(user, "system.database", "write");
  const canWriteRbac = hasPermission(user, "system.rbac", "write");

  const { data: status, isLoading, isFetching, refetch } = useSchemaStatusQuery();
  const { migrateSchema } = useSchemaMutations();
  const rbacSeed = useRbacSeedMutation();

  const [migrationResult, setMigrationResult] = useState<SchemaMigrationResult | null>(null);
  const [forceDialogOpen, setForceDialogOpen] = useState(false);
  const [removeExisting, setRemoveExisting] = useState(false);
  const [seedPromptOpen, setSeedPromptOpen] = useState(false);
  const [seedResult, setSeedResult] = useState<RbacSeedResult | null>(null);
  const [seedResultOpen, setSeedResultOpen] = useState(false);

  const riskyDiffs = status?.column_diffs.filter((d) => !d.safe) ?? [];

  const handleSync = async () => {
    const result = await migrateSchema.mutateAsync(false);
    setMigrationResult(result);
    if (result.success) {
      setSeedPromptOpen(true);
    }
  };

  const handleForceApply = async () => {
    const result = await migrateSchema.mutateAsync(true);
    setMigrationResult(result);
    setForceDialogOpen(false);
    if (result.success) {
      setSeedPromptOpen(true);
    }
  };

  const runSeed = async (remove: boolean) => {
    const result = await rbacSeed.mutateAsync(remove);
    setSeedResult(result);
    setSeedPromptOpen(false);
    setSeedResultOpen(true);
  };

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6 p-8">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" asChild>
          <Link href="/tools">
            <ArrowLeft className="size-4" />
          </Link>
        </Button>
        <div className="flex size-10 items-center justify-center rounded-lg bg-muted">
          <Database className="size-5 text-muted-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold">Database Migration</h1>
          <p className="text-sm text-muted-foreground">
            Compare the live schema against the SQLAlchemy models.
          </p>
        </div>
      </div>

      <SchemaStatusCard
        status={status}
        isLoading={isLoading}
        isFetching={isFetching}
        onRefresh={() => refetch()}
        migrationResult={migrationResult}
        isMigrating={migrateSchema.isPending}
        canWrite={canWriteSchema}
        onSync={handleSync}
        onForceApplyClick={() => setForceDialogOpen(true)}
      />

      <RbacSeedCard
        removeExisting={removeExisting}
        onRemoveExistingChange={setRemoveExisting}
        isSeeding={rbacSeed.isPending}
        canWrite={canWriteRbac}
        onSeed={() => runSeed(removeExisting)}
      />

      <ForceApplyDialog
        open={forceDialogOpen}
        diffs={riskyDiffs}
        isApplying={migrateSchema.isPending}
        onClose={() => setForceDialogOpen(false)}
        onConfirm={handleForceApply}
      />

      <RbacSeedPromptDialog
        open={seedPromptOpen}
        isSeeding={rbacSeed.isPending}
        onSkip={() => setSeedPromptOpen(false)}
        onSeed={() => runSeed(false)}
      />

      <RbacSeedResultDialog
        open={seedResultOpen}
        result={seedResult}
        onClose={() => setSeedResultOpen(false)}
      />
    </div>
  );
}
