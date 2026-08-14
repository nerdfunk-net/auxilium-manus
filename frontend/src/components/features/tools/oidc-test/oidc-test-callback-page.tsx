"use client";

import { AlertCircle, ArrowLeft, CheckCircle2, Loader2, XCircle } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

function decodeJwtPart(part: string): string {
  try {
    const normalized = part.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");
    return JSON.stringify(JSON.parse(atob(padded)), null, 2);
  } catch {
    return "(unable to decode)";
  }
}

function JwtPanel({ label, token }: { label: string; token: string }) {
  const parts = token.split(".");

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">{label}</p>
      {parts.length >= 2 ? (
        <div className="grid gap-2 sm:grid-cols-2">
          <div>
            <p className="mb-1 text-xs text-muted-foreground">Header</p>
            <pre className="overflow-x-auto rounded-md bg-muted p-2 text-xs">
              {decodeJwtPart(parts[0])}
            </pre>
          </div>
          <div>
            <p className="mb-1 text-xs text-muted-foreground">Payload</p>
            <pre className="overflow-x-auto rounded-md bg-muted p-2 text-xs">
              {decodeJwtPart(parts[1])}
            </pre>
          </div>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">Not a JWT — raw value shown below.</p>
      )}
      <pre className="overflow-x-auto rounded-md bg-muted p-2 text-xs break-all whitespace-pre-wrap">
        {token}
      </pre>
    </div>
  );
}

function OidcTestCallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [isExchanging, setIsExchanging] = useState(false);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");

  const code = searchParams.get("code");
  const state = searchParams.get("state");
  const providerError = searchParams.get("error");
  const storedState = typeof window !== "undefined" ? sessionStorage.getItem("oidc_state") : null;
  const stateValid = Boolean(state) && state === storedState;
  const providerId = state?.includes(":") ? state.split(":", 2)[0] : null;

  const handleExchange = async () => {
    if (!code || !state || !providerId) return;

    setIsExchanging(true);
    setError("");
    setResult(null);

    try {
      const response = await fetch(`/api/proxy/auth/oidc/${providerId}/callback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, state }),
      });

      const payload = (await response.json()) as Record<string, unknown>;
      if (!response.ok) {
        throw new Error((payload.message as string) || "Token exchange failed");
      }

      setResult(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Token exchange failed");
    } finally {
      setIsExchanging(false);
    }
  };

  return (
    <main className="mx-auto w-full max-w-2xl space-y-6 p-8">
      <div className="flex items-center gap-3">
        <Link href="/tools/oidc-test">
          <Button size="icon" variant="ghost">
            <ArrowLeft className="size-4" />
          </Button>
        </Link>
        <div>
          <h1 className="text-xl font-semibold">OIDC Callback Debugger</h1>
          <p className="text-sm text-muted-foreground">
            Inspects the redirect from the provider and lets you manually exchange the code.
          </p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Redirect parameters</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">provider_id</span>
            <span className="font-mono">{providerId ?? "—"}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">code</span>
            <span className="max-w-[70%] truncate font-mono">{code ?? "—"}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">state</span>
            <div className="flex items-center gap-2">
              <span className="max-w-[50%] truncate font-mono">{state ?? "—"}</span>
              <Badge variant={stateValid ? "default" : "destructive"}>
                {stateValid ? "valid" : "invalid"}
              </Badge>
            </div>
          </div>
          {providerError ? (
            <p className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-destructive">
              <AlertCircle className="size-4 shrink-0" />
              Provider returned an error: {providerError}
            </p>
          ) : null}
        </CardContent>
      </Card>

      <Button disabled={!code || !state || isExchanging} onClick={handleExchange}>
        {isExchanging ? <Loader2 className="size-4 animate-spin" /> : null}
        Exchange Code for Tokens
      </Button>

      {error ? (
        <p className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          <XCircle className="size-4 shrink-0" />
          {error}
        </p>
      ) : null}

      {result ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              {result.status === "approval_pending" ? (
                <>
                  <AlertCircle className="size-4 text-warning-foreground" />
                  Approval pending
                </>
              ) : (
                <>
                  <CheckCircle2 className="size-4 text-success-foreground" />
                  Login succeeded
                </>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <pre className="overflow-x-auto rounded-md bg-muted p-2 text-xs">
              {JSON.stringify(result, null, 2)}
            </pre>
            {typeof result.access_token === "string" ? (
              <JwtPanel label="Application JWT (access_token)" token={result.access_token} />
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      <Button onClick={() => router.push("/tools/oidc-test")} variant="outline">
        Back to Test Dashboard
      </Button>
    </main>
  );
}

export function OidcTestCallbackPage() {
  return (
    <Suspense fallback={null}>
      <OidcTestCallbackContent />
    </Suspense>
  );
}
