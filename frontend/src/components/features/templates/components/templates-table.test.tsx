import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TemplateListItem } from "../types";
import { TemplatesTable } from "./templates-table";

afterEach(cleanup);

const TEMPLATE: TemplateListItem = {
  id: 1,
  name: "banner",
  source: "database",
  template_type: "jinja2",
  category: "netmiko",
  description: null,
  created_by: "admin",
  updated_at: null,
};

function renderTable(props: Partial<Parameters<typeof TemplatesTable>[0]> = {}) {
  return render(
    <TemplatesTable
      templates={[TEMPLATE]}
      onView={vi.fn()}
      onEdit={vi.fn()}
      onExport={vi.fn()}
      onDelete={vi.fn()}
      {...props}
    />,
  );
}

describe("TemplatesTable row actions", () => {
  it("offers every action by default", () => {
    renderTable();
    for (const verb of ["View", "Edit", "Export", "Delete"]) {
      expect(screen.getByLabelText(`${verb} banner`)).toBeTruthy();
    }
  });

  it("hides Edit without write permission but keeps View and Export", () => {
    renderTable({ canEdit: false });
    expect(screen.queryByLabelText("Edit banner")).toBeNull();
    expect(screen.getByLabelText("View banner")).toBeTruthy();
    expect(screen.getByLabelText("Export banner")).toBeTruthy();
  });

  it("hides Delete without delete permission", () => {
    renderTable({ canDelete: false });
    expect(screen.queryByLabelText("Delete banner")).toBeNull();
    expect(screen.getByLabelText("Edit banner")).toBeTruthy();
  });

  it("does not invite a read-only user to create the first template", () => {
    renderTable({ templates: [], canEdit: false });
    expect(screen.queryByText(/Create your first template/)).toBeNull();
    expect(screen.getByText("No templates yet.")).toBeTruthy();
  });

  it("still invites a writer to create the first template", () => {
    renderTable({ templates: [] });
    expect(screen.getByText(/Create your first template/)).toBeTruthy();
  });
});
