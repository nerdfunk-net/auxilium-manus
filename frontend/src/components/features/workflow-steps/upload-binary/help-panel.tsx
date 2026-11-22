"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/** Built-in Help tab content for Upload Binary: every Configuration control with an example. */
export function UploadBinaryHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Copies one file — typically an IOS / IOS-XE image — from a Git repository to the
          filesystem of every device in context, using SCP. The file&apos;s MD5 is computed
          before anything is sent; after the copy the device&apos;s own{" "}
          <HelpCode>verify /md5</HelpCode> result must equal it. If it does not, cannot be read
          or times out, the copy is deleted from the device again and the device leaves through{" "}
          <span className="font-medium text-foreground">failure</span>.
        </p>
        <p>
          Needs devices from an inventory step, an SSH credential, and SCP enabled on the device
          (<HelpCode>ip scp server enable</HelpCode>, with the user allowed to use it).
        </p>
      </HelpSection>

      <HelpSection title="Credential reference">
        <p>
          Select an SSH credential (or a run parameter holding one). The same rules as Upload
          Config apply.
        </p>
      </HelpSection>

      <HelpSection title="git_repository_id and allow_stale_repository">
        <p>
          The repository that holds the file (Settings → Git Repositories). It is pulled before
          the copy; with <HelpCode>allow_stale_repository</HelpCode> on, an unreachable remote
          falls back to the last local copy instead of failing the step.
        </p>
        <HelpWarning title="The file is copied once, then the repository is released">
          <p>
            The step reads the file from the checkout once into a private temporary copy (it needs
            that much free disk space on the server, up to 4 GiB per file) and hashes that copy.
            The checksum, <HelpCode>expected_md5</HelpCode> and the bytes sent to the devices all
            come from it, and the repository is released before the first device is contacted. A
            file that changes while it is being read fails the step.
          </p>
        </HelpWarning>
        <HelpWarning title="Git LFS">
          <p>
            An image stored with Git LFS is a small pointer file in the checkout, not the image.
            The step refuses it. Store the file without LFS, or make sure the checkout holds the
            real bytes.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="source_path">
        <p>
          Path of the file inside the repository. <HelpCode>..</HelpCode>, the{" "}
          <HelpCode>.git</HelpCode> directory and symbolic links are refused.
        </p>
        <HelpExample>source_path: images/cat9k_iosxe.17.09.04a.SPA.bin</HelpExample>
      </HelpSection>

      <HelpSection title="expected_md5">
        <p>
          Optional. The MD5 the vendor publishes for the image (32 hexadecimal characters). If
          the file in the repository does not match, the step fails before any device is
          contacted, so a corrupted or wrong file never reaches a device.
        </p>
        <HelpExample>expected_md5: 0f2c5a1e9b7d4c3a8e6f1b2d3c4a5b6e</HelpExample>
      </HelpSection>

      <HelpSection title="destination_filename and file_system">
        <p>
          The name on the device (empty = the file name of <HelpCode>source_path</HelpCode>) and
          the filesystem, as the device spells it.
        </p>
        <HelpExample>
          destination_filename: cat9k_iosxe.17.09.04a.SPA.bin
          <br />
          file_system: flash:
        </HelpExample>
        <p>
          Both are pasted into device commands, so they must not contain spaces or line breaks.
        </p>
      </HelpSection>

      <HelpSection title="overwrite">
        <p>
          The step first checks whether the file exists and, if so, its MD5. An identical file
          is never copied again: the device counts as successful. A different file fails the
          device while overwrite is off, and is replaced while it is on.
        </p>
      </HelpSection>

      <HelpSection title="network_driver_override, socket_timeout and read_timeout">
        <p>
          <HelpCode>network_driver_override</HelpCode> sets the Netmiko device type for every
          device in the step. <HelpCode>socket_timeout</HelpCode> (5–300 s) is the wait for one
          SCP socket operation, not for the whole copy.
        </p>
        <p>
          <HelpCode>read_timeout</HelpCode> (5–600 s, default 600) is how long the step waits for
          the device&apos;s <HelpCode>verify /md5</HelpCode> answer. Hashing a large image on slow
          flash takes minutes; raise it if devices fail with a timeout.
        </p>
      </HelpSection>

      <HelpSection title="Why there is no inline transfer">
        <p>
          Upload Config can send text through the device CLI (inline transfer). That mode
          carries text only and would corrupt a binary, so it does not exist here. If SCP is not
          available the device fails with the reason; enable SCP on the device instead.
        </p>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — the file is on the
            device and its MD5 matches.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — no hostname or IP, SSH
            or SCP failed, not enough space, the file exists and overwrite is off, or the checksum
            did not match. A bad source file or an <HelpCode>expected_md5</HelpCode> mismatch
            fails the whole step instead.
          </li>
        </ul>
      </HelpSection>
    </div>
  );
}
