"use client";

import type { ReactNode } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface SecretManagerHelpDialogProps {
  open: boolean;
  onClose: () => void;
}

function Code({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">{children}</code>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold">{title}</h3>
      <div className="space-y-2 text-xs leading-5 text-muted-foreground">{children}</div>
    </div>
  );
}

function Example({ children }: { children: ReactNode }) {
  return (
    <pre className="m-0 overflow-x-auto whitespace-pre rounded-md border bg-muted/40 p-2 font-mono text-[11px] leading-5">
      {children}
    </pre>
  );
}

function Warning({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-warning-border bg-warning px-3 py-2 text-warning-foreground">
      <p className="font-medium">{title}</p>
      <div className="mt-1 space-y-1">{children}</div>
    </div>
  );
}

export function SecretManagerHelpDialog({ open, onClose }: SecretManagerHelpDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Configuring an OpenBao Secret Manager connection</DialogTitle>
          <DialogDescription>
            Each connection needs a credential (Settings → Credentials, type &quot;Basic Auth
            (Username + Password)&quot;) holding its AppRole Role ID and Secret ID, then a
            connection here referencing it.
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto pr-1">
            <Section title="Which authentication method">
              <p>
                This connection always authenticates with OpenBao&apos;s <strong>AppRole</strong>{" "}
                method — never <Code>userpass</Code>, <Code>ldap</Code>, <Code>cert</Code>, or a
                static token. There is no literal OpenBao user account: the credential&apos;s{" "}
                <strong>username</strong> field holds the AppRole <strong>Role ID</strong>, and its{" "}
                <strong>password</strong> field holds the AppRole <strong>Secret ID</strong>.
              </p>
            </Section>

            <Section title="1. Enable a KV v2 mount for network secrets">
              <p>
                Use a mount separate from the app&apos;s own credential vault (usually{" "}
                <Code>manus</Code>) — this connection needs its own policy scope.
              </p>
              <Example>{"bao secrets enable -path=manus-network -version=2 kv"}</Example>
            </Section>

            <Section title="2. Write a policy — read + write">
              <p>
                Workflow steps generate and rotate secrets at run time, so this policy is
                read+write, unlike the app&apos;s own read-only credential-vault policy.
              </p>
              <Example>{`cat > manus-network-secrets.hcl <<'EOF'
path "manus-network/data/*"     { capabilities = ["create", "read", "update"] }
path "manus-network/metadata/*" { capabilities = ["read"] }
EOF
bao policy write manus-network-secrets manus-network-secrets.hcl`}</Example>
            </Section>

            <Section title="3. Enable AppRole auth">
              <p>Skip this if AppRole is already enabled (e.g. from the credential-vault setup).</p>
              <Example>{"bao auth enable approle"}</Example>
            </Section>

            <Section title="4. Create the role, bound to that policy">
              <Example>{`bao write auth/approle/role/manus-network-secrets \\
  token_policies=manus-network-secrets token_period=3600 \\
  secret_id_num_uses=0 secret_id_ttl=0`}</Example>
            </Section>

            <Section title="5. Get the Role ID and generate a Secret ID">
              <Example>{`bao read -field=role_id auth/approle/role/manus-network-secrets/role-id
bao write -f -field=secret_id auth/approle/role/manus-network-secrets/secret-id`}</Example>
            </Section>

            <Section title="6. Add the credential and connection in Manus">
              <ol className="list-decimal space-y-1.5 pl-4">
                <li>
                  Settings → Credentials → Add credential, type &quot;Basic Auth (Username +
                  Password)&quot;, username = the Role ID, password = the Secret ID. Must be{" "}
                  <strong>global</strong>.
                </li>
                <li>
                  Back on this page, Add connection:{" "}
                  <Code>addr</Code> = your OpenBao URL, <Code>mount</Code> ={" "}
                  <Code>manus-network</Code> (matching step 1), then pick that credential.
                </li>
              </ol>
            </Section>

            <Warning title="Local dev container">
              <p>
                Using the repo&apos;s <Code>docker/openbao</Code> dev stack? Open a shell with{" "}
                <Code>docker compose exec openbao sh</Code> and run steps 1–5 there — same as the
                AppRole setup in <Code>docker/openbao/README.md</Code>, just a different
                mount/policy/role name.
              </p>
            </Warning>
        </div>
      </DialogContent>
    </Dialog>
  );
}
