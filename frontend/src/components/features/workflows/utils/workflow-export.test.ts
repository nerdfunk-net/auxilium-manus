import { describe, expect, it } from "vitest";

import type { Credential } from "@/components/features/settings/credentials/types";
import type { Template } from "@/components/features/templates/types";

import {
  buildCredentialExportReferences,
  buildWorkflowExportTemplates,
  collectCredentialReferencesFromCanvas,
  collectGitRepositoryIdsFromCanvas,
  collectSourceIdsFromCanvas,
  collectTemplateIdsFromCanvas,
  slugifyWorkflowName,
} from "./workflow-export";

function nodeWith(pluginConfig: unknown): Record<string, unknown> {
  return { id: "n", data: { kind: "x", pluginConfig } };
}

function credential(overrides: Partial<Credential>): Credential {
  return {
    id: 1,
    name: "lab",
    visibility: "global",
    owner_username: null,
    ...overrides,
  } as Credential;
}

describe("slugifyWorkflowName", () => {
  it.each([
    ["Backup Configs", "backup-configs"],
    ["  Spaced   Out  ", "spaced-out"],
    ["Ünï/cödé & symbols!", "n-c-d-symbols"],
    ["--already-slug--", "already-slug"],
    ["", "workflow"],
    ["!!!", "workflow"],
  ])("%j -> %j", (input, expected) => {
    expect(slugifyWorkflowName(input)).toBe(expected);
  });
});

describe("collectCredentialReferencesFromCanvas", () => {
  it("returns unique, trimmed, sorted, non-empty names", () => {
    const nodes = [
      nodeWith({ credential_reference: " b-cred " }),
      nodeWith({ credential_reference: "a-cred" }),
      nodeWith({ credential_reference: "b-cred" }),
      nodeWith({ credential_reference: "   " }),
      nodeWith({ credential_reference: 42 }),
    ];
    expect(collectCredentialReferencesFromCanvas(nodes)).toEqual(["a-cred", "b-cred"]);
  });

  it("skips nodes without data or pluginConfig of the right shape", () => {
    const nodes: Record<string, unknown>[] = [
      {},
      { data: null },
      { data: "text" },
      { data: {} },
      { data: { pluginConfig: null } },
      { data: { pluginConfig: "text" } },
    ];
    expect(collectCredentialReferencesFromCanvas(nodes)).toEqual([]);
  });
});

describe("numeric id collectors", () => {
  it("collects unique positive integers sorted numerically (not lexically)", () => {
    const nodes = [
      nodeWith({ template_id: 10 }),
      nodeWith({ template_id: 2 }),
      nodeWith({ template_id: "7" }),
      nodeWith({ template_id: 2 }),
    ];
    expect(collectTemplateIdsFromCanvas(nodes)).toEqual([2, 7, 10]);
  });

  // `true` guards against Number(true) === 1.
  it.each([[null], [undefined], [""], [0], [-3], [1.5], ["abc"], [{}], [true], [false], [[5]]])(
    "ignores the invalid value %j",
    (value) => {
      expect(collectTemplateIdsFromCanvas([nodeWith({ template_id: value })])).toEqual([]);
    },
  );

  it("reads git_repository_id independently of template_id", () => {
    const nodes = [nodeWith({ git_repository_id: 4, template_id: 9 })];
    expect(collectGitRepositoryIdsFromCanvas(nodes)).toEqual([4]);
    expect(collectTemplateIdsFromCanvas(nodes)).toEqual([9]);
  });
});

describe("collectSourceIdsFromCanvas", () => {
  it("collects trimmed unique string ids for the requested key only", () => {
    const nodes = [
      nodeWith({ nautobot_source_id: " nb-1 ", batfish_source_id: "bf" }),
      nodeWith({ nautobot_source_id: "nb-1" }),
      nodeWith({ nautobot_source_id: "" }),
      nodeWith({ nautobot_source_id: 5 }),
    ];
    expect(collectSourceIdsFromCanvas(nodes, "nautobot_source_id")).toEqual(["nb-1"]);
    expect(collectSourceIdsFromCanvas(nodes, "batfish_source_id")).toEqual(["bf"]);
  });
});

describe("buildCredentialExportReferences", () => {
  it("exports global credentials with no owner", () => {
    const refs = buildCredentialExportReferences(
      ["lab"],
      [credential({ name: "lab", visibility: "global", owner_username: "alice" })],
    );
    expect(refs).toEqual([{ name: "lab", visibility: "global", owner_username: null }]);
  });

  it("exports private credentials with their owner", () => {
    const refs = buildCredentialExportReferences(
      ["mine"],
      [credential({ name: "mine", visibility: "private", owner_username: "alice" })],
    );
    expect(refs).toEqual([{ name: "mine", visibility: "private", owner_username: "alice" }]);
  });

  it("exports unresolved names as private with a null owner so import forces a remap", () => {
    expect(buildCredentialExportReferences(["ghost"], [])).toEqual([
      { name: "ghost", visibility: "private", owner_username: null },
    ]);
  });
});

describe("buildWorkflowExportTemplates", () => {
  const template = (id: number, name: string) =>
    ({
      id,
      name,
      description: null,
      notes: undefined,
      template_type: "jinja2",
      category: "netmiko",
      content: "show version",
      variables: undefined,
      pre_run_commands: undefined,
      pre_run_use_textfsm: undefined,
      nautobot_attributes: undefined,
    }) as unknown as Template;

  it("embeds the template payload with the source id, in the requested order", () => {
    const result = buildWorkflowExportTemplates([2, 1], [template(1, "a"), template(2, "b")]);
    expect(result.map((t) => [t.id, t.name])).toEqual([
      [2, "b"],
      [1, "a"],
    ]);
  });

  it("normalises missing optional fields", () => {
    const [exported] = buildWorkflowExportTemplates([1], [template(1, "a")]);
    expect(exported).toMatchObject({
      notes: null,
      variables: {},
      pre_run_commands: [],
      pre_run_use_textfsm: false,
      nautobot_attributes: [],
    });
  });

  it("omits stale template ids that no longer exist", () => {
    expect(buildWorkflowExportTemplates([99], [template(1, "a")])).toEqual([]);
  });
});
