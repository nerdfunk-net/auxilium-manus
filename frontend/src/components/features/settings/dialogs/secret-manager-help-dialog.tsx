"use client";

import type { ReactNode } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

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
          <DialogTitle>Configuring a Secret Manager backend</DialogTitle>
          <DialogDescription>
            Each connection needs a credential (Settings → Credentials, type &quot;Basic Auth
            (Username + Password)&quot;) holding that backend&apos;s own auth material, then a
            connection here referencing it.
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="openbao" className="flex min-h-0 flex-1 flex-col">
          <TabsList className="w-fit">
            <TabsTrigger value="openbao">OpenBao</TabsTrigger>
            <TabsTrigger value="infisical">Infisical</TabsTrigger>
          </TabsList>

          <TabsContent value="openbao" className="min-h-0 flex-1 space-y-5 overflow-y-auto pr-1">
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
                  Back on this page, Add connection: backend <strong>OpenBao</strong>,{" "}
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
          </TabsContent>

          <TabsContent
            value="infisical"
            className="min-h-0 flex-1 space-y-5 overflow-y-auto pr-1"
          >
            <Section title="Which authentication method">
              <p>
                This connection always authenticates with Infisical&apos;s{" "}
                <strong>Universal Auth</strong> — a machine identity&apos;s{" "}
                <strong>Client ID</strong> / <strong>Client Secret</strong> pair. The
                credential&apos;s username field holds the Client ID, and its password field
                holds the Client Secret.
              </p>
            </Section>

            <Section title="1. Create a machine identity">
              <ol className="list-decimal space-y-1.5 pl-4">
                <li>
                  In Infisical, go to <strong>Organization → Access Control → Machine
                  Identities</strong> and select <strong>Create</strong>.
                </li>
                <li>Pick an organization role and give the identity a name (e.g. &quot;manus&quot;).</li>
                <li>Universal Auth is the default authentication method on a new identity.</li>
              </ol>
            </Section>

            <Section title="2. Generate a Client Secret">
              <p>
                On the identity&apos;s page, select <strong>Add Client Secret</strong> (set a TTL
                and/or max uses if you want it to expire) and generate it. The Client Secret is
                shown once — copy it immediately alongside the Client ID shown on the same page.
              </p>
            </Section>

            <Section title="3. Add the identity to your project">
              <ol className="list-decimal space-y-1.5 pl-4">
                <li>
                  Open the target project → <strong>Access Control → Machine Identities</strong> →{" "}
                  <strong>Add Machine Identity to Project</strong>.
                </li>
                <li>Assign the identity you created and give it a project role with read/write access to secrets.</li>
              </ol>
            </Section>

            <Section title="4. Get the Project ID and environment slug">
              <p>
                Both are on the project&apos;s <strong>Settings</strong> page — the Project ID is
                shown directly; the environment slug (e.g. <Code>dev</Code>, <Code>prod</Code>) is
                listed under the project&apos;s environments, not the display name.
              </p>
            </Section>

            <Section title="5. Add the credential and connection in Manus">
              <ol className="list-decimal space-y-1.5 pl-4">
                <li>
                  Settings → Credentials → Add credential, type &quot;Basic Auth (Username +
                  Password)&quot;, username = Client ID, password = Client Secret. Must be{" "}
                  <strong>global</strong>.
                </li>
                <li>
                  Back on this page, Add connection: backend <strong>Infisical</strong>,{" "}
                  <Code>site_url</Code> (<Code>https://app.infisical.com</Code> for cloud, or your
                  self-hosted URL), <Code>project_id</Code>, <Code>environment</Code>, then pick
                  that credential.
                </li>
              </ol>
            </Section>

            <Warning title="Verify against your Infisical version">
              <p>
                Menu names above match Infisical&apos;s documented UI at the time this page was
                written — self-hosted deployments and future Infisical versions may differ
                slightly. Retrieving a <em>previous</em> version of a secret (the &quot;what was
                the old key&quot; use case) is not yet verified to work reliably against a live
                Infisical instance — see doc/SECRET_MANAGER_INTEGRATION.md. The repo&apos;s{" "}
                <Code>docker/infisical</Code> stack is the fastest way to test this locally.
              </p>
            </Warning>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
