"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "@/components/features/workflow-steps/shared/step-help";

export function DecryptAttributeHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Reads an encrypted attribute value (a ciphertext token produced by{" "}
          <span className="font-medium text-foreground">Encrypt Attribute</span> or
          an equivalent tool), decrypts it with a shared secret from the credential
          vault, and writes the cleartext to <HelpCode>destination_path</HelpCode>{" "}
          as a <em>sealed</em> secret.
        </p>
        <p>
          A sealed value is redacted everywhere a run is persisted or displayed
          (step results, <span className="font-medium text-foreground">Log
          Attributes</span> dumps, logs) and is revealed in memory only to trusted
          consumers such as <span className="font-medium text-foreground">Render
          Jinja Template</span>. Typical chain:{" "}
          <HelpCode>Get Nautobot Attributes → Decrypt Attribute → Render Jinja
          Template → Deploy Rendered Template</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="source_path">
        <p>
          Dot path to the ciphertext token — for example{" "}
          <HelpCode>nautobot.config_context.secrets.enable_password</HelpCode> when
          the encrypted password lives in a device&apos;s Nautobot config context.
        </p>
        <p>
          <strong className="text-foreground">Reaching into an array.</strong> When
          the value sits inside a list, use a{" "}
          <HelpCode>key[field=value]</HelpCode> filter segment — it selects the{" "}
          <em>first</em> list entry whose <HelpCode>field</HelpCode> equals{" "}
          <HelpCode>value</HelpCode>, then keeps traversing. Numeric indexing
          (<HelpCode>credentials[1]</HelpCode>) is <em>not</em> supported. Given a
          config context like:
        </p>
        <HelpExample>
          {`"credentials": [
  { "username": "admin", "privilege": 15,
    "password": "AM1.aes-256-gcm.<salt>.<nonce>.<ciphertext>" },
  { "username": "noc",   "privilege": 15,
    "password": "AM1.aes-256-gcm.<salt>.<nonce>.<ciphertext>" }
]`}
        </HelpExample>
        <p>
          reach the <HelpCode>noc</HelpCode> entry&apos;s password with:
        </p>
        <HelpExample>
          nautobot.config_context.credentials[username=noc].password
        </HelpExample>
        <p>
          Pick a field that is unique in the list —{" "}
          <HelpCode>[privilege=15]</HelpCode> above would match both entries and
          resolve to the first. To decrypt <em>every</em> entry when the count and
          usernames are not known ahead of time, use <strong>list mode</strong>{" "}
          (below) instead of a filter.
        </p>
      </HelpSection>

      <HelpSection title="item_field — list mode">
        <p>
          Leave <HelpCode>item_field</HelpCode> blank for a single value. Set it to
          a field name to switch to <strong>list mode</strong>:{" "}
          <HelpCode>source_path</HelpCode> must resolve to a list, and{" "}
          <HelpCode>item_field</HelpCode> is decrypted on <em>every</em> entry that
          carries a token — the list is rewritten with each of those fields sealed.
          Entries without the field, or with a non-token value, are left untouched.
        </p>
        <HelpExample>
          source_path: nautobot.config_context.credentials
          <br />
          item_field: password
          <br />
          destination_path: (blank — rewrites the list in place)
        </HelpExample>
        <p>
          A Jinja template then loops the array — sealed values are unwrapped
          per-iteration, so counts and usernames do not matter:
        </p>
        <HelpExample>
          {`{% for c in nautobot.config_context.credentials %}
username {{ c.username }} privilege {{ c.privilege }} secret 9 {{ c.password }}
{% endfor %}`}
        </HelpExample>
        <p>
          If any one entry fails to decrypt, the whole device is routed to{" "}
          <HelpCode>failure</HelpCode> and nothing is written (the reason names the
          entry&apos;s <HelpCode>username</HelpCode>). Set{" "}
          <HelpCode>destination_path</HelpCode> to a{" "}
          <HelpCode>bag.field</HelpCode> path to write the transformed list
          somewhere other than in place.
        </p>
      </HelpSection>

      <HelpWarning title="This step is not a Cisco password decoder">
        <p>
          It only decrypts the portable{" "}
          <HelpCode>AM1.&lt;algorithm&gt;.&lt;salt&gt;.&lt;nonce&gt;.&lt;ciphertext&gt;</HelpCode>{" "}
          token that <span className="font-medium text-foreground">Encrypt
          Attribute</span> produces (or another tool emitting that exact format).
          A device-side Cisco secret — <HelpCode>$9$…</HelpCode> (type-9 / scrypt),{" "}
          <HelpCode>$8$…</HelpCode>, <HelpCode>$14$…</HelpCode>, or a type-7
          string — is a one-way hash or a proprietary scheme and cannot be
          recovered here (or anywhere). Feed those to the device as-is. A
          plaintext value is likewise not a token — pointing at one routes the
          device to <HelpCode>failure</HelpCode> with a{" "}
          <HelpCode>malformed token</HelpCode> reason.
        </p>
      </HelpWarning>

      <HelpSection title="destination_path">
        <p>
          Where the decrypted value is written, sealed, in{" "}
          <HelpCode>bag.field</HelpCode> form (e.g.{" "}
          <HelpCode>secrets.enable_password</HelpCode>). A Jinja template then
          reads it as <HelpCode>{"{{ secrets.enable_password }}"}</HelpCode>.{" "}
          <HelpCode>parsed.*</HelpCode> and <HelpCode>run_input.*</HelpCode> are
          reserved and rejected. Required in scalar mode; optional in list mode
          (blank rewrites the source list in place).
        </p>
      </HelpSection>

      <HelpSection title="credential_reference">
        <p>
          Name of a <span className="font-medium text-foreground">Shared Secret</span>{" "}
          credential from Settings → Credential vault. Only the name is stored in
          the workflow.
        </p>
      </HelpSection>

      <HelpSection title="algorithm">
        <p>
          Leave as <HelpCode>Use credential default</HelpCode> — the token carries
          its own algorithm header, so decryption works without setting anything.
          Pick a value explicitly only to enforce that the token was produced with
          that algorithm.
        </p>
      </HelpSection>

      <HelpSection title="Test Decryption">
        <p>
          Opens a modal that decrypts a ciphertext token with a shared secret you
          type in and shows the recovered value, so you can confirm a stored value
          before wiring a full workflow. Nothing is read from or written to the
          vault.
        </p>
      </HelpSection>

      <HelpWarning title="A bad decrypt does not stop the run">
        <p>
          If the shared secret does not match, or the token is malformed, that
          device is routed to the <HelpCode>failure</HelpCode> outcome with a
          recorded reason instead of failing the whole run. AES-GCM is
          authenticated, so a wrong secret can only fail — it can never return a
          nonsense value.
        </p>
        <p>
          Wire <HelpCode>failure</HelpCode> to a{" "}
          <span className="font-medium text-foreground">Notify Mattermost</span> /{" "}
          <span className="font-medium text-foreground">Notify on Error</span> step
          — its <HelpCode>{"{error.message}"}</HelpCode>,{" "}
          <HelpCode>{"{error.code}"}</HelpCode> (<HelpCode>decryption_failed</HelpCode>
          ), <HelpCode>{"{error.step_id}"}</HelpCode> and{" "}
          <HelpCode>{"{error.node_id}"}</HelpCode> placeholders describe what went
          wrong.
        </p>
      </HelpWarning>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the
            device was decrypted, or skipped because <HelpCode>source_path</HelpCode>{" "}
            resolved to nothing.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> —
            decryption failed for that device (wrong shared secret, corrupted or
            truncated token, algorithm mismatch), or in list mode{" "}
            <HelpCode>source_path</HelpCode> did not resolve to a list
            (<HelpCode>not_a_list</HelpCode>). The device carries a{" "}
            <HelpCode>DeviceError</HelpCode> with the reason and nothing is written.
          </li>
        </ul>
        <p>
          Genuine configuration mistakes — a missing path or credential, an
          unknown algorithm override — still fail the step outright rather than
          routing to <HelpCode>failure</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Create a Shared Secret credential matching the one used to encrypt.</li>
          <li>
            Point <HelpCode>source_path</HelpCode> at the encrypted value and{" "}
            <HelpCode>destination_path</HelpCode> at a name your template expects.
          </li>
          <li>Render and deploy using the sealed value.</li>
        </ol>
        <HelpExample>
          source_path: nautobot.config_context.secrets.enable_password
          <br />
          destination_path: secrets.enable_password
        </HelpExample>
      </HelpSection>
    </div>
  );
}
