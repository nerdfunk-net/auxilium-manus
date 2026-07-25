"use client";

import { AlertCircle, Boxes, CheckCircle2, Loader2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/lib/auth-store";
import type { AuthUser } from "@/lib/auth";

type CallbackStatus = "processing" | "success" | "error";

function OidcCallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const setUser = useAuthStore((state) => state.setUser);
  const [status, setStatus] = useState<CallbackStatus>("processing");
  const [error, setError] = useState("");

  useEffect(() => {
    const handleCallback = async () => {
      const code = searchParams.get("code");
      const state = searchParams.get("state");
      const providerError = searchParams.get("error");
      const providerErrorDescription = searchParams.get("error_description");

      if (providerError) {
        setError(providerErrorDescription || providerError);
        setStatus("error");
        return;
      }

      if (!code || !state) {
        setError("No authorization code received");
        setStatus("error");
        return;
      }

      const storedState = sessionStorage.getItem("oidc_state");
      sessionStorage.removeItem("oidc_state");

      if (storedState && state !== storedState) {
        setError("Invalid state parameter — possible CSRF attempt");
        setStatus("error");
        return;
      }

      const providerId = state.includes(":") ? state.split(":", 2)[0] : null;
      if (!providerId) {
        setError("Invalid state parameter");
        setStatus("error");
        return;
      }

      try {
        const response = await fetch(`/api/auth/oidc/${providerId}/callback`, {
          body: JSON.stringify({ code, state }),
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          method: "POST",
        });

        const payload = (await response.json()) as {
          status?: string;
          username?: string;
          email?: string;
          oidc_provider?: string;
          message?: string;
          user?: AuthUser;
        };

        if (!response.ok) {
          throw new Error(payload.message || "Authentication failed");
        }

        if (payload.status === "approval_pending") {
          const params = new URLSearchParams({
            provider: payload.oidc_provider || providerId,
            username: payload.username || "",
            ...(payload.email ? { email: payload.email } : {}),
          });
          router.replace(`/login/approval-pending?${params.toString()}`);
          return;
        }

        if (!payload.user) {
          throw new Error("Invalid authentication response");
        }

        setUser(payload.user);
        setStatus("success");
        router.replace("/workflows");
        router.refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Authentication failed");
        setStatus("error");
      }
    };

    handleCallback();
    // Only run once on mount — searchParams/router/setUser are stable for this page's lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-10 text-foreground">
      <section className="w-full max-w-md rounded-2xl border bg-card p-8 shadow-sm">
        <div className="mb-8 flex items-center gap-3">
          <div className="flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <Boxes className="size-6" />
          </div>
          <div>
            <h1 className="text-lg font-semibold">Auxilium Manus</h1>
            <p className="text-sm text-muted-foreground">
              {status === "processing" && "Completing sign-in..."}
              {status === "success" && "Signed in successfully"}
              {status === "error" && "Sign-in failed"}
            </p>
          </div>
        </div>

        {status === "processing" ? (
          <div className="flex justify-center py-8">
            <Loader2 className="size-10 animate-spin text-muted-foreground" />
          </div>
        ) : null}

        {status === "success" ? (
          <div className="flex justify-center py-8">
            <CheckCircle2 className="size-10 text-primary" />
          </div>
        ) : null}

        {status === "error" ? (
          <div className="space-y-4">
            <p
              className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              role="alert"
            >
              <AlertCircle className="size-4 shrink-0" />
              <span>{error}</span>
            </p>
            <Button className="w-full" onClick={() => router.replace("/login")} type="button">
              Return to login
            </Button>
          </div>
        ) : null}
      </section>
    </main>
  );
}

export function OidcCallbackPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center bg-background px-4 py-10">
          <Loader2 className="size-10 animate-spin text-muted-foreground" />
        </main>
      }
    >
      <OidcCallbackContent />
    </Suspense>
  );
}
