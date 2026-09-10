import { describe, expect, it } from "vitest";

import type { Template } from "../types";
import {
  templateExportToCreatePayload,
  templateToExportPayload,
} from "./template-export";
import { parseTemplateExportPayload } from "./template-import";

const BASE_TEMPLATE: Template = {
  id: 1,
  name: "backbone-bgp",
  source: "webeditor",
  template_type: "jinja2",
  category: "netmiko",
  description: "one-liner",
  notes: "# Wiki\n\nHow this template works.",
  content: "hostname {{ device.name }}",
  variables: {},
  pre_run_commands: [],
  pre_run_use_textfsm: false,
  nautobot_attributes: [],
  credential_id: null,
  created_by: "admin",
  is_active: true,
  created_at: null,
  updated_at: null,
};

describe("template export/import — notes (wiki) field", () => {
  it("carries notes into the export payload", () => {
    expect(templateToExportPayload(BASE_TEMPLATE).notes).toBe(
      "# Wiki\n\nHow this template works.",
    );
  });

  it("defaults a missing notes to null in the export payload", () => {
    const withoutNotes: Record<string, unknown> = { ...BASE_TEMPLATE };
    delete withoutNotes.notes;
    expect(
      templateToExportPayload(withoutNotes as unknown as Template).notes,
    ).toBeNull();
  });

  it("passes notes through to the create payload", () => {
    const payload = templateToExportPayload(BASE_TEMPLATE);
    expect(templateExportToCreatePayload(payload).notes).toBe(payload.notes);
  });

  it("round-trips notes when parsing an export file object", () => {
    const parsed = parseTemplateExportPayload({
      name: "backbone-bgp",
      notes: "documented",
    });
    expect(parsed.notes).toBe("documented");
  });

  it("defaults notes to null when the import object omits it", () => {
    const parsed = parseTemplateExportPayload({ name: "backbone-bgp" });
    expect(parsed.notes).toBeNull();
  });
});
