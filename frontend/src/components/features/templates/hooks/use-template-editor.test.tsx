import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryWrapper } from "@/test/query-wrapper";

import type { DeviceSummary } from "../types";
import { useTemplateEditor } from "./use-template-editor";

const mocks = vi.hoisted(() => ({
  params: new URLSearchParams(),
  router: { replace: vi.fn(), push: vi.fn() },
  template: { data: undefined as unknown, isLoading: false },
  sources: [] as { sourceId: string }[],
  credentials: { sourceId: "" as string | undefined, isReady: false },
  attributes: { data: undefined as unknown, error: null as unknown },
  workflows: { data: undefined as unknown },
  referenceWorkflow: { data: undefined as unknown },
  attributesQueryArgs: vi.fn(),
  credentialsArgs: vi.fn(),
  deviceHook: vi.fn(),
  saveHook: vi.fn(),
  render: vi.fn(),
  renderer: undefined as unknown,
  device: {
    isFetchingConfigs: false,
    canFetchConfigs: false,
    handleFetchConfigs: () => undefined,
    canExecuteCommands: false,
    isExecutingCommands: false,
    executeHint: "",
    handleExecuteCommands: () => undefined,
  },
  save: { handleSave: () => undefined, handleExport: () => undefined, isSaving: false },
}));
mocks.renderer = { render: mocks.render };

vi.mock("next/navigation", () => ({
  useRouter: () => mocks.router,
  useSearchParams: () => mocks.params,
}));
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall: vi.fn() }) }));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/hooks/queries/use-device-attributes-query", () => ({
  useDeviceAttributesQuery: (args: unknown) => (mocks.attributesQueryArgs(args), mocks.attributes),
}));
vi.mock("@/hooks/queries/use-nautobot-source-credentials", () => ({
  useNautobotSourceCredentials: (args: unknown) => (mocks.credentialsArgs(args), mocks.credentials),
}));
vi.mock("@/hooks/queries/use-workflow-query", () => ({
  useWorkflowQuery: () => mocks.referenceWorkflow,
}));
vi.mock("@/hooks/queries/use-workflows-query", () => ({
  useWorkflowsQuery: () => mocks.workflows,
}));
vi.mock("./use-nautobot-sources", () => ({
  useNautobotSources: () => ({ sources: mocks.sources }),
}));
vi.mock("./use-template-query", () => ({ useTemplateQuery: () => mocks.template }));
vi.mock("./use-template-render", () => ({
  useTemplateRender: () => mocks.renderer,
}));
vi.mock("./use-template-editor-device", () => ({
  useTemplateEditorDevice: (args: unknown) => {
    mocks.deviceHook(args);
    return mocks.device;
  },
}));
vi.mock("./use-template-editor-save", () => ({
  useTemplateEditorSave: (args: unknown) => {
    mocks.saveHook(args);
    return mocks.save;
  },
}));

const device: DeviceSummary = {
  id: "dev-1",
  name: "sw1",
  primary_ip4: "10.0.0.1/24",
  platform: "ios",
  network_driver: "cisco_ios",
} as DeviceSummary;

function template(overrides: Record<string, unknown> = {}) {
  return {
    id: 7,
    name: "Loaded",
    description: "desc",
    notes: "notes",
    category: "netmiko",
    template_type: "textfsm",
    content: "show ver",
    pre_run_commands: ["show ver"],
    pre_run_use_textfsm: true,
    nautobot_attributes: ["interfaces"],
    credential_id: 3,
    variables: { site: { value: "lab", type: "custom" } },
    batfish_config: null,
    ...overrides,
  };
}

beforeEach(() => {
  mocks.params = new URLSearchParams();
  mocks.router.replace.mockReset();
  mocks.template = { data: undefined, isLoading: false };
  mocks.sources = [];
  mocks.credentials = { sourceId: undefined, isReady: false };
  mocks.attributes = { data: undefined, error: null };
  mocks.workflows = { data: undefined };
  mocks.referenceWorkflow = { data: undefined };
  for (const spy of [mocks.attributesQueryArgs, mocks.credentialsArgs, mocks.deviceHook, mocks.saveHook, mocks.render]) {
    spy.mockClear();
  }
});

function setup() {
  const { wrapper } = createQueryWrapper();
  return renderHook(() => useTemplateEditor(), { wrapper });
}

type Hook = ReturnType<typeof setup>["result"];

const variable = (result: Hook, name: string) =>
  result.current.variableManager.variables.find((v) => v.name === name);
const names = (result: Hook) => result.current.variableManager.variables.map((v) => v.name);

describe("edit mode", () => {
  it("is off for a new template", () => {
    const { result } = setup();
    expect(result.current).toMatchObject({ isEditMode: false, templateId: null, isLoading: false });
  });

  it("reads the template id from the URL and loads while the template is fetched", () => {
    mocks.params = new URLSearchParams("id=7");
    mocks.template = { data: undefined, isLoading: true };
    const { result } = setup();
    expect(result.current).toMatchObject({ isEditMode: true, templateId: 7, isLoading: true });
  });

  // `?id=abc` must not be sent to the API as template "NaN".
  it.each(["abc", "1.5", "0", "-3", ""])("treats the id %j as a new template", (id) => {
    mocks.params = new URLSearchParams(`id=${id}`);
    const { result } = setup();
    expect(result.current.isEditMode).toBe(false);
    expect(result.current.templateId).toBeNull();
  });
});

describe("loading an existing template", () => {
  beforeEach(() => {
    mocks.params = new URLSearchParams("id=7");
  });

  it("fills every field once", () => {
    mocks.template = { data: template(), isLoading: false };
    const { result } = setup();
    expect(result.current).toMatchObject({
      name: "Loaded",
      description: "desc",
      notes: "notes",
      templateType: "textfsm",
      content: "show ver",
      commands: ["show ver"],
      useTextfsm: true,
      attributes: ["interfaces"],
      credentialId: "3",
    });
    expect(variable(result, "site")?.value).toBe("lab");
  });

  it("uses defaults for missing optional fields", () => {
    mocks.template = {
      data: template({
        description: null,
        notes: null,
        template_type: null,
        content: null,
        pre_run_commands: null,
        pre_run_use_textfsm: null,
        nautobot_attributes: null,
        credential_id: null,
        variables: null,
      }),
      isLoading: false,
    };
    const { result } = setup();
    expect(result.current).toMatchObject({
      description: "",
      notes: "",
      templateType: "jinja2",
      content: "",
      commands: [],
      useTextfsm: false,
      attributes: [],
      credentialId: "none",
    });
  });

  it("does not overwrite the user's edits when the template is refetched", () => {
    mocks.template = { data: template(), isLoading: false };
    const { result, rerender } = setup();
    act(() => result.current.setName("My edit"));

    mocks.template = { data: template({ name: "Server rename" }), isLoading: false };
    rerender();

    expect(result.current.name).toBe("My edit");
  });

  it("hands a report template to the report editor and does not load it here", () => {
    mocks.template = { data: template({ category: "report", id: 12 }), isLoading: false };
    const { result } = setup();
    expect(mocks.router.replace).toHaveBeenCalledWith("/templates/report-editor?id=12");
    expect(result.current.name).toBe("");
  });
});

describe("derived variables", () => {
  it("shows the command variables only while a command is configured", () => {
    const { result } = setup();
    expect(names(result)).not.toContain("commands");

    act(() => result.current.setCommands(["show ver"]));
    expect(names(result)).toContain("commands");

    act(() => result.current.setCommands(["  ", ""]));
    expect(names(result)).not.toContain("commands");
  });

  it("shows `parsed` for Get Configs, and hides it again", () => {
    const { result } = setup();
    act(() => result.current.setGetDeviceConfigs(true));
    expect(names(result)).toContain("parsed");
    act(() => result.current.setGetDeviceConfigs(false));
    expect(names(result)).not.toContain("parsed");
  });

  it("shows `parsed` (not `batfish`) for a Batfish facts question, and `batfish` for a preview question", () => {
    const { result } = setup();
    act(() => {
      result.current.setBatfishEnabled(true);
      result.current.setBatfishQuestion("ospfFacts");
    });
    expect(names(result)).toContain("parsed");
    expect(names(result)).not.toContain("batfish");

    act(() => result.current.setBatfishQuestion("routes"));
    expect(names(result)).toContain("batfish");
    expect(names(result)).not.toContain("parsed");
  });

  it("keeps `parsed` while Get Configs is on even if Batfish is switched to a preview question", () => {
    const { result } = setup();
    act(() => {
      result.current.setGetDeviceConfigs(true);
      result.current.setBatfishEnabled(true);
      result.current.setBatfishQuestion("routes");
    });
    expect(names(result)).toContain("parsed");
    expect(names(result)).toContain("batfish");
  });

  it("builds the device variable from the test device, without the prefix length", () => {
    const { result } = setup();
    act(() => result.current.setSelectedDevice(device));
    expect(JSON.parse(variable(result, "device")!.value)).toMatchObject({
      name: "sw1",
      hostname: "sw1",
      id: "dev-1",
      primary_ip4: "10.0.0.1",
      platform: "ios",
      network_driver: "cisco_ios",
      source_id: "dev-1",
    });

    act(() => result.current.setSelectedDevice(null));
    expect(variable(result, "device")?.value).toBe("");
  });

  it("tolerates a device without ip, platform and driver", () => {
    const { result } = setup();
    act(() => result.current.setSelectedDevice({ id: "d", name: "n" } as DeviceSummary));
    expect(JSON.parse(variable(result, "device")!.value)).toMatchObject({
      primary_ip4: "",
      platform: "",
      network_driver: "",
    });
  });

  it("mirrors the device attributes into the nautobot variable", () => {
    mocks.attributes = { data: { role: "core" }, error: null };
    const { result } = setup();
    act(() => result.current.setSelectedDevice(device));
    expect(JSON.parse(variable(result, "nautobot")!.value)).toEqual({ role: "core" });

    act(() => result.current.setSelectedDevice(null));
    expect(variable(result, "nautobot")?.value).toBe("");
  });

  it("uses an empty object when the attributes could not be fetched", () => {
    mocks.attributes = { data: undefined, error: new Error("403") };
    const { result } = setup();
    act(() => result.current.setSelectedDevice(device));
    expect(JSON.parse(variable(result, "nautobot")!.value)).toEqual({});
  });

  it("previews the run parameters of the linked reference workflow", () => {
    mocks.referenceWorkflow = {
      data: { name: "Backup", static_attributes: [{ name: "site", type: "string", required: true, default: "lab" }] },
    };
    const { result } = setup();
    act(() => result.current.setReferenceWorkflowId(5));
    expect(JSON.parse(variable(result, "run_input")!.value)).toEqual({ site: "lab" });

    act(() => result.current.setReferenceWorkflowId(null));
    expect(names(result)).not.toContain("run_input");
  });

  it("waits for the reference workflow before showing run_input", () => {
    mocks.referenceWorkflow = { data: undefined };
    const { result } = setup();
    act(() => result.current.setReferenceWorkflowId(5));
    expect(names(result)).not.toContain("run_input");
  });
});

describe("test source", () => {
  it("falls back to the first configured source until another is picked", () => {
    mocks.sources = [{ sourceId: "nb-1" }, { sourceId: "nb-2" }];
    const { result } = setup();
    expect(result.current.effectiveSourceId).toBe("nb-1");

    act(() => result.current.setSourceId("nb-2"));
    expect(result.current.effectiveSourceId).toBe("nb-2");
  });

  it("is empty when no source exists and does not ask for credentials", () => {
    const { result } = setup();
    expect(result.current.effectiveSourceId).toBe("");
    expect(mocks.credentialsArgs).toHaveBeenLastCalledWith({ sourceId: undefined, enabled: false });
  });

  it("only fetches device attributes once the source is ready", () => {
    mocks.sources = [{ sourceId: "nb-1" }];
    mocks.credentials = { sourceId: "nb-1", isReady: true };
    const { result } = setup();
    act(() => result.current.setSelectedDevice(device));
    expect(mocks.attributesQueryArgs).toHaveBeenLastCalledWith({
      deviceId: "dev-1",
      sourceId: "nb-1",
      attributes: [],
      enabled: true,
    });
    expect(result.current.sourceReady).toBe(true);
  });
});

describe("variables panel actions", () => {
  it("selects the variable it just added", () => {
    const { result } = setup();
    act(() => result.current.handleAddVariable("site", "lab"));
    const added = variable(result, "site")!;
    expect(result.current.selectedVariableId).toBe(added.id);
  });

  it("merges loaded variables using the chosen mode", () => {
    const { result } = setup();
    act(() => result.current.handleAddVariable("a", "old"));
    act(() => result.current.handleLoadVariables([{ name: "a", value: "new" }, { name: "b", value: "2" }], "skip"));
    expect(variable(result, "a")?.value).toBe("old");
    expect(variable(result, "b")?.value).toBe("2");
  });

  it("lists variable names, and which of them are automatic", () => {
    const { result } = setup();
    act(() => result.current.handleAddVariable("custom_one", "1"));
    expect(result.current.existingVariableNames).toEqual(["device", "nautobot", "custom_one"]);
    expect(result.current.autoVariableNames).toEqual(["device", "nautobot"]);
  });

  it("renders the content with the current variables", () => {
    const { result } = setup();
    act(() => result.current.setContent("hello {{ site }}"));
    act(() => result.current.handleRender());
    expect(mocks.render).toHaveBeenCalledWith("hello {{ site }}", result.current.variableManager.variables);
  });
});

describe("saving", () => {
  it("passes the editor state, the trimmed commands and the batfish config to the save hook", () => {
    mocks.params = new URLSearchParams("id=7");
    const { result } = setup();
    act(() => {
      result.current.setName("N");
      result.current.setCommands([" show ver ", "", "  "]);
      result.current.setCredentialId("4");
    });
    expect(mocks.saveHook).toHaveBeenLastCalledWith(
      expect.objectContaining({
        name: "N",
        cleanedCommands: ["show ver"],
        credentialId: "4",
        isEditMode: true,
        templateId: 7,
        batfishConfig: expect.objectContaining({ enabled: false, question: "routes" }),
      }),
    );
    expect(result.current.cleanedCommandCount).toBe(1);
  });
});

describe("referential stability", () => {
  it("returns the same object when nothing changed", () => {
    const { result, rerender } = setup();
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });
});
