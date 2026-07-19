"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/**
 * Built-in Help tab content for Render Jinja Template.
 * Covers every Configuration control with practical examples.
 */
export function RenderJinjaTemplateHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Renders a stored Jinja2 template once per device using the current workflow
          context (device fields, Nautobot attributes, command output, custom bags).
          The result is written to{" "}
          <HelpCode>device.parsed.{"{output_key}"}</HelpCode> for downstream Compare
          Data, Update Attribute, Route on Attribute, or Store Artifact steps.
        </p>
      </HelpSection>

      <HelpSection title="Output key">
        <p>
          <HelpCode>output_key</HelpCode> names the slot where rendered text is stored
          on each device. Downstream steps reference{" "}
          <HelpCode>device.parsed.{"{output_key}"}</HelpCode> or, in Compare Data,
          set <HelpCode>parsed_output_key</HelpCode> to the same value when content
          source is <HelpCode>rendered_template</HelpCode>.
        </p>
        <HelpExample>
          output_key: device_config
          <br />
          <span className="text-muted-foreground">
            → result at device.parsed.device_config
          </span>
        </HelpExample>
        <p>
          Use a short, descriptive slug (e.g. <HelpCode>device_config</HelpCode>,{" "}
          <HelpCode>audit_report</HelpCode>, <HelpCode>expected_routes</HelpCode>).
          Avoid spaces and special characters.
        </p>
      </HelpSection>

      <HelpSection title="Template">
        <p>
          Select a template from the Templates library dropdown. The step stores{" "}
          <HelpCode>template_id</HelpCode> (numeric ID of the stored template). Only
          Jinja2 templates (<HelpCode>template_type: jinja2</HelpCode>) appear in the
          list.
        </p>
        <p>
          Create and edit templates in the Templates section before configuring this
          step. The selected template body is rendered at workflow runtime with full
          device and run context available to Jinja.
        </p>
        <HelpExample>
          template_id: 12
          <br />
          output_key: site_summary
          <br />
          <span className="text-muted-foreground">
            → renders template #12 (e.g. &quot;Site audit summary&quot;) per device
          </span>
        </HelpExample>
        <HelpWarning title="Template must exist">
          <p>
            If the previously selected template was deleted, the Configuration panel
            shows an error — pick another template from the dropdown.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Template context">
        <p>
          Templates typically use device identity, Nautobot fields, and upstream step
          output, for example:
        </p>
        <HelpExample>
          {"{{ device.name }}"} — {"{{ nautobot.location.name }}"}
          <br />
          {"{{ device.parsed.version }}"} — from Run Command + TextFSM
          <br />
          {"{{ custom.my_field }}"} — from Update Attribute or context
        </HelpExample>
        <p>
          Test templates in the Templates editor with sample context before wiring
          them into a workflow.
        </p>
      </HelpSection>

      <HelpSection title="Outcomes">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <span className="font-medium text-foreground">success</span> — template
            rendered for the device; output available at{" "}
            <HelpCode>device.parsed.{"{output_key}"}</HelpCode>.
          </li>
          <li>
            <span className="font-medium text-foreground">failure</span> — missing
            template, Jinja syntax error, or undefined variable when strict rendering
            fails. Check template syntax and context paths.
          </li>
        </ul>
      </HelpSection>

      <HelpSection title="Typical setup">
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Create a Jinja2 template in Templates with the fields you need.</li>
          <li>
            Place after steps that populate context (inventory, Run Command, Update
            Attribute).
          </li>
          <li>Set output_key and select the template.</li>
          <li>
            Use Compare Data with content source rendered_template, or Store Artifact,
            referencing the same output_key.
          </li>
        </ol>
      </HelpSection>
    </div>
  );
}
