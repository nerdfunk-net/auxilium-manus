"use client";

import { useCallback, useEffect, useRef } from "react";
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
import { useAgentSourcesMutations } from "@/hooks/queries/use-agent-sources-mutations";

import { AgentStatusPanel } from "../components/agent-status-panel";
import { SOURCE_ID_REGEX } from "../constants/setting-keys";
import { CredentialSelect } from "../credentials/components/credential-select";
import type {
  AgentSourceCreatePayload,
  AgentSourceUpdatePayload,
  AgentTransport,
} from "../types/settings-api";
import { AGENT_SECRET_COMMAND, buildRedisAclCommand } from "../utils/agent-redis-acl";

const BYTES_PER_KIB = 1024;

const sourceIdSchema = z
  .string()
  .min(1, "Source ID is required")
  .max(64)
  .regex(
    SOURCE_ID_REGEX,
    "Use lowercase letters, numbers, underscores, and hyphens. Must start with a letter.",
  )
  .transform((value) => value.trim().toLowerCase());

const agentSchema = z
  .object({
    sourceId: sourceIdSchema,
    transport: z.enum(["http", "redis"]),
    agentId: z
      .string()
      .min(1, "Agent ID is required")
      .max(64)
      .regex(SOURCE_ID_REGEX, "Use lowercase letters, numbers, underscores, and hyphens."),
    url: z.string(),
    credentialId: z
      .number({ error: "Select a shared-secret credential" })
      .int()
      .positive("Select a shared-secret credential"),
    maxConcurrency: z.number().int().min(1).max(64),
    maxRequestKib: z.number().int().min(1).max(8192),
    maxTimeoutSeconds: z.number().int().min(1).max(600),
  })
  .superRefine((values, ctx) => {
    if (values.transport !== "http") {
      return;
    }
    const url = values.url.trim();
    let valid = false;
    try {
      const parsed = new URL(url);
      valid = parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch {
      valid = false;
    }
    if (!valid) {
      ctx.addIssue({
        code: "custom",
        path: ["url"],
        message: "Enter an http(s) URL, e.g. http://geo-agent:8080",
      });
    }
  });

type AgentFormValues = z.input<typeof agentSchema>;
type AgentFormOutput = z.output<typeof agentSchema>;

export interface AgentSourceEditValue {
  sourceId: string;
  transport: AgentTransport;
  agentId: string;
  url: string | null;
  credentialId: number | null;
  maxConcurrency: number;
  maxRequestBytes: number;
  maxTimeoutSeconds: number;
}

interface AgentSourceDialogProps {
  open: boolean;
  mode: "create" | "edit";
  initialValue?: AgentSourceEditValue | null;
  existingSourceIds?: string[];
  isSaving?: boolean;
  onClose: () => void;
  onCreate: (values: AgentSourceCreatePayload) => void;
  onUpdate: (sourceId: string, values: AgentSourceUpdatePayload) => void;
}

const EMPTY_DEFAULTS = {
  sourceId: "",
  transport: "http",
  agentId: "",
  url: "",
  credentialId: undefined,
  maxConcurrency: 4,
  maxRequestKib: 1024,
  maxTimeoutSeconds: 60,
} as unknown as AgentFormValues;

const EMPTY_SOURCE_IDS: string[] = [];

export function AgentSourceDialog({
  open,
  mode,
  initialValue,
  existingSourceIds = EMPTY_SOURCE_IDS,
  isSaving = false,
  onClose,
  onCreate,
  onUpdate,
}: AgentSourceDialogProps) {
  const { testConnection } = useAgentSourcesMutations();
  const {
    register,
    handleSubmit,
    reset,
    control,
    setError,
    formState: { errors },
  } = useForm<AgentFormValues, unknown, AgentFormOutput>({
    resolver: zodResolver(agentSchema),
    defaultValues: EMPTY_DEFAULTS,
  });
  const transport = useWatch({ control, name: "transport" });
  const agentId = useWatch({ control, name: "agentId" });

  const wasOpenRef = useRef(false);
  useEffect(() => {
    if (open && !wasOpenRef.current) {
      reset(
        initialValue
          ? {
              sourceId: initialValue.sourceId,
              transport: initialValue.transport,
              agentId: initialValue.agentId,
              url: initialValue.url ?? "",
              credentialId: initialValue.credentialId ?? undefined,
              maxConcurrency: initialValue.maxConcurrency,
              maxRequestKib: Math.max(1, Math.round(initialValue.maxRequestBytes / BYTES_PER_KIB)),
              maxTimeoutSeconds: initialValue.maxTimeoutSeconds,
            }
          : EMPTY_DEFAULTS,
      );
    }
    wasOpenRef.current = open;
  }, [open, initialValue, reset]);

  const isEdit = mode === "edit";
  const editedSourceId = initialValue?.sourceId ?? "";

  const onSubmit = useCallback(
    (values: AgentFormOutput) => {
      if (!isEdit && existingSourceIds.includes(values.sourceId)) {
        setError("sourceId", { message: "This source ID is already in use" });
        return;
      }
      const shared = {
        transport: values.transport,
        agent_id: values.agentId.trim(),
        url: values.transport === "http" ? values.url.trim() : null,
        credential_id: values.credentialId,
        max_concurrency: values.maxConcurrency,
        max_request_bytes: values.maxRequestKib * BYTES_PER_KIB,
        max_timeout_seconds: values.maxTimeoutSeconds,
      };
      if (isEdit) {
        onUpdate(editedSourceId, shared);
        return;
      }
      onCreate({ source_id: values.sourceId, ...shared });
    },
    [editedSourceId, existingSourceIds, isEdit, onCreate, onUpdate, setError],
  );

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit agent: ${editedSourceId}` : "Add agent"}</DialogTitle>
          <DialogDescription>
            An agent runs your Python handlers for the Route to Agent step. Messages are
            encrypted and authenticated with a secret shared between the app and the agent.
          </DialogDescription>
        </DialogHeader>

        {isEdit ? <AgentStatusPanel sourceId={editedSourceId} enabled={open} /> : null}

        <form className="space-y-4" onSubmit={handleSubmit(onSubmit)}>
          <div className="space-y-2">
            <Label htmlFor="agent-source-id">Source ID</Label>
            <Input
              id="agent-source-id"
              placeholder="geo"
              disabled={isEdit}
              {...register("sourceId")}
            />
            {errors.sourceId ? (
              <p className="text-xs text-destructive">{errors.sourceId.message}</p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="agent-transport">Transport</Label>
            <Controller
              control={control}
              name="transport"
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="agent-transport">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="http">HTTP — agent on the same Docker host</SelectItem>
                    <SelectItem value="redis">Redis — agent on another host</SelectItem>
                  </SelectContent>
                </Select>
              )}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="agent-id">Agent ID</Label>
            <Input id="agent-id" placeholder="geo-agent" {...register("agentId")} />
            <p className="text-xs text-muted-foreground">
              Must match <code>MANUS_AGENT_ID</code> on the agent. It is bound into every
              message and names the agent&apos;s Redis keys.
            </p>
            {errors.agentId ? (
              <p className="text-xs text-destructive">{errors.agentId.message}</p>
            ) : null}
          </div>

          {transport === "http" ? (
            <div className="space-y-2">
              <Label htmlFor="agent-url">Agent URL</Label>
              <Input id="agent-url" placeholder="http://geo-agent:8080" {...register("url")} />
              {errors.url ? (
                <p className="text-xs text-destructive">{errors.url.message}</p>
              ) : null}
            </div>
          ) : (
            <div className="space-y-2 rounded-lg border bg-muted/30 p-3">
              <p className="text-xs text-muted-foreground">
                The agent connects to this app&apos;s Redis (Redis 7 or newer). Give it its own
                Redis user, limited to its keys, and run this on Redis. Replace the password. It
                starts with <code>reset</code>, so running it again replaces any earlier rules and
                passwords of that user. Keep it across restarts with an ACL file:
              </p>
              <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded bg-muted p-2 font-mono text-[11px]">
                {buildRedisAclCommand(agentId ?? "")}
              </pre>
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="agent-credential">Shared secret</Label>
            <Controller
              control={control}
              name="credentialId"
              render={({ field }) => (
                <CredentialSelect
                  id="agent-credential"
                  value={field.value ?? null}
                  onChange={(next) => field.onChange(next ?? undefined)}
                  credentialType="shared_secret"
                />
              )}
            />
            <p className="text-xs text-muted-foreground">
              A global shared-secret credential of at least 32 random characters (
              <code>{AGENT_SECRET_COMMAND}</code>). Set the same value as{" "}
              <code>MANUS_AGENT_SECRET</code> on the agent.
            </p>
            {errors.credentialId ? (
              <p className="text-xs text-destructive">{errors.credentialId.message}</p>
            ) : null}
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-2">
              <Label htmlFor="agent-concurrency">Parallel calls</Label>
              <Input
                id="agent-concurrency"
                type="number"
                min={1}
                max={64}
                {...register("maxConcurrency", { valueAsNumber: true })}
              />
              {errors.maxConcurrency ? (
                <p className="text-xs text-destructive">1 to 64</p>
              ) : null}
            </div>
            <div className="space-y-2">
              <Label htmlFor="agent-request-kib">Max request (KiB)</Label>
              <Input
                id="agent-request-kib"
                type="number"
                min={1}
                max={8192}
                {...register("maxRequestKib", { valueAsNumber: true })}
              />
              {errors.maxRequestKib ? (
                <p className="text-xs text-destructive">1 to 8192</p>
              ) : null}
            </div>
            <div className="space-y-2">
              <Label htmlFor="agent-timeout">Max timeout (s)</Label>
              <Input
                id="agent-timeout"
                type="number"
                min={1}
                max={600}
                {...register("maxTimeoutSeconds", { valueAsNumber: true })}
              />
              {errors.maxTimeoutSeconds ? (
                <p className="text-xs text-destructive">1 to 600</p>
              ) : null}
            </div>
          </div>

          <DialogFooter className="gap-2 sm:gap-2">
            {isEdit ? (
              <Button
                type="button"
                variant="outline"
                disabled={testConnection.isPending}
                onClick={() => testConnection.mutate({ source_id: editedSourceId })}
              >
                {testConnection.isPending ? "Testing…" : "Test connection"}
              </Button>
            ) : null}
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSaving}>
              {isSaving ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
          {isEdit ? null : (
            <p className="text-xs text-muted-foreground">
              Save the source first, then use Test connection once the agent is running.
            </p>
          )}
        </form>
      </DialogContent>
    </Dialog>
  );
}
