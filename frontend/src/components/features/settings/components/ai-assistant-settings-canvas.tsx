"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import { useCallback, useMemo } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { AssistantPanel } from "@/components/features/ai-assistant/components/assistant-panel";
import { useAiAssistantAvailable } from "@/components/features/ai-assistant/hooks/use-ai-assistant-available";
import type {
  AiModelOption,
  AiProvider,
  AiSettings,
} from "@/components/features/ai-assistant/types/ai-assistant";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import { ShareConfirmSwitch } from "./share-confirm-switch";
import { useAuthStore } from "@/lib/auth-store";
import { hasRole } from "@/lib/permissions";
import { PROVIDER_LABELS } from "@/components/features/ai-assistant/constants/providers";
import { useAiSettingsMutations } from "@/hooks/queries/use-ai-settings-mutations";
import { useAiSettingsQuery } from "@/hooks/queries/use-ai-settings-query";

/** Inventory data categories that are more likely to hold sensitive values; each has its own opt-in. */
const INVENTORY_CATEGORIES = [
  {
    name: "share_device_addresses",
    label: "Addresses and serial numbers",
    description: "Primary IPs, interfaces, hostnames, serials and asset tags.",
    warning:
      "IP addresses, interfaces, hostnames, serial numbers and asset tags of your devices will be sent to the AI provider.",
  },
  {
    name: "share_custom_fields",
    label: "Custom fields",
    description:
      "Nautobot custom fields. They can hold free text such as credentials or owners.",
    warning:
      "Nautobot custom fields of your devices will be sent. They are free text and may contain credentials or internal information that automatic redaction does not recognise.",
  },
  {
    name: "share_config_context",
    label: "Config context",
    description:
      "Nautobot config context, which often carries keys, passwords and addressing.",
    warning:
      "The Nautobot config context of your devices will be sent. It often carries keys, passwords and addressing; secrets under unusual key names are not recognised by automatic redaction.",
  },
] as const;

const formSchema = z
  .object({
    enabled: z.boolean(),
    provider: z.enum(["anthropic", "gemini", "openai_compat"]),
    model: z.string().min(1, "Model is required"),
    base_url: z.string().max(512),
    api_key: z.string().max(512),
    share_inventory_data: z.boolean(),
    share_device_addresses: z.boolean(),
    share_custom_fields: z.boolean(),
    share_config_context: z.boolean(),
    share_content_data: z.boolean(),
  })
  .refine(
    (values) =>
      values.provider !== "openai_compat" || values.base_url.trim().length > 0,
    { message: "A server URL is required", path: ["base_url"] },
  );

type FormValues = z.infer<typeof formSchema>;

const EMPTY_MODEL_OPTIONS: AiModelOption[] = [];

export function AiAssistantSettingsCanvas() {
  const { data: settings, isLoading } = useAiSettingsQuery();

  if (isLoading || !settings) {
    return (
      <div className="flex h-full items-center justify-center bg-muted">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // The form is created only once the settings exist, so its first render already holds the
  // stored model. Starting empty and filling it in later left the model Select showing nothing.
  return <AiAssistantSettingsForm settings={settings} />;
}

function AiAssistantSettingsForm({ settings }: { settings: AiSettings }) {
  const { saveSettings, testConnection } = useAiSettingsMutations();
  const available = useAiAssistantAvailable();
  // Only an administrator may point the backend at a custom server (it is an outbound request).
  const canSetServerUrl = useAuthStore((state) => hasRole(state.user, "admin"));

  const defaultValues = useMemo<FormValues>(
    () => ({
      enabled: settings.enabled,
      provider: settings.provider,
      model: settings.model,
      base_url: settings.base_url ?? "",
      api_key: "",
      share_inventory_data: settings.share_inventory_data,
      share_device_addresses: settings.share_device_addresses,
      share_custom_fields: settings.share_custom_fields,
      share_config_context: settings.share_config_context,
      share_content_data: settings.share_content_data,
    }),
    [settings],
  );

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    values: defaultValues,
  });

  const handleSave = useCallback(
    (values: FormValues) => {
      const { api_key, base_url, ...rest } = values;
      // A blank key field means "leave the stored key unchanged"; the base URL only applies to
      // the OpenAI-compatible provider.
      const payload = {
        ...rest,
        ...(rest.provider === "openai_compat" && canSetServerUrl
          ? { base_url: base_url.trim() }
          : {}),
        ...(api_key.trim() ? { api_key: api_key.trim() } : {}),
      };
      saveSettings.mutate(payload, {
        // Replacing a key can leave the cached settings object unchanged, so the form's
        // `values` never refresh; clear the plaintext key from the form explicitly.
        onSuccess: () => form.reset({ ...values, api_key: "" }),
      });
    },
    [canSetServerUrl, form, saveSettings],
  );

  const handleRemoveKey = useCallback(() => {
    saveSettings.mutate({ clear_api_key: true });
  }, [saveSettings]);

  const handleTest = useCallback(
    () => testConnection.mutate(),
    [testConnection],
  );

  const keySet = settings.api_key_set ?? false;
  const configured = settings.configured ?? false;
  const providers = settings.available_providers ?? [];
  const dirty = form.formState.isDirty;
  const selectedProvider = useWatch({
    control: form.control,
    name: "provider",
  });
  const inventoryShared = useWatch({
    control: form.control,
    name: "share_inventory_data",
  });
  const selectedModelId = useWatch({ control: form.control, name: "model" });
  const modelOptions =
    settings.available_models[selectedProvider] ?? EMPTY_MODEL_OPTIONS;
  const selectedModel = modelOptions.find(
    (option) => option.id === selectedModelId,
  );

  // Changing provider invalidates the model: fall back to that provider's first (default) model.
  const handleProviderChange = useCallback(
    (provider: AiProvider) => {
      form.setValue("provider", provider, { shouldDirty: true });
      // A model id (or server URL) from another provider is meaningless here.
      const first = settings.available_models[provider]?.[0];
      form.setValue("model", first?.id ?? "", { shouldDirty: true });
      form.setValue("base_url", "", { shouldDirty: true });
    },
    [form, settings],
  );

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto bg-muted p-8">
      <div className="mx-auto w-full max-w-2xl space-y-6">
        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSave)} className="space-y-6">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">AI Assistant</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField
                  control={form.control}
                  name="enabled"
                  render={({ field }) => (
                    <FormItem className="flex items-center justify-between gap-4">
                      <div className="space-y-1">
                        <FormLabel>Enable the AI assistant</FormLabel>
                        <FormDescription>
                          When off, all assistant panels are hidden for you.
                          Your key and settings are kept.
                        </FormDescription>
                      </div>
                      <FormControl>
                        <Switch
                          checked={field.value}
                          onCheckedChange={field.onChange}
                        />
                      </FormControl>
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="provider"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Provider</FormLabel>
                      <Select
                        value={field.value}
                        onValueChange={handleProviderChange}
                      >
                        <FormControl>
                          <SelectTrigger className="w-full">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {providers.map((provider) => (
                            <SelectItem key={provider} value={provider}>
                              {PROVIDER_LABELS[provider]}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                {selectedProvider === "openai_compat" && (
                  <FormField
                    control={form.control}
                    name="base_url"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Server URL</FormLabel>
                        <FormControl>
                          <Input
                            className="font-mono text-xs"
                            placeholder="http://ollama-host:11434/v1"
                            disabled={!canSetServerUrl}
                            {...field}
                          />
                        </FormControl>
                        <FormDescription>
                          The server&apos;s OpenAI-compatible base URL (for
                          Ollama: http://host:11434/v1). A server on the same
                          machine as the backend is only reachable when the
                          backend runs with ALLOW_LOOPBACK_SOURCE_URLS enabled.
                          {!canSetServerUrl &&
                            " Only an administrator can change the server URL."}
                        </FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}
                <FormField
                  control={form.control}
                  name="model"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Model</FormLabel>
                      {modelOptions.length > 0 ? (
                        <Select
                          value={field.value}
                          onValueChange={field.onChange}
                        >
                          <FormControl>
                            <SelectTrigger className="w-full">
                              <SelectValue />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            {modelOptions.map((option) => (
                              <SelectItem key={option.id} value={option.id}>
                                {option.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      ) : (
                        <FormControl>
                          <Input
                            className="font-mono text-xs"
                            placeholder="e.g. llama3.1:8b"
                            {...field}
                          />
                        </FormControl>
                      )}
                      {selectedModel && (
                        <FormDescription>
                          {selectedModel.description}
                        </FormDescription>
                      )}
                      {selectedProvider === "openai_compat" && (
                        <FormDescription>
                          Tool use (editing templates through proposals) depends
                          on the model; smaller local models may handle it
                          poorly.
                        </FormDescription>
                      )}
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="api_key"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>
                        API key
                        {selectedProvider === "openai_compat" && " (optional)"}
                      </FormLabel>
                      <div className="flex items-center gap-2">
                        <FormControl>
                          <Input
                            type="password"
                            autoComplete="off"
                            placeholder={
                              keySet
                                ? "Key saved — enter a new one to replace"
                                : ""
                            }
                            {...field}
                          />
                        </FormControl>
                        {keySet && (
                          <Button
                            type="button"
                            variant="outline"
                            onClick={handleRemoveKey}
                            disabled={saveSettings.isPending}
                          >
                            Remove
                          </Button>
                        )}
                      </div>
                      <FormDescription>
                        Private to your account and stored encrypted. It is
                        never shown again after saving.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">
                  Data sent to the model
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <Alert>
                  <AlertTitle>Opt-in only</AlertTitle>
                  <AlertDescription>
                    Workflows, templates and step schemas are sent as the
                    assistant needs them. Anything derived from devices or runs
                    is sent only if you allow it below. Config backups and
                    command output can contain passwords or keys; automatic
                    redaction is best-effort, not a guarantee.
                  </AlertDescription>
                </Alert>
                <FormField
                  control={form.control}
                  name="share_inventory_data"
                  render={({ field }) => (
                    <FormItem className="flex items-center justify-between gap-4">
                      <div className="space-y-1">
                        <FormLabel>Inventory and device attributes</FormLabel>
                        <FormDescription>
                          Device names, role, platform, location, status and
                          tags. The categories below need this switch too.
                        </FormDescription>
                      </div>
                      <FormControl>
                        <ShareConfirmSwitch
                          checked={field.value}
                          label="Inventory and device attributes"
                          warning="Device names, roles, platforms, locations, status and tags from your inventories will be sent to the AI provider."
                          onChange={field.onChange}
                        />
                      </FormControl>
                    </FormItem>
                  )}
                />
                {INVENTORY_CATEGORIES.map((category) => (
                  <FormField
                    key={category.name}
                    control={form.control}
                    name={category.name}
                    render={({ field }) => (
                      <FormItem className="ml-6 flex items-center justify-between gap-4 border-l pl-4">
                        <div className="space-y-1">
                          <FormLabel>{category.label}</FormLabel>
                          <FormDescription>
                            {category.description}
                          </FormDescription>
                        </div>
                        <FormControl>
                          <ShareConfirmSwitch
                            checked={field.value && inventoryShared}
                            disabled={!inventoryShared}
                            label={category.label}
                            warning={category.warning}
                            onChange={field.onChange}
                          />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                ))}
                <FormField
                  control={form.control}
                  name="share_content_data"
                  render={({ field }) => (
                    <FormItem className="flex items-center justify-between gap-4">
                      <div className="space-y-1">
                        <FormLabel>Run and device content</FormLabel>
                        <FormDescription>
                          Config backups, command output, run logs and step
                          error text.
                        </FormDescription>
                      </div>
                      <FormControl>
                        <ShareConfirmSwitch
                          checked={field.value}
                          label="Run and device content"
                          warning="Command output, config backups, run logs and error text will be sent to the AI provider. They frequently contain hostnames, addresses and sometimes credentials."
                          onChange={field.onChange}
                        />
                      </FormControl>
                    </FormItem>
                  )}
                />
              </CardContent>
            </Card>

            <div className="flex items-center gap-2">
              <Button type="submit" disabled={saveSettings.isPending || !dirty}>
                {saveSettings.isPending && (
                  <Loader2 className="size-4 animate-spin" />
                )}
                Save
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={handleTest}
                disabled={!configured || dirty || testConnection.isPending}
              >
                {testConnection.isPending && (
                  <Loader2 className="size-4 animate-spin" />
                )}
                Test connection
              </Button>
              {dirty && configured && (
                <span className="text-xs text-muted-foreground">
                  Save before testing.
                </span>
              )}
            </div>
          </form>
        </Form>

        {available && (
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Try it</CardTitle>
            </CardHeader>
            <CardContent className="h-96">
              <AssistantPanel />
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
