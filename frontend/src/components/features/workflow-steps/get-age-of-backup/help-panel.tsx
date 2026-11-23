"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/**
 * Built-in Help tab content for Get Age of Backup.
 * Covers every Configuration control with practical examples.
 */
export function GetAgeOfBackupHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Finds the backup file of each device in a git repository and reports how many days ago
          it last <span className="font-medium text-foreground">changed</span>: the date of the
          newest git commit that touched the file. The age is written as a number into a separate
          attribute bag, so a later step (Route on Attribute, Compare Data, Notify, …) can
          compare it, e.g. to find devices whose backup is older than 30 days.
        </p>
        <p>
          Place it after an inventory step so each device has a name to resolve the path against.
          The step only reads: it never writes to git or to a device.
        </p>
      </HelpSection>

      <HelpWarning title="A git date is the last change, not the last backup">
        <p>
          The backup workflow commits a file only when its content differs from the committed
          one. A stable device whose config has not changed for 90 days is backed up every night
          and still shows <HelpCode>age_days: 90</HelpCode>. To see when the backup last ran, use
          the marker (below). Configs with a changing line, such as a timestamp comment, produce
          a new commit on every run and look fresh.
        </p>
      </HelpWarning>

      <HelpSection title="Repository">
        <p>
          <HelpCode>git_repository_id</HelpCode> selects the repository the backups are pushed
          to. It is refreshed (pulled) before reading, so the newest commits count.{" "}
          <HelpCode>allow_stale_repository</HelpCode> lets the step use the last local copy when
          the pull fails (expired token, offline). Leave it off if an age must never come from
          an outdated copy.
        </p>
      </HelpSection>

      <HelpSection title="Path template">
        <p>
          <HelpCode>path_template</HelpCode> is the relative path of the backup file, resolved
          per device. Use the same template the backup workflow stores its files under.
        </p>
        <HelpExample>
          path_template: {"{device.name}"}.cfg
          <br />
          <span className="text-muted-foreground">→ router1.cfg</span>
        </HelpExample>
        <HelpExample>
          path_template: {"{nautobot.location.name}"}/{"{device.name}"}.cfg
          <br />
          <span className="text-muted-foreground">→ DC1/router1.cfg</span>
        </HelpExample>
        <p>
          A device fails when a placeholder is empty, the path leaves the repository or crosses a
          symbolic link, the file does not exist, or the file has no commit yet.
        </p>
      </HelpSection>

      <HelpSection title="Result bag">
        <p>
          <HelpCode>output_bag</HelpCode> (default <HelpCode>backup_age</HelpCode>) names the
          attribute bag. Letters, digits and underscores only;{" "}
          <HelpCode>parsed</HelpCode>, <HelpCode>run_input</HelpCode> and device field names
          such as <HelpCode>name</HelpCode> are not allowed.
        </p>
        <ul className="list-disc space-y-1.5 pl-4">
          <li>
            <HelpCode>{"{backup_age.age_days}"}</HelpCode> — whole days since the last change
            (a number, rounded down, never negative).
          </li>
          <li>
            <HelpCode>{"{backup_age.last_changed}"}</HelpCode> — ISO date and time (UTC) of that
            commit.
          </li>
          <li>
            <HelpCode>{"{backup_age.commit_sha}"}</HelpCode> — the commit.
          </li>
          <li>
            With the marker: <HelpCode>{"{backup_age.checked_age_days}"}</HelpCode>,{" "}
            <HelpCode>{"{backup_age.last_checked}"}</HelpCode> and{" "}
            <HelpCode>{"{backup_age.marker_found}"}</HelpCode> (true or false).
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Backup-check marker">
        <p>
          With <HelpCode>use_marker</HelpCode> on, the step also reads when a Store in DB record
          of the device was last stored. Add a Store in DB step to the backup workflow, after the
          backup on the success path, and give both steps the same key.
        </p>
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            Backup workflow: Get Configs → Store Artifact (git) → Git Push → Store in DB with{" "}
            <HelpCode>storage_key: backup_checked</HelpCode> and{" "}
            <HelpCode>content_source: single_attribute</HelpCode> and{" "}
            <HelpCode>attribute_path: device.name</HelpCode>. Connect that step&apos;s failure
            outcome to your error notification: a failed write leaves no new marker.
          </li>
          <li>
            Check workflow: Get Age of Backup with <HelpCode>use_marker</HelpCode> on and{" "}
            <HelpCode>marker_storage_key: backup_checked</HelpCode>.
          </li>
        </ol>
        <p>
          Storing the same value again still moves the record&apos;s date, so a constant value
          is fine. Placeholders in <HelpCode>marker_storage_key</HelpCode> are rendered per
          device.
        </p>
        <p>
          A device with no marker still succeeds: <HelpCode>marker_found</HelpCode> is false and
          the two date fields are empty. The step also records one warning event in the run
          (&quot;No backup-check marker found under storage key … for 12 of 12 devices&quot;).
          If it names every device, the key most likely differs from the one in the Store in DB
          step.
        </p>
        <HelpWarning title="A missing marker does not match a number comparison">
          <p>
            An empty <HelpCode>checked_age_days</HelpCode> is never greater than a number, so a
            Route on Attribute with only <HelpCode>{"{:gt(1)}"}</HelpCode> sends these devices to
            its default outcome without any message. Add a first route{" "}
            <HelpCode>{"{backup_age.marker_found:equalsIgnoreCase('false')}"}</HelpCode> and
            connect it, then connect this step&apos;s failure outcome as well. Whole days are
            rounded down, so <HelpCode>{"{:gt(1)}"}</HelpCode> means two full days or more.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the age was written
            for the device.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — per device, for one
            of the reasons listed under Path template, or a marker lookup that failed.
          </li>
        </ul>
      </HelpSection>
    </div>
  );
}
