"use client";

import {
  Boxes,
  Building2,
  FlaskConical,
  Globe,
  KeyRound,
  Loader2,
  LogIn,
  Shield,
  Users,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/lib/auth-store";

interface OidcProvider {
  provider_id: string;
  name: string;
  description?: string | null;
  icon?: string | null;
  display_order: number;
}

interface OidcProvidersResponse {
  providers: OidcProvider[];
  allow_traditional_login: boolean;
}

const PROVIDER_ICONS: Record<string, typeof LogIn> = {
  building: Building2,
  flask: FlaskConical,
  users: Users,
  shield: Shield,
  key: KeyRound,
  globe: Globe,
};

function getProviderIcon(icon?: string | null) {
  return (icon && PROVIDER_ICONS[icon]) || LogIn;
}

export function LoginPage() {
  const router = useRouter();
  const login = useAuthStore((state) => state.login);
  const isLoading = useAuthStore((state) => state.isLoading);
  const authError = useAuthStore((state) => state.error);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [oidcProviders, setOidcProviders] = useState<OidcProvider[]>([]);
  const [allowTraditionalLogin, setAllowTraditionalLogin] = useState(true);
  const [oidcError, setOidcError] = useState("");
  const [oidcLoadingProvider, setOidcLoadingProvider] = useState<string | null>(null);
  const [notice] = useState(() => {
    if (typeof window === "undefined") return "";
    const reason = new URLSearchParams(window.location.search).get("reason");
    if (reason === "idle") return "You were signed out due to inactivity.";
    if (reason === "expired") return "Your session expired. Please sign in again.";
    return "";
  });

  useEffect(() => {
    let cancelled = false;

    fetch("/api/proxy/auth/oidc/providers")
      .then((response) => (response.ok ? (response.json() as Promise<OidcProvidersResponse>) : null))
      .then((data) => {
        if (!data || cancelled) return;
        setOidcProviders(data.providers);
        setAllowTraditionalLogin(data.allow_traditional_login);
      })
      .catch(() => {
        // OIDC is optional — silently fall back to traditional login only.
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();

      try {
        await login({ username, password });
        router.replace("/workflows");
        router.refresh();
      } catch {
        // The auth store exposes the user-facing error message.
      }
    },
    [login, password, router, username],
  );

  const handleOidcLogin = useCallback(async (providerId: string) => {
    setOidcLoadingProvider(providerId);
    setOidcError("");

    try {
      const redirectUri = `${window.location.origin}/login/callback`;
      const response = await fetch(
        `/api/proxy/auth/oidc/${providerId}/login?redirect_uri=${encodeURIComponent(redirectUri)}`,
      );

      if (!response.ok) {
        throw new Error(`Failed to initiate SSO login with ${providerId}`);
      }

      const data = (await response.json()) as { authorization_url: string; state: string };
      sessionStorage.setItem("oidc_state", data.state);
      window.location.assign(data.authorization_url);
    } catch (err) {
      setOidcError(err instanceof Error ? err.message : "SSO login failed");
      setOidcLoadingProvider(null);
    }
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
              Sign in to the NetDevOps workflow builder.
            </p>
          </div>
        </div>

        {notice ? (
          <p
            className="mb-5 rounded-lg border border-border bg-muted px-3 py-2 text-sm text-muted-foreground"
            role="status"
          >
            {notice}
          </p>
        ) : null}

        {oidcError ? (
          <p
            className="mb-5 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            role="alert"
          >
            {oidcError}
          </p>
        ) : null}

        {!allowTraditionalLogin && oidcProviders.length > 0 ? (
          <div className="space-y-3">
            <p className="text-center text-sm text-muted-foreground">
              Choose how you&apos;d like to sign in
            </p>
            {oidcProviders.map((provider) => {
              const Icon = getProviderIcon(provider.icon);
              const isLoadingThis = oidcLoadingProvider === provider.provider_id;
              return (
                <Button
                  className="h-auto w-full justify-start gap-3 py-3"
                  disabled={oidcLoadingProvider !== null}
                  key={provider.provider_id}
                  onClick={() => handleOidcLogin(provider.provider_id)}
                  type="button"
                  variant="outline"
                >
                  {isLoadingThis ? <Loader2 className="size-4 animate-spin" /> : <Icon className="size-4" />}
                  <div className="flex flex-col items-start text-left">
                    <span className="font-medium">{provider.name}</span>
                    {provider.description ? (
                      <span className="text-xs text-muted-foreground">{provider.description}</span>
                    ) : null}
                  </div>
                </Button>
              );
            })}
          </div>
        ) : (
          <form className="space-y-5" onSubmit={handleSubmit}>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="username">
                Username
              </label>
              <input
                autoComplete="username"
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                id="username"
                maxLength={255}
                onChange={(event) => setUsername(event.target.value)}
                required
                type="text"
                value={username}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="password">
                Password
              </label>
              <input
                autoComplete="current-password"
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                id="password"
                maxLength={128}
                onChange={(event) => setPassword(event.target.value)}
                required
                type="password"
                value={password}
              />
            </div>

            {authError ? (
              <p
                className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
                role="alert"
              >
                {authError}
              </p>
            ) : null}

            <Button className="w-full" disabled={isLoading} type="submit">
              {isLoading ? <Loader2 className="size-4 animate-spin" /> : <LogIn className="size-4" />}
              Sign in
            </Button>

            {oidcProviders.length > 0 ? (
              <>
                <div className="relative">
                  <div className="absolute inset-0 flex items-center">
                    <span className="w-full border-t" />
                  </div>
                  <div className="relative flex justify-center text-xs uppercase">
                    <span className="bg-card px-2 text-muted-foreground">Or continue with</span>
                  </div>
                </div>

                {oidcProviders.map((provider) => {
                  const Icon = getProviderIcon(provider.icon);
                  const isLoadingThis = oidcLoadingProvider === provider.provider_id;
                  return (
                    <Button
                      className="h-auto w-full justify-start gap-3 py-3"
                      disabled={oidcLoadingProvider !== null}
                      key={provider.provider_id}
                      onClick={() => handleOidcLogin(provider.provider_id)}
                      type="button"
                      variant="outline"
                    >
                      {isLoadingThis ? (
                        <Loader2 className="size-4 animate-spin" />
                      ) : (
                        <Icon className="size-4" />
                      )}
                      <div className="flex flex-col items-start text-left">
                        <span className="font-medium">{provider.name}</span>
                        {provider.description ? (
                          <span className="text-xs text-muted-foreground">
                            {provider.description}
                          </span>
                        ) : null}
                      </div>
                    </Button>
                  );
                })}
              </>
            ) : null}
          </form>
        )}
      </section>
    </main>
  );
}
