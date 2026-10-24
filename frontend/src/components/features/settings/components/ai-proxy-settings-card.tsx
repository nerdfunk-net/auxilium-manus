"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import { useCallback, useMemo } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import type { AiProxySettings } from "@/components/features/ai-assistant/types/ai-assistant";
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
import { Switch } from "@/components/ui/switch";
import { useAiProxyMutations } from "@/hooks/queries/use-ai-proxy-mutations";
import { useAiProxyQuery } from "@/hooks/queries/use-ai-proxy-query";

import { CredentialSelect } from "../credentials/components/credential-select";

const formSchema = z
  .object({
    enabled: z.boolean(),
    url: z.string().max(512),
    credential_id: z.number().nullable(),
    bypass_hosts: z.string().max(2000),
  })
  .refine((values) => !values.enabled || values.url.trim().length > 0, {
    message: "A proxy URL is required",
    path: ["url"],
  });

type FormValues = z.infer<typeof formSchema>;

/** "a.corp, 10.0.0.0/8" -> ["a.corp", "10.0.0.0/8"] */
function parseHosts(raw: string): string[] {
  return raw
    .split(/[\s,]+/)
    .map((host) => host.trim())
    .filter((host) => host.length > 0);
}

/** Administrator-only: one outbound proxy for every user's AI traffic. */
export function AiProxySettingsCard() {
  const { data, isLoading } = useAiProxyQuery();
  if (isLoading || !data) {
    return (
      <Card>
        <CardContent className="flex justify-center py-8">
          <Loader2 className="size-5 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }
  return <AiProxySettingsForm settings={data} />;
}

function AiProxySettingsForm({ settings }: { settings: AiProxySettings }) {
  const { saveProxy } = useAiProxyMutations();

  const values = useMemo<FormValues>(
    () => ({
      enabled: settings.enabled,
      url: settings.url,
      credential_id: settings.credential_id,
      bypass_hosts: settings.bypass_hosts.join(", "),
    }),
    [settings],
  );

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    values,
  });

  const handleSave = useCallback(
    (next: FormValues) => {
      saveProxy.mutate({
        enabled: next.enabled,
        url: next.url.trim(),
        credential_id: next.credential_id,
        bypass_hosts: parseHosts(next.bypass_hosts),
      });
    },
    [saveProxy],
  );

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Proxy</CardTitle>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form
            onSubmit={form.handleSubmit(handleSave)}
            className="space-y-4"
            aria-label="AI proxy settings"
          >
            <FormField
              control={form.control}
              name="enabled"
              render={({ field }) => (
                <FormItem className="flex items-center justify-between gap-4">
                  <div className="space-y-1">
                    <FormLabel>Use a proxy</FormLabel>
                    <FormDescription>
                      Sends the traffic of every user&apos;s assistant to the
                      provider through this HTTP/HTTPS proxy. Applies to all
                      providers.
                    </FormDescription>
                  </div>
                  <FormControl>
                    <Switch
                      checked={field.value}
                      onCheckedChange={field.onChange}
                      aria-label="Use a proxy"
                    />
                  </FormControl>
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="url"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Proxy URL</FormLabel>
                  <FormControl>
                    <Input
                      className="font-mono text-xs"
                      placeholder="http://proxy.example.com:3128"
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Without a user name or password. With a plain http URL the
                    proxy login is sent unencrypted to the proxy.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="credential_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Proxy login</FormLabel>
                  <CredentialSelect
                    id="ai-proxy-credential"
                    value={field.value}
                    onChange={field.onChange}
                    credentialType="generic"
                    placeholder="No authentication"
                  />
                  <FormDescription>
                    A global Basic Auth credential with the proxy&apos;s user
                    name and password. Leave empty for a proxy without login.
                  </FormDescription>
                  {field.value != null && (
                    <Button
                      type="button"
                      variant="link"
                      size="sm"
                      className="h-auto p-0"
                      onClick={() => field.onChange(null)}
                    >
                      Remove login
                    </Button>
                  )}
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="bypass_hosts"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Bypass hosts</FormLabel>
                  <FormControl>
                    <Input
                      className="font-mono text-xs"
                      placeholder="ollama.corp.example, 10.0.0.0/8"
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Servers reached directly, e.g. an internal Ollama. A
                    host name, a domain with at least two labels (corp.example
                    also covers its subdomains), an IP address or a CIDR range,
                    separated by commas.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <div className="flex items-center gap-3">
              <Button
                type="submit"
                disabled={saveProxy.isPending || !form.formState.isDirty}
              >
                {saveProxy.isPending && (
                  <Loader2 className="size-4 animate-spin" />
                )}
                Save proxy
              </Button>
              <span className="text-xs text-muted-foreground">
                Use &ldquo;Test connection&rdquo; above to check it.
              </span>
            </div>
          </form>
        </Form>
      </CardContent>
    </Card>
  );
}
