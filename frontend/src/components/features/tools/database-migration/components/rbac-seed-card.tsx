"use client";

import { AlertTriangle, Loader2 } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";

interface RbacSeedCardProps {
  removeExisting: boolean;
  onRemoveExistingChange: (value: boolean) => void;
  isSeeding: boolean;
  canWrite: boolean;
  onSeed: () => void;
}

export function RbacSeedCard({
  removeExisting,
  onRemoveExistingChange,
  isSeeding,
  canWrite,
  onSeed,
}: RbacSeedCardProps) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">RBAC System Seeding</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <Alert>
          <AlertDescription>
            Creates any missing permissions and roles from the current catalog and grants them to
            the built-in <code>admin</code>/<code>viewer</code> roles. Safe to re-run at any time.
          </AlertDescription>
        </Alert>

        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <Checkbox
            checked={removeExisting}
            onCheckedChange={(checked) => onRemoveExistingChange(checked === true)}
          />
          Remove all existing RBAC data before seeding
        </label>

        {removeExisting && (
          <Alert variant="destructive">
            <AlertTriangle />
            <AlertTitle>This deletes all roles and permissions</AlertTitle>
            <AlertDescription>
              Every role, permission, and role/user assignment is deleted before the catalog is
              rebuilt from scratch. Your own admin access is restored automatically as part of the
              same operation.
            </AlertDescription>
          </Alert>
        )}

        <div className="flex justify-end">
          <Button
            variant={removeExisting ? "destructive" : "default"}
            disabled={!canWrite || isSeeding}
            onClick={onSeed}
          >
            {isSeeding && <Loader2 className="mr-2 size-4 animate-spin" />}
            {removeExisting ? "Remove & Reseed RBAC" : "Seed RBAC System"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
