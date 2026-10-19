"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/** Built-in Help tab content for Run Workflow. */
export function StartWorkflowHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Starts another workflow as a run of its own, for example a backup before a change, and
          optionally waits for it. The started run appears in the run list with a link to the run
          that started it. The same workflow can still be run by hand or on a schedule.
        </p>
      </HelpSection>

      <HelpSection title="Devices">
        <p>
          Devices reach the started workflow the way a schedule or a manual run supplies them: as
          the text run input of a{" "}
          <span className="font-medium text-foreground">Get from User</span> step (its{" "}
          <HelpCode>device_param</HelpCode>), one <HelpCode>name,ip,network_driver</HelpCode> line per device (the driver the calling workflow knows for the device rides along).
          Choose that input under <span className="font-medium text-foreground">Devices of this
          workflow go into</span>. A workflow without such an input is started without devices.
        </p>
        <p>
          Start the backup workflow with <span className="font-medium text-foreground">Get from
          User</span>, then Get Nautobot Attributes if you need the Nautobot data. A device with
          neither name nor IP the other workflow can use leaves through{" "}
          <HelpCode>failure</HelpCode> as <HelpCode>no_device_identity</HelpCode>.
        </p>
        <p>
          To back up a <span className="font-medium text-foreground">saved inventory</span>
          instead, give the started workflow an inventory run input and select the inventory under
          Run inputs. That is independent of this workflow&apos;s devices.
        </p>
      </HelpSection>

      <HelpSection title="One run or one run per device">
        <p>
          <span className="font-medium text-foreground">One run for all devices</span> (default)
          passes every device in one run; they succeed or fail together.{" "}
          <span className="font-medium text-foreground">One run per device</span> starts a run for
          each device and routes every device by its own result, so a failed backup stops only that
          device. It starts at most <HelpCode>max_runs</HelpCode> runs; if more devices arrive the
          step stops before it starts any.
        </p>
      </HelpSection>

      <HelpSection title="Waiting">
        <p>
          With <HelpCode>Wait for the runs to finish</HelpCode> on, the step checks the runs every{" "}
          <HelpCode>poll_interval_seconds</HelpCode> for at most <HelpCode>wait_seconds</HelpCode>{" "}
          (5 to 600; the default is 300). A device continues through <HelpCode>success</HelpCode>{" "}
          when its run finished successfully and its Get from User step really ran. A failed,
          cancelled or partial run, or one still running when the time is up, sends the device
          through <HelpCode>failure</HelpCode>. A run that is still going is not stopped.
        </p>
        <p>
          With waiting off the step only starts the runs and reports <HelpCode>success</HelpCode>{" "}
          at once. Cancelling the calling run, or losing it to a worker crash, cancels the started
          runs too.
        </p>
      </HelpSection>

      <HelpSection title="Run inputs and results">
        <p>
          The other inputs of the started workflow are listed under Run inputs, with the same
          fields a schedule shows. Required inputs without a default must be given. The run id, its
          status and the seconds waited are written to every device&apos;s{" "}
          <HelpCode>child_run</HelpCode> attribute bag.
        </p>
        <p>
          <span className="font-medium text-foreground">Secret inputs are never passed</span>:
          run inputs are saved in the workflow definition as plain text. A workflow that needs a
          secret run input cannot be started by this step; give it a credential reference with a
          default instead.
        </p>
      </HelpSection>

      <HelpSection title="Example: back up, then change">
        <HelpExample>
          {`Get from Nautobot
  -> Run Workflow (backup workflow, wait 300 s)
       success -> Deploy Rendered Template
       failure -> Notify on Error`}
        </HelpExample>
        <p>
          Wire <HelpCode>failure</HelpCode> to a notification so a change never runs without a
          finished backup.
        </p>
      </HelpSection>

      <HelpWarning title="Things to know">
        <p>
          Inside a fan-out branch the step runs once per child; with one run per device that
          multiplies the runs. Place it before the fan-out or after a Fan In. A workflow cannot
          start itself or one that started it, and chains are limited to three levels. The wait is
          held in the worker and is lost if the worker restarts; the started runs are not.
        </p>
      </HelpWarning>
    </div>
  );
}
