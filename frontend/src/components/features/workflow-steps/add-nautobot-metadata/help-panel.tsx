"use client";

import { HelpCode, HelpExample, HelpSection, HelpWarning } from "../shared/step-help";

/** Built-in Help tab content for Add Metadata (every Configuration control, with examples). */
export function AddNautobotMetadataHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          Makes sure a Location or a Device Type exists in Nautobot before devices are added to
          it. If the object already exists it is reused, so the step can run again safely.
          Devices that resolve to the same object share a single Nautobot call.
        </p>
      </HelpSection>

      <HelpSection title="Nautobot source">
        <p>
          Click <span className="font-medium text-foreground">Configure Source</span> and choose a
          source from Settings → Sources → Nautobot. The step stores{" "}
          <HelpCode>nautobot_source_id</HelpCode>; the Nautobot dropdowns need it.
        </p>
      </HelpSection>

      <HelpSection title="How a value is entered">
        <p>Every field takes a fixed text, a pick from Nautobot, or an attribute-bag expression:</p>
        <ul className="list-disc space-y-1 pl-4">
          <li>
            Type a fixed value, e.g. <HelpCode>Berlin</HelpCode>
          </li>
          <li>
            Pick an existing entry from the dropdown (it fills the text box with that name)
          </li>
          <li>
            Use a path, e.g. <HelpCode>{"{custom.location_name}"}</HelpCode> — or click the
            magnifier to browse the attributes of the last run
          </li>
          <li>
            Mix both, e.g. <HelpCode>{"Site-{custom.code}"}</HelpCode>
          </li>
        </ul>
        <HelpWarning title="A path that does not exist fails that device">
          <p>
            Add a default to allow it: <HelpCode>{"{custom.parent | default('')}"}</HelpCode>. The
            only exception is Description, where a missing path counts as empty. Other devices in
            the run still proceed.
          </p>
        </HelpWarning>
      </HelpSection>

      <HelpSection title="Location">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>location_type</HelpCode> * — a Nautobot location type, e.g.{" "}
            <HelpCode>Site</HelpCode> or <HelpCode>{"{custom.location_type}"}</HelpCode>
          </li>
          <li>
            <HelpCode>name</HelpCode> * — e.g. <HelpCode>{"{custom.location_name}"}</HelpCode>
          </li>
          <li>
            <HelpCode>status</HelpCode> * — defaults to <HelpCode>Active</HelpCode>; may be{" "}
            <HelpCode>{"{nautobot.status}"}</HelpCode>
          </li>
          <li>
            <HelpCode>description</HelpCode> — optional, may be empty
          </li>
          <li>
            <HelpCode>parent</HelpCode> — optional parent location. Nautobot requires one when the
            location type is nested under another type (for example a Site under a Region).
          </li>
        </ul>
        <HelpExample>
          {`location_type: {custom.location_type}
name:          {custom.location_name}
status:        Active
description:  {custom.description}`}
        </HelpExample>
      </HelpSection>

      <HelpSection title="Device Type">
        <ul className="list-disc space-y-1 pl-4">
          <li>
            <HelpCode>manufacturer</HelpCode> * — must already exist in Nautobot
          </li>
          <li>
            <HelpCode>role</HelpCode> * — must already exist for devices
          </li>
          <li>
            <HelpCode>model</HelpCode> * — the device type name, e.g. <HelpCode>C9300-24T</HelpCode>
          </li>
          <li>
            <HelpCode>height</HelpCode> * — positive whole number of rack units, default{" "}
            <HelpCode>1</HelpCode>
          </li>
          <li>
            <HelpCode>platform</HelpCode> — optional, but Nautobot needs it to log in to the device
          </li>
        </ul>
        <HelpWarning title="Role and platform are not stored on the device type">
          <p>
            A Nautobot device type only holds manufacturer, model and height. Role and platform are
            checked against Nautobot (an unknown name fails the device) and written, with the
            model, into the device&apos;s <HelpCode>nautobot</HelpCode> attributes (
            <HelpCode>device_type</HelpCode>, <HelpCode>role</HelpCode>,{" "}
            <HelpCode>platform</HelpCode>). A later Add to Nautobot step set to{" "}
            <HelpCode>{"{nautobot.origin}"}</HelpCode> then uses them.
          </p>
        </HelpWarning>
        <HelpExample>
          {`manufacturer: {custom.manufacturer}
role:         {custom.role}
model:        {custom.model}
height:       1
platform:     {custom.platform}`}
        </HelpExample>
      </HelpSection>

      <HelpSection title="Outcomes">
        <p>
          <HelpCode>success</HelpCode> — the object exists (created or reused).{" "}
          <HelpCode>failure</HelpCode> — a value could not be resolved, a referenced object was
          not found in Nautobot, or Nautobot rejected the request; the device carries an error
          code such as <HelpCode>unresolved_attribute</HelpCode>,{" "}
          <HelpCode>missing_required_field</HelpCode>, <HelpCode>invalid_height</HelpCode> or{" "}
          <HelpCode>reference_not_found</HelpCode>.
        </p>
      </HelpSection>
    </div>
  );
}
