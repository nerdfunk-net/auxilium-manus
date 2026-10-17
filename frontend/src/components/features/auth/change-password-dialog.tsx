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
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { useChangePasswordMutation } from "@/hooks/queries/use-auth-mutations";

const formSchema = z
  .object({
    current_password: z.string().min(1, "Required"),
    new_password: z.string().min(12, "Must be at least 12 characters").max(128),
    confirm_password: z.string().min(1, "Required"),
  })
  .refine((values) => values.new_password === values.confirm_password, {
    message: "Passwords do not match",
    path: ["confirm_password"],
  });

type FormValues = z.infer<typeof formSchema>;

const DEFAULT_VALUES: FormValues = {
  current_password: "",
  new_password: "",
  confirm_password: "",
};

interface ChangePasswordDialogProps {
  open: boolean;
  /** Non-dismissable: no close button, Escape, or outside click. Used when
   * the account's must_change_password flag is set. */
  forced?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function ChangePasswordDialog({
  open,
  forced = false,
  onOpenChange,
}: ChangePasswordDialogProps) {
  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: DEFAULT_VALUES,
  });
  const changePassword = useChangePasswordMutation();

  useEffect(() => {
    if (open) {
      form.reset(DEFAULT_VALUES);
    }
  }, [form, open]);

  const handleSubmit = (values: FormValues) => {
    changePassword.mutate(
      { current_password: values.current_password, new_password: values.new_password },
      { onSuccess: () => onOpenChange?.(false) },
    );
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !forced && onOpenChange?.(next)}>
      <DialogContent
        className="sm:max-w-md"
        hideCloseButton={forced}
        onEscapeKeyDown={(event) => forced && event.preventDefault()}
        onPointerDownOutside={(event) => forced && event.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>Change password</DialogTitle>
          <DialogDescription>
            {forced
              ? "You must set a new password before continuing."
              : "Choose a new password for your account."}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form className="space-y-4" onSubmit={form.handleSubmit(handleSubmit)}>
            <FormField
              control={form.control}
              name="current_password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Current password</FormLabel>
                  <FormControl>
                    <Input autoComplete="current-password" type="password" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="new_password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>New password</FormLabel>
                  <FormControl>
                    <Input autoComplete="new-password" type="password" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="confirm_password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Confirm new password</FormLabel>
                  <FormControl>
                    <Input autoComplete="new-password" type="password" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <DialogFooter>
              {forced ? null : (
                <Button type="button" variant="outline" onClick={() => onOpenChange?.(false)}>
                  Cancel
                </Button>
              )}
              <Button type="submit" disabled={changePassword.isPending}>
                {changePassword.isPending ? "Saving…" : "Change password"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
