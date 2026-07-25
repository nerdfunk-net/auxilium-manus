"use client";

import { AlertCircle, ArrowLeft, CheckCircle2, Loader2, Shield, XCircle } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApi } from "@/hooks/use-api";
import {
  useOidcDebugQuery,
  type OidcProviderDebugInfo,
} from "@/hooks/queries/use-oidc-debug-query";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";

function StatusCard({
  label,
  value,
  ok,
}: {
  label: string;
  value: string;
  ok: boolean;
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 pt-6">
        {ok ? (
          <CheckCircle2 className="size-5 text-green-600" />
        ) : (
          <XCircle className="size-5 text-muted-foreground" />
        )}
        <div>
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="font-medium">{value}</p>
        </div>
      </CardContent>
    </Card>
  );
}

function ProviderDetail({ provider }: { provider: OidcProviderDebugInfo }) {
  const { apiCall } = useApi();
  const [redirectUri, setRedirectUri] = useState(
    typeof window !== "undefined" ? `${window.location.origin}/login/oidc-test-callback` : "",
  );
  const [useOverrides, setUseOverrides] = useState(false);
  const [scopes, setScopes] = useState(provider.scopes.join(" "));
  const [clientId, setClientId] = useState(provider.client_id ?? "");
  const [responseType, setResponseType] = useState("code");
  const [testError, setTestError] = useState("");
  const [isTesting, setIsTesting] = useState(false);

  const handleTestLogin = async () => {
    setIsTesting(true);
    setTestError("");

    try {
      const data = useOverrides
        ? await apiCall<{ authorization_url: string; state: string }>(
            `auth/oidc/${provider.provider_id}/test-login`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                redirect_uri: redirectUri,
                scopes: scopes.split(/\s+/).filter(Boolean),
                response_type: responseType,
                client_id: clientId || undefined,
              }),
            },
          )
        : await apiCall<{ authorization_url: string; state: string }>(
            `auth/oidc/${provider.provider_id}/login?redirect_uri=${encodeURIComponent(redirectUri)}`,
            { method: "GET" },
          );

      sessionStorage.setItem("oidc_state", data.state);
      window.location.assign(data.authorization_url);
    } catch (err) {
      setTestError(err instanceof Error ? err.message : "Test login failed");
      setIsTesting(false);
    }
  };

  return (
    <Tabs defaultValue="configuration">
      <TabsList>
        <TabsTrigger value="configuration">Configuration</TabsTrigger>
        <TabsTrigger value="endpoints">Endpoints</TabsTrigger>
        <TabsTrigger value="test-login">Test Login</TabsTrigger>
      </TabsList>

      <TabsContent className="space-y-3 text-sm" value="configuration">
        <Row label="Provider ID" value={provider.provider_id} />
        <Row label="Name" value={provider.name} />
        <Row label="Client ID" value={provider.client_id ?? "—"} />
        <Row label="Discovery URL" value={provider.discovery_url ?? "—"} />
        <Row label="Scopes" value={provider.scopes.join(", ") || "—"} />
        <Row
          label="Claim mappings"
          value={
            Object.entries(provider.claim_mappings)
              .map(([k, v]) => `${k} → ${v}`)
              .join(", ") || "defaults"
          }
        />
        <Row label="Auto-provision" value={provider.auto_provision ? "Enabled" : "Disabled"} />
        <Row label="Default role" value={provider.default_role ?? "viewer (fallback)"} />
        {provider.ca_cert_path ? (
          <Row
            label="CA certificate"
            value={`${provider.ca_cert_path} (${provider.ca_cert_exists ? "found" : "missing"})`}
          />
        ) : null}
      </TabsContent>

      <TabsContent className="space-y-3 text-sm" value="endpoints">
        {provider.discovery_error ? (
          <p className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-destructive">
            <AlertCircle className="size-4 shrink-0" />
            {provider.discovery_error}
          </p>
        ) : provider.endpoints ? (
          <>
            <Row label="Issuer" value={provider.endpoints.issuer} />
            <Row label="Authorization endpoint" value={provider.endpoints.authorization_endpoint} />
            <Row label="Token endpoint" value={provider.endpoints.token_endpoint} />
            <Row label="JWKS URI" value={provider.endpoints.jwks_uri} />
            {provider.endpoints.userinfo_endpoint ? (
              <Row label="Userinfo endpoint" value={provider.endpoints.userinfo_endpoint} />
            ) : null}
            {provider.endpoints.end_session_endpoint ? (
              <Row label="End-session endpoint" value={provider.endpoints.end_session_endpoint} />
            ) : null}
          </>
        ) : (
          <p className="text-muted-foreground">Provider is disabled — endpoints not resolved.</p>
        )}
      </TabsContent>

      <TabsContent className="space-y-4" value="test-login">
        <div className="space-y-2">
          <Label htmlFor="redirect-uri">Redirect URI</Label>
          <Input
            id="redirect-uri"
            onChange={(e) => setRedirectUri(e.target.value)}
            value={redirectUri}
          />
        </div>

        <div className="flex items-center gap-2">
          <Checkbox
            checked={useOverrides}
            id="use-overrides"
            onCheckedChange={(checked) => setUseOverrides(checked === true)}
          />
          <Label htmlFor="use-overrides">Override default parameters for testing</Label>
        </div>

        {useOverrides ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="client-id">Client ID</Label>
              <Input id="client-id" onChange={(e) => setClientId(e.target.value)} value={clientId} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="response-type">Response type</Label>
              <Input
                id="response-type"
                onChange={(e) => setResponseType(e.target.value)}
                value={responseType}
              />
            </div>
            <div className="col-span-full space-y-2">
              <Label htmlFor="scopes">Scopes (space-separated)</Label>
              <Input id="scopes" onChange={(e) => setScopes(e.target.value)} value={scopes} />
            </div>
          </div>
        ) : null}

        {testError ? (
          <p className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            <AlertCircle className="size-4 shrink-0" />
            {testError}
          </p>
        ) : null}

        <Button disabled={isTesting || !provider.enabled} onClick={handleTestLogin}>
          {isTesting ? <Loader2 className="size-4 animate-spin" /> : null}
          Test Login
        </Button>
        {!provider.enabled ? (
          <p className="text-xs text-muted-foreground">Provider is disabled in config.</p>
        ) : null}
      </TabsContent>
    </Tabs>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5 border-b pb-2 last:border-b-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="break-all font-mono text-sm">{value}</span>
    </div>
  );
}

export function OidcTestPage() {
  const user = useAuthStore((state) => state.user);
  const canRead = hasPermission(user, "system.oidc", "read");
  const { data, isLoading, error } = useOidcDebugQuery({ enabled: canRead });
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(null);

  const selectedProvider = useMemo(
    () => data?.providers.find((p) => p.provider_id === selectedProviderId) ?? data?.providers[0],
    [data, selectedProviderId],
  );

  if (!canRead) {
    return (
      <div className="mx-auto w-full max-w-3xl space-y-4 p-8">
        <p className="text-sm text-muted-foreground">
          You don&apos;t have permission to view OIDC diagnostics.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6 p-8">
      <div className="flex items-center gap-3">
        <Link href="/tools">
          <Button size="icon" variant="ghost">
            <ArrowLeft className="size-4" />
          </Button>
        </Link>
        <div className="flex size-10 items-center justify-center rounded-lg bg-muted">
          <Shield className="size-5 text-muted-foreground" />
        </div>
        <div>
          <h1 className="text-xl font-semibold">OIDC Test Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Debug provider configuration and test SSO login flows.
          </p>
        </div>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="size-8 animate-spin text-muted-foreground" />
        </div>
      ) : null}

      {error ? (
        <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error instanceof Error ? error.message : "Failed to load OIDC status"}
        </p>
      ) : null}

      {data ? (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <StatusCard label="OIDC" ok={data.oidc_enabled} value={data.oidc_enabled ? "Enabled" : "Disabled"} />
            <StatusCard
              label="Providers"
              ok={data.providers.length > 0}
              value={String(data.providers.length)}
            />
            <StatusCard
              label="Traditional login"
              ok={data.allow_traditional_login}
              value={data.allow_traditional_login ? "Allowed" : "SSO-only"}
            />
          </div>

          {data.providers.length === 0 ? (
            <Card>
              <CardContent className="pt-6 text-sm text-muted-foreground">
                No providers configured. Add one to{" "}
                <code className="font-mono">config/oidc_providers.yaml</code>.
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-4 sm:grid-cols-[220px_1fr]">
              <div className="space-y-2">
                {data.providers.map((provider) => (
                  <button
                    className={`w-full rounded-lg border p-3 text-left text-sm transition-colors hover:border-primary/50 ${
                      selectedProvider?.provider_id === provider.provider_id
                        ? "border-primary bg-primary/5"
                        : ""
                    }`}
                    key={provider.provider_id}
                    onClick={() => setSelectedProviderId(provider.provider_id)}
                    type="button"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium">{provider.name}</span>
                      <Badge variant={provider.enabled ? "default" : "secondary"}>
                        {provider.enabled ? "enabled" : "disabled"}
                      </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground">{provider.provider_id}</p>
                  </button>
                ))}
              </div>

              <Card>
                <CardHeader>
                  <CardTitle className="text-base">{selectedProvider?.name}</CardTitle>
                </CardHeader>
                <CardContent>
                  {selectedProvider ? <ProviderDetail provider={selectedProvider} /> : null}
                </CardContent>
              </Card>
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
