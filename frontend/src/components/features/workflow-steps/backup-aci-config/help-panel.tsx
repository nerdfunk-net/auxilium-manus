"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/** Built-in Help tab content for Back Up ACI Config to Git. */
export function BackupAciConfigHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Reads the configuration (not the state) of every tenant and of the
          access policies from an APIC and writes it as JSON into a git
          repository, then commits (and optionally pushes). The files are stable
          between runs, so a git diff shows only what changed in the fabric.
          Nothing is written to ACI, and the devices of the workflow are not
          used.
        </p>
      </HelpSection>

      <HelpSection title="Files">
        <HelpExample>
          &lt;repository_subdirectory&gt;/tenants/&lt;tenant&gt;.json
          <br />
          &lt;repository_subdirectory&gt;/access-policies.json
        </HelpExample>
        <p>
          One fabric per folder: two fabrics in the same folder would overwrite
          each other. Tenant files come from{" "}
          <HelpCode>uni/tn-&lt;tenant&gt;</HelpCode>, the access policies from{" "}
          <HelpCode>uni/infra</HelpCode>. Fabric policies are not backed up.
        </p>
      </HelpSection>

      <HelpSection title="Settings">
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <HelpCode>aci_source_id</HelpCode>,{" "}
            <HelpCode>git_repository_id</HelpCode> — the APIC to read and the
            repository (Settings, Git Repositories) to write to.
          </li>
          <li>
            <HelpCode>tenants</HelpCode> — optional list; empty backs up every
            tenant. A name the APIC does not know fails the step.
          </li>
          <li>
            <HelpCode>include_access_policies</HelpCode> — also write{" "}
            <HelpCode>access-policies.json</HelpCode>.
          </li>
          <li>
            <HelpCode>commit</HelpCode> — commit the changed files; unchanged
            files give no commit. <HelpCode>push</HelpCode> pushes the commit
            and needs <HelpCode>commit</HelpCode>.
          </li>
          <li>
            <HelpCode>commit_message</HelpCode> —{" "}
            <HelpCode>{"{source_id}"}</HelpCode> becomes the ACI source id.{" "}
            <HelpCode>output_key</HelpCode> — name of the run metadata entry.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Result">
        <p>
          The run metadata entry{" "}
          <HelpCode>&lt;node id&gt;.&lt;output_key&gt;</HelpCode> lists the
          files written, the tenants, <HelpCode>committed</HelpCode>,{" "}
          <HelpCode>pushed</HelpCode>, <HelpCode>commit_sha</HelpCode> and{" "}
          <HelpCode>files_changed</HelpCode>. The <HelpCode>success</HelpCode>{" "}
          outcome is always taken; the <HelpCode>changed</HelpCode> outcome as
          well when files changed in the commit, so a workflow can notify on a
          change.
        </p>
        <p>
          <HelpCode>stale_files</HelpCode> lists tenant files in the repository
          whose tenant the APIC no longer has (only when all tenants are backed
          up). They are reported, not deleted.
        </p>
        <HelpWarning title="Read before you push">
          <p>
            If any tenant or the access policies cannot be read (a very large
            tenant can exceed what the APIC returns in one answer), the step
            fails and writes nothing, so the repository never holds a mix of old
            and new files. The export contains whatever the APIC returns for the
            configuration: review a repository before pushing it somewhere
            shared. Attributes that hold a secret (<HelpCode>key</HelpCode>,{" "}
            <HelpCode>password</HelpCode>, <HelpCode>authKey</HelpCode>,{" "}
            <HelpCode>community</HelpCode>, ...) are replaced by{" "}
            <HelpCode>&lt;secret removed&gt;</HelpCode> when the APIC returns a
            value for them, so these files are not a restore source for keys. If
            a failure happens after the first file was written, the step puts
            the files it touched back before it stops.
          </p>
          <p>
            A tenant whose name starts or ends with a dot or contains two dots
            in a row cannot be written to a file name safely: the step fails and
            names it.
          </p>
        </HelpWarning>
      </HelpSection>
    </div>
  );
}
