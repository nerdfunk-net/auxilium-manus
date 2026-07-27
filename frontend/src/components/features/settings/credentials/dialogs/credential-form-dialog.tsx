"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
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
import { Switch } from "@/components/ui/switch";

import type { Credential } from "../types";
import { toDateInputValue } from "../utils/credential-utils";

const formSchema = z.object({
  name: z.string().min(1, "Required").max(128),
  username: z.string().min(1, "Required").max(128),
  password: z.string().optional(),
  valid_until: z.string().optional(),
  visibility: z.enum(["global", "private"]),
});

type FormValues = z.infer<typeof formSchema>;

interface CredentialFormDialogProps {
  open: boolean;
  mode: "create" | "edit";
  credential?: Credential;
  isSaving?: boolean;
  onClose: () => void;
  onSubmit: (values: FormValues) => void;
}

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
    defaultValues: {
      name: "",
      username: "",
      password: "",
      valid_until: "",
      visibility: "private",
    },
  });

  useEffect(() => {
    if (!open) {
      return;
    }
    if (mode === "edit" && credential) {
      form.reset({
        name: credential.name,
        username: credential.username,
        password: "",
        valid_until: toDateInputValue(credential.valid_until),
        visibility: credential.visibility,
      });
      return;
    }
    form.reset({
      name: "",
      username: "",
      password: "",
      valid_until: "",
      visibility: "private",
    });
  }, [credential, form, mode, open]);

  const handleSubmit = (values: FormValues) => {
    if (mode === "create" && !values.password?.trim()) {
      form.setError("password", { message: "Password is required" });
      return;
    }
    onSubmit(values);
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {mode === "create" ? "Add SSH login" : "Edit SSH login"}
          </DialogTitle>
          <DialogDescription>
            Credentials are encrypted at rest. Passwords are never shown after
            saving.
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
                    Unique identifier referenced by workflow steps.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="username"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Username</FormLabel>
                  <FormControl>
                    <Input placeholder="admin" autoComplete="off" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Password{mode === "edit" ? " (leave blank to keep)" : ""}
                  </FormLabel>
                  <FormControl>
                    <Input
                      type="password"
                      autoComplete="new-password"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

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
                      Global credentials are visible and usable by all users.
                      Private credentials are visible only to you.
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
