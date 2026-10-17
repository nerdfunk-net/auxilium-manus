"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { useMemo } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { useMailSettingsMutations } from "@/hooks/queries/use-mail-settings-mutations";
import { useMailSettingsQuery } from "@/hooks/queries/use-mail-settings-query";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";

import { useCredentialsQuery } from "../credentials/hooks/use-credentials-query";
import {
  MAIL_SECURITY_OPTIONS,
  type MailSecurity,
  type MailSettings,
} from "../types/mail";

/** Radix Select forbids an empty-string item value, so "no login" needs a sentinel. */
const NO_CREDENTIAL = "__none__";

const formSchema = z
  .object({
    smtp_server: z.string().trim().max(255),
    smtp_port: z.number().int().min(1).max(65535),
    security: z.enum(["none", "starttls", "ssl"]),
    verify_tls: z.boolean(),
    from_address: z.string().trim().max(320),
    credential: z.string(),
    // One domain per line or separated by commas; empty allows every domain.
    allowed_domains: z.string(),
  })
  .refine((values) => values.credential === NO_CREDENTIAL || values.security !== "none", {
    message: "A login needs STARTTLS or SSL/TLS: the password is not sent unencrypted",
    path: ["security"],
  })
  .refine((values) => parseDomains(values.allowed_domains).invalid.length === 0, {
    message: "Enter domain names such as example.org",
    path: ["allowed_domains"],
  })
  .refine((values) => values.from_address === "" || /^[^@\s<>,;]+@[^@\s<>,;]+$/.test(values.from_address), {
    message: "Enter an email address such as reports@example.org",
    path: ["from_address"],
  });

type FormValues = z.infer<typeof formSchema>;

const DOMAIN = /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$/;

function parseDomains(text: string): { domains: string[]; invalid: string[] } {
  const domains: string[] = [];
  const invalid: string[] = [];
  for (const entry of text.split(/[\s,;]+/)) {
    const domain = entry.trim().toLowerCase().replace(/\.$/, "");
    if (domain === "") continue;
    if (!DOMAIN.test(domain)) invalid.push(entry);
    else if (!domains.includes(domain)) domains.push(domain);
  }
  return { domains, invalid };
}

const EMPTY: FormValues = {
  smtp_server: "",
  smtp_port: 587,
  security: "starttls",
  verify_tls: true,
  from_address: "",
  credential: NO_CREDENTIAL,
  allowed_domains: "",
};

function toPayload(values: FormValues): MailSettings {
  return {
    smtp_server: values.smtp_server.trim(),
    smtp_port: values.smtp_port,
    security: values.security,
    verify_tls: values.verify_tls,
    from_address: values.from_address.trim(),
    credential_name: values.credential === NO_CREDENTIAL ? null : values.credential,
    allowed_recipient_domains: parseDomains(values.allowed_domains).domains,
  };
}

/** The SMTP server reports are mailed through (global; the password comes from a credential). */
export function MailSettingsCanvas() {
  const user = useAuthStore((state) => state.user);
  const canWrite = hasPermission(user, "system.mail", "write");
  const { data: settings, isLoading } = useMailSettingsQuery();
  const { data: credentialData } = useCredentialsQuery();
  const { saveSettings, testConnection } = useMailSettingsMutations();

  const credentials = useMemo(
    () =>
      (credentialData?.credentials ?? []).filter(
        (c) => c.type === "generic" && c.visibility === "global" && c.status !== "expired",
      ),
    [credentialData?.credentials],
  );

  const values = useMemo<FormValues>(
    () =>
      settings
        ? {
            smtp_server: settings.smtp_server,
            smtp_port: settings.smtp_port,
            security: settings.security,
            verify_tls: settings.verify_tls,
            from_address: settings.from_address,
            credential: settings.credential_name ?? NO_CREDENTIAL,
            allowed_domains: settings.allowed_recipient_domains.join("\n"),
          }
        : EMPTY,
    [settings],
  );
  const form = useForm<FormValues>({ resolver: zodResolver(formSchema), values });
  const dirty = form.formState.isDirty;

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center bg-muted">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const handleSecurityChange = (next: MailSecurity, onChange: (value: MailSecurity) => void) => {
    // Move the port to the new protocol's usual one, but only while it is still the old default.
    const previous = MAIL_SECURITY_OPTIONS.find((o) => o.value === form.getValues("security"));
    const target = MAIL_SECURITY_OPTIONS.find((o) => o.value === next);
    if (previous && target && form.getValues("smtp_port") === previous.port) {
      form.setValue("smtp_port", target.port, { shouldDirty: true });
    }
    onChange(next);
  };

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto bg-muted p-8">
      <div className="mx-auto w-full max-w-2xl space-y-6">
        {!canWrite ? (
          <Alert>
            <AlertDescription>You can view these settings but not change them.</AlertDescription>
          </Alert>
        ) : null}
        <Form {...form}>
          <form
            onSubmit={form.handleSubmit((v) => saveSettings.mutate(toPayload(v)))}
            className="space-y-6"
          >
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">SMTP server</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
                  <FormField
                    control={form.control}
                    name="smtp_server"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Server</FormLabel>
                        <FormControl>
                          <Input placeholder="smtp.example.org" disabled={!canWrite} {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="smtp_port"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Port</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            min={1}
                            max={65535}
                            disabled={!canWrite}
                            {...field}
                            onChange={(e) => field.onChange(e.target.valueAsNumber)}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
                <FormField
                  control={form.control}
                  name="security"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Security</FormLabel>
                      <Select
                        value={field.value}
                        onValueChange={(v) => handleSecurityChange(v as MailSecurity, field.onChange)}
                        disabled={!canWrite}
                      >
                        <FormControl>
                          <SelectTrigger className="w-64">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {MAIL_SECURITY_OPTIONS.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                              {option.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="verify_tls"
                  render={({ field }) => (
                    <FormItem className="flex items-center justify-between rounded-lg border p-3">
                      <div>
                        <FormLabel>Verify the server certificate</FormLabel>
                        <FormDescription>
                          Turn off only for a server with a self-signed certificate.
                        </FormDescription>
                      </div>
                      <FormControl>
                        <Switch
                          checked={field.value}
                          onCheckedChange={field.onChange}
                          disabled={!canWrite}
                        />
                      </FormControl>
                    </FormItem>
                  )}
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Sender and login</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField
                  control={form.control}
                  name="from_address"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>From address</FormLabel>
                      <FormControl>
                        <Input placeholder="reports@example.org" disabled={!canWrite} {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="credential"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Login credential</FormLabel>
                      <Select value={field.value} onValueChange={field.onChange} disabled={!canWrite}>
                        <FormControl>
                          <SelectTrigger className="w-64">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value={NO_CREDENTIAL}>No login</SelectItem>
                          {credentials.map((credential) => (
                            <SelectItem key={credential.id} value={credential.name}>
                              {credential.name}
                            </SelectItem>
                          ))}
                          {field.value !== NO_CREDENTIAL &&
                          !credentials.some((c) => c.name === field.value) ? (
                            <SelectItem value={field.value}>{field.value} (unavailable)</SelectItem>
                          ) : null}
                        </SelectContent>
                      </Select>
                      <FormDescription>
                        A global credential of type generic: its user name and password sign in to
                        the server.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Recipients</CardTitle>
              </CardHeader>
              <CardContent>
                <FormField
                  control={form.control}
                  name="allowed_domains"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Allowed recipient domains</FormLabel>
                      <FormControl>
                        <Textarea
                          rows={3}
                          placeholder="example.org"
                          disabled={!canWrite}
                          {...field}
                        />
                      </FormControl>
                      <FormDescription>
                        Reports can only be sent to these domains and their subdomains. Leave empty
                        to allow any address.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </CardContent>
            </Card>

            {testConnection.data ? (
              <Alert variant={testConnection.data.ok ? "default" : "destructive"}>
                {testConnection.data.ok ? (
                  <CheckCircle2 className="size-4" />
                ) : (
                  <XCircle className="size-4" />
                )}
                <AlertDescription>{testConnection.data.message}</AlertDescription>
              </Alert>
            ) : null}

            <div className="flex items-center justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={!canWrite || dirty || !settings?.configured || testConnection.isPending}
                title={dirty ? "Save first: the test uses the saved settings" : undefined}
                onClick={() => testConnection.mutate()}
              >
                {testConnection.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
                Test connection
              </Button>
              <Button type="submit" disabled={!canWrite || saveSettings.isPending || !dirty}>
                {saveSettings.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
                Save Changes
              </Button>
            </div>
          </form>
        </Form>
      </div>
    </div>
  );
}
