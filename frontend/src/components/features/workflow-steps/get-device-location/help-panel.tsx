"use client";

import {
  HelpCode,
  HelpExample,
  HelpSection,
  HelpWarning,
} from "../shared/step-help";

/** Built-in Help tab content for Get Location of Device (get-device-location). */
export function GetDeviceLocationHelpPanel() {
  return (
    <div className="space-y-6">
      <HelpSection title="What this step does">
        <p>
          A device in Nautobot belongs to exactly one location, usually the lowest
          level of a hierarchy such as Country → State → City → Building → Room.
          This step walks up that hierarchy, finds the location whose{" "}
          <span className="font-medium text-foreground">location type</span>{" "}
          matches the one you chose and writes its name to an attribute.
        </p>
        <p>
          Use it so a backup path can use the city or building instead of an
          ambiguous room name.
        </p>
      </HelpSection>

      <HelpSection title="Nautobot source">
        <p>
          Choose a source from Settings → Sources → Nautobot. It is stored as{" "}
          <HelpCode>nautobot_source_id</HelpCode>. The device is found by its
          Nautobot ID (when an earlier Nautobot step set it), otherwise by name and
          then primary IPv4.
        </p>
      </HelpSection>

      <HelpSection title="location_type">
        <p>
          Click <span className="font-medium text-foreground">Select Location Type</span>{" "}
          to list the location types of the source and click one. Type names are
          unique, but a <span className="font-medium text-foreground">nestable</span>{" "}
          type (a Building inside a Building) can appear more than once in one
          hierarchy; the picker marks these.
        </p>
        <HelpExample>
          location_type: City
          <br />
          <span className="text-muted-foreground">
            Room A → Building A → City A → … gives &quot;City A&quot;
          </span>
        </HelpExample>
      </HelpSection>

      <HelpSection title="target_attribute">
        <p>
          Attribute that receives the location name, in <HelpCode>bag.field</HelpCode>{" "}
          form. Default <HelpCode>custom.location</HelpCode>. The{" "}
          <HelpCode>device</HelpCode>, <HelpCode>parsed</HelpCode> and{" "}
          <HelpCode>run_input</HelpCode> namespaces cannot be written.
        </p>
        <HelpExample>
          path_template: ./{"{custom.location}"}/{"{device.name}"}.cfg
        </HelpExample>
      </HelpSection>

      <HelpSection title="case_insensitive_lookup">
        <p>
          Only matters when the device has to be looked up by name: match it
          regardless of case (for example names lower-cased by Batfish).
        </p>
      </HelpSection>

      <HelpWarning title="Devices without a matching location fail">
        <p>
          A device with no location, or none of the chosen type in its hierarchy
          (for example it sits in a Country but you chose City), leaves through the{" "}
          <HelpCode>failure</HelpCode> handle with code{" "}
          <HelpCode>location_type_not_found</HelpCode>. The message lists the
          hierarchy that was found (up to 8 levels).
        </p>
        <p>
          If a nestable type occurs more than once in the hierarchy the device also
          fails, with code <HelpCode>location_type_ambiguous</HelpCode>, instead of
          picking one of them.
        </p>
      </HelpWarning>
    </div>
  );
}
