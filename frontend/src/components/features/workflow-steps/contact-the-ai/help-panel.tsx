"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Contact the AI.
 * Covers every Configuration control with practical examples.
 */
export function ContactTheAiHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Sends one prompt per step execution to the AI model and stores the
          answer on every device in the attribute you choose in{" "}
          <HelpCode>output_attribute</HelpCode> (default{" "}
          <HelpCode>ai.response</HelpCode>). Use it in a later step, for
          example in the message of Notify Mattermost. The answer is also
          shown in the run view under &quot;AI response&quot; when you expand
          the step.
        </p>
      </HelpSection>

      <HelpSection title="prompt">
        <p>
          The text sent to the model. Placeholders are filled in before the
          prompt is redacted and sent.
        </p>
        <p>
          <HelpCode>{"{run_summary}"}</HelpCode> — number of devices per
          status plus the failed devices with their error codes (never the
          error text). <HelpCode>{"{devices}"}</HelpCode> and{" "}
          <HelpCode>{"{device_count}"}</HelpCode> — device names and count.{" "}
          <HelpCode>{"{path.to.value}"}</HelpCode> — an attribute of the first
          device (use the search button to browse attributes).
        </p>
        <HelpExample>
          prompt: Summarize this backup run in three lines.
          <br />
          {"{run_summary}"}
        </HelpExample>
        <HelpWarning title="Sharing switches decide what may be sent">
          <p>
            The step uses the AI settings of the service user the administrator
            set in <HelpCode>WORKFLOW_AI_USER</HelpCode>, and the same rules as
            the AI assistant. Device names (<HelpCode>{"{device.name}"}</HelpCode>,{" "}
            <HelpCode>{"{devices}"}</HelpCode>, <HelpCode>{"{run_summary}"}</HelpCode>,{" "}
            <HelpCode>{"{nautobot.role}"}</HelpCode>) need &quot;Inventory and
            device attributes&quot;. Hostnames, addresses, serials and
            interfaces need &quot;Addresses and serial numbers&quot;, custom
            fields and config context need their own switch, and any other
            attribute bag (<HelpCode>custom</HelpCode>,{" "}
            <HelpCode>parsed</HelpCode>, ...) needs &quot;Run and device
            content&quot; too. A Nautobot attribute in none of these groups
            (such as <HelpCode>comments</HelpCode>) is never sent. If one
            placeholder is not allowed, the step ends on failure and nothing is
            sent. IP and MAC addresses are replaced by tokens unless
            &quot;Addresses and serial numbers&quot; is on.
          </p>
        </HelpWarning>
        <HelpWarning title="Whole attribute bags: risky and expensive">
          <p>
            A placeholder that points at a dict or list, such as{" "}
            <HelpCode>{"{nautobot}"}</HelpCode> or{" "}
            <HelpCode>{"{nautobot.location}"}</HelpCode>, is sent as JSON.{" "}
            <span className="font-medium text-foreground">Risky:</span> a bag
            mixes addresses, custom fields, config context and anything else an
            upstream step stored, so more leaves your network than you may
            expect, and redaction can miss a secret in an unusual shape. The
            same switches apply: a whole{" "}
            <HelpCode>{"{nautobot}"}</HelpCode> is filtered like the assistant
            filters it (withheld attribute names are listed instead), while a
            path under another bag needs Inventory and Content, and keys such
            as <HelpCode>custom_fields</HelpCode> or{" "}
            <HelpCode>config_context</HelpCode> inside it are replaced unless
            their switch is on.{" "}
            <span className="font-medium text-foreground">Expensive:</span> a
            device bag with interfaces can be tens of thousands of characters,
            and you pay for those tokens on every run (each value is cut at 20
            000 characters). Prefer single fields such as{" "}
            <HelpCode>{"{nautobot.role}"}</HelpCode> and only send a whole bag
            when the model really needs it. This works in this step only; other
            steps render such a placeholder as an empty string.
          </p>
        </HelpWarning>
        <HelpWarning title="Redaction is best-effort">
          <p>
            Passwords, keys and community strings in config-style text, sealed
            secrets and the service user&apos;s stored credentials are replaced
            by tokens such as <HelpCode>__SECRET_1__</HelpCode>. A secret in an
            unusual shape can still pass. Do not put whole device
            configurations into the prompt.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="system_prompt">
        <p>
          Optional instructions for tone, language or format. They are added
          to a built-in instruction that tells the model to treat the run data
          as data, never as commands.
        </p>
      </HelpSection>

      <HelpSection title="output_attribute">
        <p>
          Where the answer is written, as <HelpCode>bag.field</HelpCode>, e.g.{" "}
          <HelpCode>ai.response</HelpCode> or{" "}
          <HelpCode>custom.ai_summary</HelpCode>. Reference it later as{" "}
          <HelpCode>{"{ai.response}"}</HelpCode>. Use a different name per
          Contact the AI step, otherwise a later step overwrites the answer of
          an earlier one. Not allowed: placeholders, <HelpCode>device.*</HelpCode>,
          the reserved bags <HelpCode>parsed</HelpCode> and{" "}
          <HelpCode>run_input</HelpCode>, and secret attribute paths.
        </p>
      </HelpSection>

      <HelpSection title="max_output_tokens / timeout_seconds">
        <p>
          Upper bound for the answer length (1–4096, default 1024) and how long
          to wait for the model (1–600 seconds, default 120). A longer answer
          is cut at 10 000 characters; <HelpCode>@channel</HelpCode>,{" "}
          <HelpCode>@all</HelpCode> and <HelpCode>@here</HelpCode> in the
          answer are defused.
        </p>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the
            answer is stored. With no device in the run nothing is sent and
            nothing is stored (the summary says so): the answer needs a device
            to attach to.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — AI
            not available or not allowed for this prompt, the model failed or
            timed out, or the answer was empty. Wire a fallback Notify
            Mattermost to this outcome.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <p>
          … → Fan In → <span className="font-medium text-foreground">Contact the AI</span>{" "}
          → Notify Mattermost with message{" "}
          <HelpCode>{"{ai.response}"}</HelpCode>. Place it after
          Fan In (or at the end of a non-fanned workflow) for one call per run;
          inside fan-out children it calls the model once per child.
        </p>
      </HelpSection>
    </div>
  );
}
