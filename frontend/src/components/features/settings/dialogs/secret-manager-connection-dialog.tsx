"use client";

import { useCallback, useEffect } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useSecretManagerConnectionsMutations } from "@/hooks/queries/use-secret-manager-connections-mutations";
import type {
  SecretManagerBackend,
  SecretManagerConnectionRecord,
} from "@/hooks/queries/use-secret-manager-connections-query";

import { useCredentialsQuery } from "../credentials/hooks/use-credentials-query";

const connectionSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  backend: z.enum(["openbao", "infisical"]),
  credentialName: z.string().optional(),
  verifySsl: z.boolean(),
  isActive: z.boolean(),
  description: z.string().max(1000).optional(),
  // OpenBao
  addr: z.string().optional(),
  mount: z.string().optional(),
  namespace: z.string().optional(),
  // Infisical
  siteUrl: z.string().optional(),
  projectId: z.string().optional(),
  environment: z.string().optional(),
});

type ConnectionFormValues = z.infer<typeof connectionSchema>;

const EMPTY_DEFAULTS: ConnectionFormValues = {
  name: "",
  backend: "openbao",
  credentialName: "",
  verifySsl: true,
  isActive: true,
  description: "",
  addr: "",
  mount: "",
  namespace: "",
  siteUrl: "https://app.infisical.com",
  projectId: "",
  environment: "",
};

interface SecretManagerConnectionDialogProps {
  open: boolean;
  connection: SecretManagerConnectionRecord | null;
  onClose: () => void;
}

export function SecretManagerConnectionDialog({
  open,
  connection,
  onClose,
}: SecretManagerConnectionDialogProps) {
  const { createConnection, updateConnection } = useSecretManagerConnectionsMutations();
  const { data: credentialsData } = useCredentialsQuery();
  const isEdit = connection != null;

  const {
    register,
    control,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<ConnectionFormValues>({
    resolver: zodResolver(connectionSchema),
    defaultValues: EMPTY_DEFAULTS,
  });

  const backend = useWatch({ control, name: "backend" });

  useEffect(() => {
    if (!open) return;
    const config = connection?.backend_config ?? {};
    reset({
      name: connection?.name ?? "",
      backend: connection?.backend ?? "openbao",
      credentialName: connection?.credential_name ?? "",
      verifySsl: connection?.verify_ssl ?? true,
      isActive: connection?.is_active ?? true,
      description: connection?.description ?? "",
      addr: typeof config.addr === "string" ? config.addr : "",
      mount: typeof config.mount === "string" ? config.mount : "",
      namespace: typeof config.namespace === "string" ? config.namespace : "",
      siteUrl:
        typeof config.site_url === "string" ? config.site_url : "https://app.infisical.com",
      projectId: typeof config.project_id === "string" ? config.project_id : "",
      environment: typeof config.environment === "string" ? config.environment : "",
    });
  }, [open, connection, reset]);

  const genericCredentials = (credentialsData?.credentials ?? []).filter(
    (cred) => cred.type === "generic",
  );
  const hasPrivateOnly =
    genericCredentials.length > 0 && genericCredentials.every((cred) => cred.visibility !== "global");

  const onSubmit = useCallback(
    (values: ConnectionFormValues) => {
      const backendConfig: Record<string, unknown> =
        values.backend === "openbao"
          ? {
              addr: values.addr?.trim() ?? "",
              mount: values.mount?.trim() ?? "",
              namespace: values.namespace?.trim() || undefined,
            }
          : {
              site_url: values.siteUrl?.trim() ?? "",
              project_id: values.projectId?.trim() ?? "",
              environment: values.environment?.trim() ?? "",
            };

      const payload = {
        name: values.name.trim(),
        backend: values.backend as SecretManagerBackend,
        credential_name: values.credentialName || null,
        verify_ssl: values.verifySsl,
        is_active: values.isActive,
        description: values.description?.trim() || null,
        backend_config: backendConfig,
      };

      if (isEdit && connection) {
        updateConnection.mutate({ id: connection.id, data: payload }, { onSuccess: onClose });
      } else {
        createConnection.mutate(payload, { onSuccess: onClose });
      }
    },
    [connection, createConnection, isEdit, onClose, updateConnection],
  );

  const isSaving = createConnection.isPending || updateConnection.isPending;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit Secret Manager connection" : "Add Secret Manager connection"}</DialogTitle>
          <DialogDescription>
            Referenced by ID from the secret-get / secret-set / secret-generate workflow steps.
          </DialogDescription>
        </DialogHeader>

        <form className="flex min-h-0 flex-1 flex-col" onSubmit={handleSubmit(onSubmit)}>
          <div className="flex-1 space-y-4 overflow-y-auto px-1 py-1">
            <div className="space-y-2">
              <Label htmlFor="sm-conn-name">Name</Label>
              <Input id="sm-conn-name" placeholder="network-secrets" {...register("name")} />
              {errors.name ? (
                <p className="text-xs text-destructive">{errors.name.message}</p>
              ) : null}
            </div>

            <div className="space-y-2">
              <Label htmlFor="sm-conn-backend">Backend</Label>
              <Controller
                control={control}
                name="backend"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="sm-conn-backend">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="openbao">OpenBao</SelectItem>
                      <SelectItem value="infisical">Infisical</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              />
            </div>

            {backend === "openbao" ? (
              <>
                <div className="space-y-2">
                  <Label htmlFor="sm-conn-addr">OpenBao address</Label>
                  <Input
                    id="sm-conn-addr"
                    placeholder="https://vault.internal:8200"
                    {...register("addr")}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="sm-conn-mount">KV v2 mount</Label>
                  <Input id="sm-conn-mount" placeholder="manus-network" {...register("mount")} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="sm-conn-namespace">Namespace (optional)</Label>
                  <Input id="sm-conn-namespace" placeholder="" {...register("namespace")} />
                </div>
              </>
            ) : (
              <>
                <div className="space-y-2">
                  <Label htmlFor="sm-conn-site-url">Infisical site URL</Label>
                  <Input
                    id="sm-conn-site-url"
                    placeholder="https://app.infisical.com"
                    {...register("siteUrl")}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="sm-conn-project-id">Project ID</Label>
                  <Input id="sm-conn-project-id" placeholder="" {...register("projectId")} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="sm-conn-environment">Environment</Label>
                  <Input id="sm-conn-environment" placeholder="prod" {...register("environment")} />
                </div>
              </>
            )}

            <div className="space-y-2">
              <Label htmlFor="sm-conn-credential">Connection credential</Label>
              <Controller
                control={control}
                name="credentialName"
                render={({ field }) => (
                  <Select value={field.value || ""} onValueChange={field.onChange}>
                    <SelectTrigger id="sm-conn-credential">
                      <SelectValue placeholder="Select a credential" />
                    </SelectTrigger>
                    <SelectContent>
                      {genericCredentials.length === 0 ? (
                        <div className="px-2 py-1.5 text-xs text-muted-foreground">
                          No generic credentials found. Add one in Settings → Credentials, with
                          username = role_id/client_id and password = secret_id/client_secret.
                        </div>
                      ) : (
                        genericCredentials.map((cred) => (
                          <SelectItem
                            key={cred.id}
                            value={cred.name}
                            disabled={cred.visibility !== "global"}
                          >
                            {cred.name}
                            {cred.visibility !== "global" ? " — private, must be global" : ""}
                          </SelectItem>
                        ))
                      )}
                    </SelectContent>
                  </Select>
                )}
              />
              <p className="text-xs text-muted-foreground">
                A <strong>generic</strong> credential holding this connection&apos;s own auth
                material: username = OpenBao AppRole role_id / Infisical client_id, password =
                secret_id / client_secret. Must be <strong>global</strong> — this connection is
                used by background workflow runs, not as the signed-in user.
                {hasPrivateOnly
                  ? " Edit the credential in Settings → Credentials and turn on “Make this credential global”."
                  : ""}
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="sm-conn-description">Description (optional)</Label>
              <Input id="sm-conn-description" placeholder="Optional" {...register("description")} />
            </div>

            <div className="flex items-center justify-between rounded-lg border px-4 py-3">
              <div>
                <Label htmlFor="sm-conn-verify-ssl" className="mb-0">
                  Verify TLS certificate
                </Label>
                <p className="text-xs text-muted-foreground">
                  Disable only for a self-signed dev/test instance.
                </p>
              </div>
              <Controller
                control={control}
                name="verifySsl"
                render={({ field }) => (
                  <Switch
                    id="sm-conn-verify-ssl"
                    checked={field.value}
                    onCheckedChange={field.onChange}
                  />
                )}
              />
            </div>

            <div className="flex items-center justify-between rounded-lg border px-4 py-3">
              <div>
                <Label htmlFor="sm-conn-active" className="mb-0">
                  Active
                </Label>
                <p className="text-xs text-muted-foreground">
                  Inactive connections are rejected by secret-get/set/generate steps.
                </p>
              </div>
              <Controller
                control={control}
                name="isActive"
                render={({ field }) => (
                  <Switch
                    id="sm-conn-active"
                    checked={field.value}
                    onCheckedChange={field.onChange}
                  />
                )}
              />
            </div>
          </div>

          <DialogFooter className="shrink-0 pt-4">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button disabled={isSaving} type="submit">
              {isSaving ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
