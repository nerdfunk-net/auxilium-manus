"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
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
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

import type { Credential, CredentialType } from "../types";
import { SELECTABLE_CREDENTIAL_TYPES, credentialTypeLabel } from "../utils/credential-utils";
import { toDateInputValue } from "../utils/credential-utils";

const formSchema = z
  .object({
    name: z.string().min(1, "Required").max(128),
    username: z.string().min(1, "Required").max(128),
    type: z.enum(["ssh", "ssh_key", "token", "generic"]),
    password: z.string().optional(),
    ssh_private_key: z.string().optional(),
    ssh_passphrase: z.string().optional(),
    valid_until: z.string().optional(),
    visibility: z.enum(["global", "private"]),
  })
  .refine(
    (values) => values.type !== "ssh_key" || Boolean(values.ssh_private_key?.trim()),
    { message: "SSH private key is required", path: ["ssh_private_key"] },
  );

type FormValues = z.infer<typeof formSchema>;

interface CredentialFormDialogProps {
  open: boolean;
  mode: "create" | "edit";
  credential?: Credential;
  isSaving?: boolean;
  onClose: () => void;
  onSubmit: (values: FormValues) => void;
}

const EMPTY_DEFAULTS: FormValues = {
  name: "",
  username: "",
  type: "ssh",
  password: "",
  ssh_private_key: "",
  ssh_passphrase: "",
  valid_until: "",
  visibility: "private",
};

const USERNAME_HINTS: Record<CredentialType, string> = {
  ssh: "admin",
  ssh_key: "git",
  token: "the account the token belongs to, if required",
  generic: "admin",
  tacacs: "",
};

export function CredentialFormDialog({
  open,
  mode,
  credential,
  isSaving = false,
  onClose,
  onSubmit,
}: CredentialFormDialogProps) {
  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: EMPTY_DEFAULTS,
  });

  const type = useWatch({ control: form.control, name: "type" });

  useEffect(() => {
    if (!open) {
      return;
    }
    if (mode === "edit" && credential) {
      const editableType = SELECTABLE_CREDENTIAL_TYPES.includes(credential.type)
        ? credential.type
        : "ssh";
      form.reset({
        name: credential.name,
        username: credential.username,
        type: editableType as "ssh" | "ssh_key" | "token" | "generic",
        password: "",
        ssh_private_key: "",
        ssh_passphrase: "",
        valid_until: toDateInputValue(credential.valid_until),
        visibility: credential.visibility,
      });
      return;
    }
    form.reset(EMPTY_DEFAULTS);
  }, [credential, form, mode, open]);

  const handleSubmit = (values: FormValues) => {
    if (mode === "create" && values.type !== "ssh_key" && !values.password?.trim()) {
      form.setError("password", { message: `${credentialTypeLabel(values.type)} is required` });
      return;
    }
    onSubmit(values);
  };

  const isEdit = mode === "edit";

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit credential" : "Add credential"}</DialogTitle>
          <DialogDescription>
            Credentials are encrypted at rest. Secrets are never shown again after saving.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form className="space-y-4" onSubmit={form.handleSubmit(handleSubmit)}>
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Credential ID</FormLabel>
                  <FormControl>
                    <Input placeholder="lab-core-switch" {...field} />
                  </FormControl>
                  <FormDescription>
                    Unique identifier referenced by workflow steps and Git repository config.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormItem>
              <FormLabel>Type</FormLabel>
              <Controller
                control={form.control}
                name="type"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange} disabled={isEdit}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {SELECTABLE_CREDENTIAL_TYPES.map((option) => (
                        <SelectItem key={option} value={option}>
                          {credentialTypeLabel(option)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
              <FormDescription>
                {isEdit
                  ? "The type cannot be changed after creation."
                  : "SSH Login and Token use a username + secret. SSH Key uses a private key."}
              </FormDescription>
            </FormItem>

            <FormField
              control={form.control}
              name="username"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Username{type === "token" ? " (optional for some hosts)" : ""}</FormLabel>
                  <FormControl>
                    <Input placeholder={USERNAME_HINTS[type]} autoComplete="off" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {type === "ssh_key" ? (
              <>
                <FormField
                  control={form.control}
                  name="ssh_private_key"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>
                        SSH private key{isEdit ? " (leave blank to keep)" : ""}
                      </FormLabel>
                      <FormControl>
                        <Textarea
                          placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                          className="min-h-32 font-mono text-xs"
                          autoComplete="off"
                          {...field}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="ssh_passphrase"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>
                        Key passphrase (optional){isEdit ? " — leave blank to keep" : ""}
                      </FormLabel>
                      <FormControl>
                        <Input type="password" autoComplete="new-password" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </>
            ) : (
              <FormField
                control={form.control}
                name="password"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      {type === "token" ? "Token" : "Password"}
                      {isEdit ? " (leave blank to keep)" : ""}
                    </FormLabel>
                    <FormControl>
                      <Input type="password" autoComplete="new-password" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            <FormField
              control={form.control}
              name="valid_until"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Valid until</FormLabel>
                  <FormControl>
                    <Input type="date" {...field} />
                  </FormControl>
                  <FormDescription>
                    Optional expiry date for credential rotation tracking.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="visibility"
              render={({ field }) => (
                <FormItem className="flex flex-row items-center justify-between rounded-lg border p-3">
                  <div className="space-y-0.5">
                    <FormLabel>Make this credential global</FormLabel>
                    <FormDescription>
                      Global credentials are visible and usable by all users — required for Git
                      repositories and other background integrations. Private credentials are
                      visible only to you.
                    </FormDescription>
                  </div>
                  <FormControl>
                    <Switch
                      checked={field.value === "global"}
                      onCheckedChange={(checked) =>
                        field.onChange(checked ? "global" : "private")
                      }
                    />
                  </FormControl>
                </FormItem>
              )}
            />

            <DialogFooter>
              <Button type="button" variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit" disabled={isSaving}>
                {isSaving ? "Saving…" : mode === "create" ? "Create" : "Save"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
