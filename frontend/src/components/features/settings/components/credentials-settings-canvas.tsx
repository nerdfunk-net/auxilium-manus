"use client";

import { useCallback, useMemo, useState } from "react";
import { KeyRound, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";

import { CredentialsTable } from "../credentials/components/credentials-table";
import { CredentialFormDialog } from "../credentials/dialogs/credential-form-dialog";
import { DeleteCredentialDialog } from "../credentials/dialogs/delete-credential-dialog";
import { useCredentialMutations } from "../credentials/hooks/use-credential-mutations";
import { useCredentialsQuery } from "../credentials/hooks/use-credentials-query";
import type { Credential } from "../credentials/types";

type DialogState =
  | { type: "closed" }
  | { type: "create" }
  | { type: "edit"; credential: Credential }
  | { type: "delete"; credential: Credential };

export function CredentialsSettingsCanvas() {
  const [dialog, setDialog] = useState<DialogState>({ type: "closed" });
  const [includeExpired, setIncludeExpired] = useState(false);

  const { data, isLoading } = useCredentialsQuery({ includeExpired });
  const { createCredential, updateCredential, deleteCredential } =
    useCredentialMutations();

  const credentials = useMemo(
    () => data?.credentials ?? [],
    [data?.credentials],
  );

  const handleCreate = useCallback(
    (values: {
      name: string;
      username: string;
      password?: string;
      valid_until?: string;
    }) => {
      createCredential.mutate(
        {
          name: values.name.trim(),
          username: values.username.trim(),
          type: "ssh",
          password: values.password,
          valid_until: values.valid_until || undefined,
        },
        { onSuccess: () => setDialog({ type: "closed" }) },
      );
    },
    [createCredential],
  );

  const handleUpdate = useCallback(
    (
      credential: Credential,
      values: {
        name: string;
        username: string;
        password?: string;
        valid_until?: string;
      },
    ) => {
      const payload: {
        name: string;
        username: string;
        password?: string;
        valid_until?: string;
      } = {
        name: values.name.trim(),
        username: values.username.trim(),
        valid_until: values.valid_until || undefined,
      };
      if (values.password?.trim()) {
        payload.password = values.password;
      }

      updateCredential.mutate(
        { id: credential.id, data: payload },
        { onSuccess: () => setDialog({ type: "closed" }) },
      );
    },
    [updateCredential],
  );

  const confirmDelete = useCallback(() => {
    if (dialog.type !== "delete") {
      return;
    }
    deleteCredential.mutate(dialog.credential.id, {
      onSuccess: () => setDialog({ type: "closed" }),
    });
  }, [deleteCredential, dialog]);

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto bg-slate-50 p-8">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <KeyRound className="size-5" />
            </div>
            <div>
              <h1 className="text-lg font-semibold">Credential vault</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Configure SSH login credentials for network device access.
                Passwords are encrypted in the database.
              </p>
            </div>
          </div>
          <Button
            type="button"
            onClick={() => setDialog({ type: "create" })}
          >
            <Plus className="size-4" />
            Add SSH login
          </Button>
        </div>

        <div className="flex items-center gap-3 rounded-lg border bg-card px-4 py-3">
          <Switch
            checked={includeExpired}
            id="include-expired-credentials"
            onCheckedChange={setIncludeExpired}
          />
          <label
            className="text-sm text-muted-foreground"
            htmlFor="include-expired-credentials"
          >
            Show expired credentials
          </label>
        </div>

        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading credentials…</p>
        ) : (
          <CredentialsTable
            credentials={credentials}
            onDelete={(credential) => setDialog({ type: "delete", credential })}
            onEdit={(credential) => setDialog({ type: "edit", credential })}
          />
        )}
      </div>

      <CredentialFormDialog
        open={dialog.type === "create"}
        mode="create"
        isSaving={createCredential.isPending}
        onClose={() => setDialog({ type: "closed" })}
        onSubmit={handleCreate}
      />

      <CredentialFormDialog
        open={dialog.type === "edit"}
        mode="edit"
        credential={dialog.type === "edit" ? dialog.credential : undefined}
        isSaving={updateCredential.isPending}
        onClose={() => setDialog({ type: "closed" })}
        onSubmit={(values) => {
          if (dialog.type === "edit") {
            handleUpdate(dialog.credential, values);
          }
        }}
      />

      <DeleteCredentialDialog
        open={dialog.type === "delete"}
        credentialName={
          dialog.type === "delete" ? dialog.credential.name : undefined
        }
        isDeleting={deleteCredential.isPending}
        onClose={() => setDialog({ type: "closed" })}
        onConfirm={confirmDelete}
      />
    </div>
  );
}
