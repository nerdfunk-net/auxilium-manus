import { describe, expect, it, vi } from "vitest";

import type { Credential } from "@/components/features/settings/credentials/types";
import type { Template } from "@/components/features/templates/types";

import { WORKFLOW_EXPORT_FORMAT } from "../types/workflow-export";
import {
  applyNumericFieldRemap,
  applyStringFieldRemap,
  buildCredentialRemapRequirements,
  buildGitRepositoryRemapRequirements,
  buildSourceRemapRequirements,
  parseWorkflowExportFile,
  resolveWorkflowTemplatesOnImport,
  WorkflowImportParseError,
} from "./workflow-import";
import {
  buildCredentialExportReferences,
  buildWorkflowExportTemplates,
  collectCredentialReferencesFromCanvas,
  collectTemplateIdsFromCanvas,
} from "./workflow-export";

type Node = Record<string, unknown>;

function node(kind: string, pluginConfig: Record<string, unknown>): Node {
  return { id: `${kind}-${Math.random()}`, data: { kind, pluginConfig } };
}

function cred(name: string, visibility: "global" | "private", owner: string | null = null) {
  return { name, visibility, owner_username: owner } as unknown as Credential;
}

function validFile(overrides: Record<string, unknown> = {}) {
  return {
    export_format: WORKFLOW_EXPORT_FORMAT,
    name: "Backup",
    canvas_nodes: [],
    canvas_edges: [],
    canvas_groups: [],
    ...overrides,
  };
}

describe("parseWorkflowExportFile", () => {
  it.each([[null], ["text"], [42], [undefined]])("rejects the non-object %j", (raw) => {
    expect(() => parseWorkflowExportFile(raw)).toThrow(WorkflowImportParseError);
  });

  it("rejects a file with the wrong export_format", () => {
    expect(() => parseWorkflowExportFile(validFile({ export_format: "other" }))).toThrow(
      /Unrecognized workflow export file/,
    );
  });

  it.each([[undefined], [""], ["   "], [7]])("rejects the workflow name %j", (name) => {
    expect(() => parseWorkflowExportFile(validFile({ name }))).toThrow(/missing a workflow name/);
  });

  it.each(["canvas_nodes", "canvas_edges", "canvas_groups"])(
    "rejects a file where %s is not an array",
    (field) => {
      expect(() => parseWorkflowExportFile(validFile({ [field]: {} }))).toThrow(
        new RegExp(field),
      );
    },
  );

  it("fills defaults for a minimal / legacy file", () => {
    const parsed = parseWorkflowExportFile(validFile());
    expect(parsed).toMatchObject({
      description: null,
      folder: null,
      visibility: "private",
      notes: null,
      static_attributes: [],
      credential_references: [],
      templates: [],
    });
    expect(Number.isNaN(Date.parse(parsed.exported_at))).toBe(false);
  });

  it("only accepts 'public' as an explicit non-default visibility", () => {
    expect(parseWorkflowExportFile(validFile({ visibility: "public" })).visibility).toBe("public");
    expect(parseWorkflowExportFile(validFile({ visibility: "shared" })).visibility).toBe("private");
  });

  it("sanitises credential references", () => {
    const parsed = parseWorkflowExportFile(
      validFile({
        credential_references: [
          { name: " g ", visibility: "global", owner_username: "ignored" },
          { name: "p", visibility: "anything", owner_username: "bob" },
          { name: "p2", owner_username: 5 },
          { name: "   " },
          { visibility: "global" },
          null,
          "text",
        ],
      }),
    );
    expect(parsed.credential_references).toEqual([
      { name: "g", visibility: "global", owner_username: null },
      { name: "p", visibility: "private", owner_username: "bob" },
      { name: "p2", visibility: "private", owner_username: null },
    ]);
  });

  it("skips malformed templates but keeps valid ones", () => {
    const parsed = parseWorkflowExportFile(
      validFile({
        templates: [
          { id: 1, name: "ok", content: "x" },
          { id: "2", name: "string id" },
          { id: 0, name: "zero id" },
          { id: -1, name: "negative id" },
          { id: 3 },
          { id: 4, name: "  " },
          null,
        ],
      }),
    );
    expect(parsed.templates.map((t) => [t.id, t.name])).toEqual([
      [1, "ok"],
      [2, "string id"],
    ]);
  });

  it("strips legacy send-mail settings from nodes while parsing", () => {
    const parsed = parseWorkflowExportFile(
      validFile({
        canvas_nodes: [node("send-mail", { to: "a@b.c", smtp_host: "h", credential_reference: "c" })],
      }),
    );
    expect(
      (parsed.canvas_nodes[0].data as { pluginConfig: unknown }).pluginConfig,
    ).toEqual({ to: "a@b.c" });
  });

  // A hand-edited or corrupted file must surface as a parse error the UI can
  // show, not as a raw TypeError.
  it.each([
    ["canvas_nodes", null],
    ["canvas_nodes", "text"],
    ["canvas_edges", 5],
    ["canvas_groups", [1]],
  ])("reports a bad %s entry (%j) as a WorkflowImportParseError", (field, entry) => {
    expect(() => parseWorkflowExportFile(validFile({ [field]: [entry] }))).toThrow(
      WorkflowImportParseError,
    );
  });
});

describe("buildCredentialRemapRequirements", () => {
  const nodes = [node("run-command", { credential_reference: "lab" })];

  it("keeps a visible global credential", () => {
    const reqs = buildCredentialRemapRequirements(
      [{ name: "lab", visibility: "global", owner_username: null }],
      nodes,
      [cred("lab", "global")],
      "me",
    );
    expect(reqs).toEqual([]);
  });

  it("requires a remap for a global credential that is not visible here", () => {
    const [req] = buildCredentialRemapRequirements(
      [{ name: "lab", visibility: "global", owner_username: null }],
      nodes,
      [],
      "me",
    );
    expect(req).toMatchObject({ name: "lab", visibility: "global", credentialType: "ssh" });
  });

  it("keeps my own private credential only while it still exists", () => {
    const meta = [{ name: "lab", visibility: "private" as const, owner_username: "me" }];
    expect(buildCredentialRemapRequirements(meta, nodes, [cred("lab", "private", "me")], "me")).toEqual([]);
    expect(buildCredentialRemapRequirements(meta, nodes, [], "me")).toHaveLength(1);
  });

  it("does not accept a global credential of the same name for my private one", () => {
    const meta = [{ name: "lab", visibility: "private" as const, owner_username: "me" }];
    expect(buildCredentialRemapRequirements(meta, nodes, [cred("lab", "global")], "me")).toHaveLength(1);
  });

  it.each([["alice"], [null]])(
    "always remaps a private credential owned by %j",
    (owner) => {
      const meta = [{ name: "lab", visibility: "private" as const, owner_username: owner }];
      expect(
        buildCredentialRemapRequirements(meta, nodes, [cred("lab", "private", "me")], "me"),
      ).toHaveLength(1);
    },
  );

  it("treats a legacy file (no sidecar) as keep-when-visible", () => {
    expect(buildCredentialRemapRequirements([], nodes, [cred("lab", "global")], "me")).toEqual([]);
    const [req] = buildCredentialRemapRequirements([], nodes, [], "me");
    expect(req).toMatchObject({ visibility: "unknown", owner_username: null });
  });

  it("infers the required credential type from the step kind", () => {
    const reqs = buildCredentialRemapRequirements(
      [],
      [
        node("encrypt-attribute", { credential_reference: "secret" }),
        node("add-pyats-testbed", { credential_reference: "generic" }),
        node("run-command", { credential_reference: "ssh-cred" }),
      ],
      [],
      "me",
    );
    expect(Object.fromEntries(reqs.map((r) => [r.name, r.credentialType]))).toEqual({
      secret: "shared_secret",
      generic: "generic",
      "ssh-cred": "ssh",
    });
  });
});

describe("git repository and source remap requirements", () => {
  it("lists only ids missing in the target environment", () => {
    const nodes = [
      node("a", { git_repository_id: 1 }),
      node("b", { git_repository_id: 2 }),
      node("c", { git_repository_id: 2 }),
    ];
    expect(buildGitRepositoryRemapRequirements(nodes, [1])).toEqual([{ id: 2 }]);
    expect(buildGitRepositoryRemapRequirements(nodes, [1, 2])).toEqual([]);
  });

  it("lists only source ids missing in the target environment", () => {
    const nodes = [
      node("a", { nautobot_source_id: "nb-1" }),
      node("b", { nautobot_source_id: "nb-2" }),
    ];
    expect(buildSourceRemapRequirements(nodes, "nautobot_source_id", ["nb-1"])).toEqual([
      { sourceId: "nb-2" },
    ]);
  });
});

describe("applyStringFieldRemap", () => {
  it("rewrites matching values (trimmed) and leaves others", () => {
    const nodes = [
      node("a", { credential_reference: " old " }),
      node("b", { credential_reference: "keep" }),
    ];
    const result = applyStringFieldRemap(nodes, "credential_reference", new Map([["old", "new"]]));
    const refs = result.map(
      (n) => ((n.data as Node).pluginConfig as Node).credential_reference,
    );
    expect(refs).toEqual(["new", "keep"]);
  });

  it("clears the field when the target is an empty string", () => {
    const result = applyStringFieldRemap(
      [node("a", { credential_reference: "old" })],
      "credential_reference",
      new Map([["old", ""]]),
    );
    expect(((result[0].data as Node).pluginConfig as Node).credential_reference).toBe("");
  });

  it("does not mutate the input, with or without a remap", () => {
    const original = [node("a", { credential_reference: "old" })];
    const snapshot = structuredClone(original);
    const withRemap = applyStringFieldRemap(original, "credential_reference", new Map([["old", "new"]]));
    const withoutRemap = applyStringFieldRemap(original, "credential_reference", new Map());
    expect(original).toEqual(snapshot);
    expect(withRemap[0]).not.toBe(original[0]);
    expect(withoutRemap[0]).not.toBe(original[0]);
  });

  it("tolerates nodes without data or pluginConfig", () => {
    const nodes: Node[] = [{}, { data: null }, { data: {} }, { data: { pluginConfig: 3 } }];
    expect(() =>
      applyStringFieldRemap(nodes, "credential_reference", new Map([["a", "b"]])),
    ).not.toThrow();
  });
});

describe("applyNumericFieldRemap", () => {
  const ids = (nodes: Node[]) =>
    nodes.map((n) => ((n.data as Node).pluginConfig as Node).template_id);

  it("remaps numbers and numeric strings", () => {
    const result = applyNumericFieldRemap(
      [node("a", { template_id: 1 }), node("b", { template_id: "2" })],
      "template_id",
      new Map([
        [1, 10],
        [2, 20],
      ]),
    );
    expect(ids(result)).toEqual([10, 20]);
  });

  it("applies a swap in a single pass (1<->2) without chaining", () => {
    const result = applyNumericFieldRemap(
      [node("a", { template_id: 1 }), node("b", { template_id: 2 })],
      "template_id",
      new Map([
        [1, 2],
        [2, 1],
      ]),
    );
    expect(ids(result)).toEqual([2, 1]);
  });

  it("leaves unmapped, empty and non-integer values alone", () => {
    const result = applyNumericFieldRemap(
      [
        node("a", { template_id: 99 }),
        node("b", { template_id: "" }),
        node("c", { template_id: null }),
        node("d", { template_id: "x" }),
        node("e", { template_id: 1.5 }),
        node("f", { template_id: true }),
      ],
      "template_id",
      new Map([[1, 10]]),
    );
    expect(ids(result)).toEqual([99, "", null, "x", 1.5, true]);
  });

  it("does not mutate the input", () => {
    const original = [node("a", { template_id: 1 })];
    const snapshot = structuredClone(original);
    applyNumericFieldRemap(original, "template_id", new Map([[1, 2]]));
    expect(original).toEqual(snapshot);
  });
});

describe("resolveWorkflowTemplatesOnImport", () => {
  const exported = (id: number, name: string) =>
    ({ id, name, template_type: "jinja2", category: "netmiko", content: "", variables: {},
      pre_run_commands: [], pre_run_use_textfsm: false, nautobot_attributes: [],
      description: null, notes: null }) as never;

  it("reuses an existing template with the same name and creates the rest", async () => {
    const createTemplate = vi.fn(async (payload: { name: string }) =>
      ({ id: 500, name: payload.name }) as unknown as Template,
    );
    const remap = await resolveWorkflowTemplatesOnImport({
      exportedTemplates: [exported(1, "existing"), exported(2, "fresh")],
      existingTemplates: [{ id: 77, name: "existing" } as never],
      createTemplate,
    });
    expect(remap).toEqual(new Map([[1, 77], [2, 500]]));
    expect(createTemplate).toHaveBeenCalledTimes(1);
  });

  it("creates a same-named template only once", async () => {
    const createTemplate = vi.fn(async (payload: { name: string }) =>
      ({ id: 500, name: payload.name }) as unknown as Template,
    );
    const remap = await resolveWorkflowTemplatesOnImport({
      exportedTemplates: [exported(1, "dup"), exported(2, "dup")],
      existingTemplates: [],
      createTemplate,
    });
    expect(createTemplate).toHaveBeenCalledTimes(1);
    expect(remap).toEqual(new Map([[1, 500], [2, 500]]));
  });

  it("propagates a creation failure", async () => {
    await expect(
      resolveWorkflowTemplatesOnImport({
        exportedTemplates: [exported(1, "x")],
        existingTemplates: [],
        createTemplate: async () => {
          throw new Error("boom");
        },
      }),
    ).rejects.toThrow("boom");
  });
});

describe("export -> import round trip", () => {
  it("preserves the canvas, references and templates through JSON", () => {
    const canvasNodes = [
      node("run-command", { credential_reference: "lab", template_id: 5, git_repository_id: 3 }),
      node("send-mail", { to: "ops@example.com" }),
    ];
    const template = {
      id: 5, name: "t", description: "d", notes: "n", template_type: "jinja2",
      category: "netmiko", content: "show ver", variables: { a: { value: "1", type: "custom" } },
      pre_run_commands: ["terminal length 0"], pre_run_use_textfsm: true,
      nautobot_attributes: ["name"],
    } as unknown as Template;

    const file = {
      export_format: WORKFLOW_EXPORT_FORMAT,
      exported_at: "2026-01-01T00:00:00.000Z",
      name: "Backup",
      description: "desc",
      folder: "ops",
      visibility: "public",
      notes: "wiki",
      canvas_nodes: canvasNodes,
      canvas_edges: [{ id: "e", source: "a", target: "b" }],
      canvas_groups: [{ id: "g" }],
      static_attributes: [],
      credential_references: buildCredentialExportReferences(
        collectCredentialReferencesFromCanvas(canvasNodes),
        [cred("lab", "global")],
      ),
      templates: buildWorkflowExportTemplates(collectTemplateIdsFromCanvas(canvasNodes), [template]),
    };

    const parsed = parseWorkflowExportFile(JSON.parse(JSON.stringify(file)));
    expect(parsed).toEqual(file);
  });
});
