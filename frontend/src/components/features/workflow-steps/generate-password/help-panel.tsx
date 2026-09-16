"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "@/components/features/workflow-steps/shared/step-help";

export function GeneratePasswordHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Generates a random password per device (stdlib{" "}
          <HelpCode>secrets</HelpCode>, never <HelpCode>random</HelpCode>) and
          seals it into the device&apos;s attribute bag for a later step in the
          same run — e.g. a config-push step reading{" "}
          <HelpCode>destination_path</HelpCode>.
        </p>
        <p>
          <span className="font-medium text-foreground">
            Unlike Secret Get / Secret Set / Secret Generate
          </span>
          , this step needs no Secret Manager connection and no Settings
          configuration — it is fully self-contained, local generation only.
        </p>
        <p>
          The generated value is never shown in the run UI, never logged, and
          never persisted in plaintext — only a sealed envelope reaches{" "}
          <HelpCode>destination_path</HelpCode>, redacted everywhere the run is
          displayed or stored.
        </p>
      </HelpSection>

      <HelpSection title="length">
        <p>
          Total password length. Must be between <HelpCode>8</HelpCode> and{" "}
          <HelpCode>256</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="min_digits / min_uppercase / min_lowercase / min_special">
        <p>
          Each is a guaranteed <span className="font-medium text-foreground">
            minimum
          </span>{" "}
          count from that character category. If the four minimums sum to less
          than <HelpCode>length</HelpCode>, the remaining characters are drawn
          randomly from whichever categories have a non-zero minimum, then the
          whole password is shuffled — the guaranteed characters are not
          predictably front-loaded.
        </p>
        <p>
          The special-character alphabet is fixed (not configurable):{" "}
          <HelpCode>!@#$%^&amp;*()-_=+[]{"{"}{"}"}:,.?</HelpCode>.
        </p>
      </HelpSection>

      <HelpSection title="destination_path">
        <p>
          Where the sealed password is written in the device&apos;s attribute
          bag, in <HelpCode>bag.field</HelpCode> form — so the very next step
          (e.g. a push-config step) can use it without any external lookup.
          Defaults to <HelpCode>generated_password.value</HelpCode>.
        </p>
      </HelpSection>

      <HelpWarning title="0 excludes a category entirely">
        <p>
          Setting a <HelpCode>min_*</HelpCode> field to <HelpCode>0</HelpCode>{" "}
          does not just mean &quot;no guaranteed minimum&quot; — it removes
          that character class from the password altogether, including from
          the random fill.
        </p>
      </HelpWarning>

      <HelpWarning title="Invalid combinations are rejected">
        <p>
          A config with all four minimums at <HelpCode>0</HelpCode> is
          invalid — there would be no character pool to draw from. The four
          minimums summing to more than <HelpCode>length</HelpCode> is also
          invalid; lowering <HelpCode>length</HelpCode> may require lowering
          the minimums too.
        </p>
      </HelpWarning>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — a
            password was generated and sealed for every device.
          </li>
        </ul>
        <p>
          No <HelpCode>failure</HelpCode> outcome exists: generation is pure
          local computation with nothing that can fail per device or per
          connection. A bad config fails the whole step before it runs, not
          with a per-device failure branch.
        </p>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Place this step after an inventory step.</li>
          <li>
            Set the four minimums so they sum to no more than{" "}
            <HelpCode>length</HelpCode>.
          </li>
          <li>
            Follow with a config-push step that reads{" "}
            <HelpCode>destination_path</HelpCode> to apply the new password to
            the device, in the same run.
          </li>
        </ol>
        <HelpExample>
          length: 16
          <br />
          min_digits: 2
          <br />
          min_uppercase: 2
          <br />
          min_lowercase: 2
          <br />
          min_special: 2
          <br />
          destination_path: generated_password.value
        </HelpExample>
      </HelpSection>
    </div>
  );
}
