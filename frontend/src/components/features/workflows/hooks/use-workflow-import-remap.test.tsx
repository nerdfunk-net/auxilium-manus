import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/lib/auth-store";

import { useWorkflowImportRemap } from "./use-workflow-import-remap";

type Loadable<T> = { data?: T; isLoading: boolean; isError?: boolean };

const queries = vi.hoisted(() => ({
  credentials: { data: undefined, isLoading: false } as Loadable<unknown>,
  git: { data: undefined, isLoading: false } as Loadable<unknown>,
  nautobot: { sources: [] as { sourceId: string }[], isLoading: false, isError: false },
  mattermost: { data: undefined, isLoading: false } as Loadable<unknown>,
  batfish: { data: undefined, isLoading: false } as Loadable<unknown>,
  pyats: { data: undefined, isLoading: false } as Loadable<unknown>,
}));

// Each mocked query hook records the options it was called with.
const calls = vi.hoisted(() => ({
  credentials: vi.fn(),
  git: vi.fn(),
  nautobot: vi.fn(),
  mattermost: vi.fn(),
  batfish: vi.fn(),
  pyats: vi.fn(),
}));

vi.mock(
  "@/components/features/settings/credentials/hooks/use-credentials-query",
  () => ({
    useCredentialsQuery: (options: unknown) => (calls.credentials(options), queries.credentials),
  }),
);
vi.mock("@/hooks/queries/use-git-repositories-query", () => ({
  useGitRepositoriesQuery: (options: unknown) => (calls.git(options), queries.git),
}));
vi.mock("@/components/features/templates/hooks/use-nautobot-sources", () => ({
  useNautobotSources: (options: unknown) => (calls.nautobot(options), queries.nautobot),
}));
vi.mock("@/hooks/queries/use-mattermost-sources-query", () => ({
  useMattermostSourcesQuery: (options: unknown) => (calls.mattermost(options), queries.mattermost),
}));
vi.mock("@/hooks/queries/use-batfish-sources-query", () => ({
  useBatfishSourcesQuery: (options: unknown) => (calls.batfish(options), queries.batfish),
}));
vi.mock("@/hooks/queries/use-pyats-sources-query", () => ({
  usePyATSSourcesQuery: (options: unknown) => (calls.pyats(options), queries.pyats),
}));

const idle = { data: undefined, isLoading: false, isError: false };

beforeEach(() => {
  Object.values(calls).forEach((spy) => spy.mockClear());
  queries.credentials = { ...idle };
  queries.git = { ...idle };
  queries.nautobot = { sources: [], isLoading: false, isError: false };
  queries.mattermost = { ...idle };
  queries.batfish = { ...idle };
  queries.pyats = { ...idle };
  useAuthStore.setState({ user: { username: "me" } as never });
});

type Node = Record<string, unknown>;
const node = (kind: string, pluginConfig: Record<string, unknown>): Node => ({
  id: kind,
  data: { kind, pluginConfig },
});

function setup(
  canvasNodes: Node[][],
  options: { enabled?: boolean; refs?: never[][] } = {},
) {
  const props = {
    canvasNodesList: canvasNodes,
    credentialReferencesList: options.refs ?? canvasNodes.map(() => []),
    enabled: options.enabled ?? true,
  };
  return renderHook(() => useWorkflowImportRemap(props));
}

describe("with nothing to remap", () => {
  it("reports no requirements and is trivially complete", () => {
    const { result } = setup([[node("run-command", {})]]);
    expect(result.current.hasAnyRequirements).toBe(false);
    expect(result.current.allSelected).toBe(true);
    expect(result.current.isLoading).toBe(false);
  });
});

describe("credentials", () => {
  const nodes = [[node("run-command", { credential_reference: "lab" })]];

  it("requires a remap for a credential that is not visible and starts incomplete", () => {
    const { result } = setup(nodes);
    expect(result.current.credential.requirements).toMatchObject([
      { name: "lab", credentialType: "ssh" },
    ]);
    expect(result.current.hasAnyRequirements).toBe(true);
    expect(result.current.allSelected).toBe(false);
  });

  it("does not require a remap for a visible global credential", () => {
    queries.credentials = {
      data: { credentials: [{ name: "lab", visibility: "global" }] },
      isLoading: false,
    };
    const { result } = setup(nodes);
    expect(result.current.credential.requirements).toEqual([]);
    expect(result.current.credential.credentials).toHaveLength(1);
  });

  it("is complete once a replacement is chosen, and passes it on in buildRemapArgs", () => {
    const { result } = setup(nodes);
    act(() => result.current.credential.onChange("lab", " other "));
    expect(result.current.allSelected).toBe(true);
    expect(result.current.buildRemapArgs().credentialRemap).toEqual(new Map([["lab", "other"]]));
  });

  it("does not count a blank choice as selected", () => {
    const { result } = setup(nodes);
    act(() => result.current.credential.onChange("lab", "   "));
    expect(result.current.allSelected).toBe(false);
    expect(result.current.buildRemapArgs().credentialRemap.size).toBe(0);
  });

  it("uses the signed-in username to decide about private credentials", () => {
    const refs = [[{ name: "lab", visibility: "private", owner_username: "me" }]] as never[][];
    queries.credentials = {
      data: { credentials: [{ name: "lab", visibility: "private" }] },
      isLoading: false,
    };
    expect(setup(nodes, { refs }).result.current.credential.requirements).toEqual([]);

    useAuthStore.setState({ user: { username: "someone-else" } as never });
    expect(setup(nodes, { refs }).result.current.credential.requirements).toHaveLength(1);
  });

  it("shows no requirements while credentials load, and is loading", () => {
    queries.credentials = { data: undefined, isLoading: true };
    const { result } = setup(nodes);
    expect(result.current.credential.requirements).toEqual([]);
    expect(result.current.credential.isLoading).toBe(true);
    expect(result.current.isLoading).toBe(true);
  });
});

describe("git repositories", () => {
  const nodes = [[node("git-step", { git_repository_id: 7 })]];

  it("requires a remap for an id that is missing here and offers the available repos", () => {
    queries.git = {
      data: { repositories: [{ id: 1, name: "configs", category: "device_configs" }] },
      isLoading: false,
    };
    const { result } = setup(nodes);
    expect(result.current.gitRepository.requirements).toEqual([{ id: 7 }]);
    expect(result.current.gitRepository.options).toEqual([
      { value: "1", label: "configs (device_configs)" },
    ]);
  });

  it("does not require a remap for an id that exists", () => {
    queries.git = {
      data: { repositories: [{ id: 7, name: "x", category: "c" }] },
      isLoading: false,
    };
    expect(setup(nodes).result.current.gitRepository.requirements).toEqual([]);
  });

  it("converts the chosen repository id to a number", () => {
    const { result } = setup(nodes);
    act(() => result.current.gitRepository.onChange("7", "12"));
    expect(result.current.allSelected).toBe(true);
    expect(result.current.buildRemapArgs().gitRepositoryRemap).toEqual(new Map([[7, 12]]));
  });
});

describe("sources", () => {
  const nodes = [
    [
      node("a", { nautobot_source_id: "nb-old" }),
      node("b", { mattermost_source_id: "mm-old" }),
      node("c", { batfish_source_id: "bf-old" }),
      node("d", { pyats_source_id: "py-old" }),
    ],
  ];

  it("requires a remap per source type for ids missing in this environment", () => {
    queries.nautobot = { sources: [{ sourceId: "nb-new" }], isLoading: false, isError: false };
    queries.mattermost = { data: { sources: [{ source_id: "mm-new" }] }, isLoading: false };
    const { result } = setup(nodes);
    const { sources } = result.current;

    expect(sources.nautobot.requirements).toEqual([{ sourceId: "nb-old" }]);
    expect(sources.nautobot.options).toEqual([{ value: "nb-new", label: "nb-new" }]);
    expect(sources.mattermost.requirements).toEqual([{ sourceId: "mm-old" }]);
    expect(sources.batfish.requirements).toEqual([{ sourceId: "bf-old" }]);
    expect(sources.pyats.requirements).toEqual([{ sourceId: "py-old" }]);
    expect(sources.batfish.options).toEqual([]);
  });

  it("does not require a remap for an id that exists", () => {
    queries.nautobot = { sources: [{ sourceId: "nb-old" }], isLoading: false, isError: false };
    expect(setup(nodes).result.current.sources.nautobot.requirements).toEqual([]);
  });

  it("keeps each type's selection separate", () => {
    const { result } = setup(nodes);
    act(() => result.current.sources.nautobot.onChange("nb-old", "nb-new"));
    expect(result.current.sources.nautobot.value).toEqual({ "nb-old": "nb-new" });
    expect(result.current.sources.mattermost.value).toEqual({});
    expect(result.current.allSelected).toBe(false);
  });

  it("is complete only when every type with a requirement has a choice", () => {
    const { result } = setup(nodes);
    act(() => {
      result.current.sources.nautobot.onChange("nb-old", "n");
      result.current.sources.mattermost.onChange("mm-old", "m");
      result.current.sources.batfish.onChange("bf-old", "b");
    });
    expect(result.current.allSelected).toBe(false);
    act(() => result.current.sources.pyats.onChange("py-old", "p"));
    expect(result.current.allSelected).toBe(true);

    const { sourceRemaps } = result.current.buildRemapArgs();
    expect(sourceRemaps.nautobot).toEqual(new Map([["nb-old", "n"]]));
    expect(sourceRemaps.pyats).toEqual(new Map([["py-old", "p"]]));
  });

  it("suppresses the requirements of a type that is still loading", () => {
    queries.batfish = { data: undefined, isLoading: true };
    const { result } = setup(nodes);
    expect(result.current.sources.batfish.requirements).toEqual([]);
    expect(result.current.sources.batfish.isLoading).toBe(true);
    expect(result.current.sources.pyats.requirements).toHaveLength(1);
  });
});

describe("enabled", () => {
  it.each([true, false])("is passed to every query hook (%s)", (enabled) => {
    setup([[node("run-command", {})]], { enabled });
    for (const spy of Object.values(calls)) {
      expect(spy).toHaveBeenCalledWith(expect.objectContaining({ enabled }));
    }
  });
});

describe("enabled=false", () => {
  it("reports no requirements even when references are missing", () => {
    const nodes = [
      [
        node("a", { credential_reference: "lab", git_repository_id: 7, nautobot_source_id: "x" }),
      ],
    ];
    const { result } = setup(nodes, { enabled: false });
    expect(result.current.hasAnyRequirements).toBe(false);
    expect(result.current.allSelected).toBe(true);
  });
});

describe("several files at once (gallery)", () => {
  it("combines the references of all files and de-duplicates them", () => {
    const { result } = setup([
      [node("a", { credential_reference: "lab", git_repository_id: 7 })],
      [node("b", { credential_reference: "lab", git_repository_id: 8 })],
    ]);
    expect(result.current.credential.requirements.map((r) => r.name)).toEqual(["lab"]);
    expect(result.current.gitRepository.requirements).toEqual([{ id: 7 }, { id: 8 }]);
  });
});

describe("resetRemapState", () => {
  it("clears every selection", () => {
    const { result } = setup([
      [
        node("a", {
          credential_reference: "lab",
          git_repository_id: 7,
          nautobot_source_id: "nb-old",
        }),
      ],
    ]);
    act(() => {
      result.current.credential.onChange("lab", "x");
      result.current.gitRepository.onChange("7", "1");
      result.current.sources.nautobot.onChange("nb-old", "y");
    });
    expect(result.current.allSelected).toBe(true);

    act(() => result.current.resetRemapState());

    expect(result.current.credential.value).toEqual({});
    expect(result.current.gitRepository.value).toEqual({});
    expect(result.current.sources.nautobot.value).toEqual({});
    expect(result.current.allSelected).toBe(false);
  });
});

describe("canProceed", () => {
  const credentialNodes = [[node("run-command", { credential_reference: "lab" })]];

  it("is true when nothing needs a replacement", () => {
    const { result } = setup([[node("run-command", {})]]);
    expect(result.current.canProceed).toBe(true);
    expect(result.current.isCheckingReferences).toBe(false);
  });

  // `hasAnyRequirements` stays false while a list loads; Import must not be allowed meanwhile.
  it("is false while a list the workflow depends on is still loading", () => {
    queries.credentials = { data: undefined, isLoading: true };
    const { result } = setup(credentialNodes);
    expect(result.current.hasAnyRequirements).toBe(false);
    expect(result.current.isCheckingReferences).toBe(true);
    expect(result.current.canProceed).toBe(false);
  });

  it("does not wait for lists the workflow has no references to", () => {
    queries.credentials = { data: undefined, isLoading: true };
    queries.pyats = { data: undefined, isLoading: true };
    const { result } = setup([[node("a", { git_repository_id: 7 })]]);
    queries.git = { data: { repositories: [{ id: 7, name: "x", category: "c" }] }, isLoading: false };
    expect(result.current.isCheckingReferences).toBe(false);
  });

  it.each([
    ["git", { git_repository_id: 7 }, "git"],
    ["nautobot", { nautobot_source_id: "nb" }, "nautobot"],
    ["mattermost", { mattermost_source_id: "mm" }, "mattermost"],
    ["batfish", { batfish_source_id: "bf" }, "batfish"],
    ["pyats", { pyats_source_id: "py" }, "pyats"],
  ] as const)("waits for the %s list when the workflow references it", (_name, config, query) => {
    if (query === "nautobot") {
      queries.nautobot = { sources: [], isLoading: true, isError: false };
    } else {
      queries[query] = { data: undefined, isLoading: true };
    }
    const { result } = setup([[node("a", config)]]);
    expect(result.current.canProceed).toBe(false);
  });

  it("becomes true once the lists settled and every requirement has a replacement", () => {
    const { result } = setup(credentialNodes);
    expect(result.current.canProceed).toBe(false);
    act(() => result.current.credential.onChange("lab", "other"));
    expect(result.current.canProceed).toBe(true);
  });

  it("is true while the dialog is closed", () => {
    queries.credentials = { data: undefined, isLoading: true };
    const { result } = setup(credentialNodes, { enabled: false });
    expect(result.current.canProceed).toBe(true);
  });
});

describe("loadFailed", () => {
  it("is false when the lists loaded", () => {
    const { result } = setup([[node("a", { credential_reference: "lab", git_repository_id: 7 })]]);
    expect(result.current.credential.loadFailed).toBe(false);
    expect(result.current.gitRepository.loadFailed).toBe(false);
    expect(result.current.sources.nautobot.loadFailed).toBe(false);
  });

  it("reports which list could not be fetched", () => {
    queries.credentials = { data: undefined, isLoading: false, isError: true };
    queries.git = { data: undefined, isLoading: false, isError: true };
    queries.nautobot = { sources: [], isLoading: false, isError: true };
    queries.batfish = { data: undefined, isLoading: false, isError: true };
    const { result } = setup([[node("a", { credential_reference: "lab" })]]);
    expect(result.current.credential.loadFailed).toBe(true);
    expect(result.current.gitRepository.loadFailed).toBe(true);
    expect(result.current.sources.nautobot.loadFailed).toBe(true);
    expect(result.current.sources.batfish.loadFailed).toBe(true);
    expect(result.current.sources.mattermost.loadFailed).toBe(false);
    expect(result.current.sources.pyats.loadFailed).toBe(false);
  });

  it("still requires a replacement when the credential list could not be loaded", () => {
    queries.credentials = { data: undefined, isLoading: false, isError: true };
    const { result } = setup([[node("a", { credential_reference: "lab" })]]);
    expect(result.current.credential.requirements).toHaveLength(1);
    expect(result.current.canProceed).toBe(false);
  });
});
