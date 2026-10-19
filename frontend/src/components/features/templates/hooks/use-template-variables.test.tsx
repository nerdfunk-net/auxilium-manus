import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BatfishQueryResult, CommandEntry } from "../types";
import { useTemplateVariables } from "./use-template-variables";

function setup() {
  return renderHook(() => useTemplateVariables());
}

type Hook = ReturnType<typeof setup>["result"];

const names = (result: Hook) => result.current.variables.map((v) => v.name);
const byId = (result: Hook, id: string) => result.current.variables.find((v) => v.id === id);
const parsedValue = (result: Hook) => {
  const raw = byId(result, "auto:parsed")?.value;
  return raw ? JSON.parse(raw) : null;
};

const command = (name: string, extra: Partial<CommandEntry> = {}): CommandEntry => ({
  node_id: "n1",
  name,
  success: true,
  raw: `${name} output`,
  parsed: null,
  ...extra,
});

describe("initial variables", () => {
  it("starts with the always-present auto variables only", () => {
    const { result } = setup();
    expect(names(result)).toEqual(["device", "nautobot"]);
    expect(result.current.variables.every((v) => v.isAutoFilled && v.type === "auto")).toBe(true);
  });
});

describe("custom variables", () => {
  it("adds a custom variable with a unique id and returns the id", () => {
    const { result } = setup();
    let first = "";
    let second = "";
    act(() => {
      first = result.current.addVariable("site", "lab");
      second = result.current.addVariable("site", "lab");
    });
    expect(first).not.toBe(second);
    expect(byId(result, first)).toMatchObject({ name: "site", value: "lab", type: "custom", isAutoFilled: false });
  });

  it("uses the given type", () => {
    const { result } = setup();
    let id = "";
    act(() => {
      id = result.current.addVariable("x", "1", "secret");
    });
    expect(byId(result, id)?.type).toBe("secret");
  });

  it("updates the value of one variable only", () => {
    const { result } = setup();
    let a = "";
    let b = "";
    act(() => {
      a = result.current.addVariable("a", "1");
      b = result.current.addVariable("b", "2");
    });
    act(() => result.current.updateVariableValue(a, "changed"));
    expect(byId(result, a)?.value).toBe("changed");
    expect(byId(result, b)?.value).toBe("2");
  });

  it("removes a variable by id", () => {
    const { result } = setup();
    let id = "";
    act(() => {
      id = result.current.addVariable("a", "1");
    });
    act(() => result.current.removeVariable(id));
    expect(names(result)).toEqual(["device", "nautobot"]);
  });
});

describe("device and nautobot variables", () => {
  it("serialises the device info and clears it with null", () => {
    const { result } = setup();
    act(() => result.current.setDeviceInfo({ name: "sw1" }));
    expect(JSON.parse(byId(result, "auto:device")!.value)).toEqual({ name: "sw1" });
    act(() => result.current.setDeviceInfo(null));
    expect(byId(result, "auto:device")?.value).toBe("");
  });

  it("serialises the nautobot attributes and clears them when falsy", () => {
    const { result } = setup();
    act(() => result.current.setNautobotAttributes({ role: "core" }));
    expect(JSON.parse(byId(result, "auto:nautobot")!.value)).toEqual({ role: "core" });
    act(() => result.current.setNautobotAttributes(undefined));
    expect(byId(result, "auto:nautobot")?.value).toBe("");
  });
});

describe("command variables", () => {
  it("adds them once when enabled and removes them when disabled", () => {
    const { result } = setup();
    act(() => result.current.toggleCommandVariables(true));
    act(() => result.current.toggleCommandVariables(true));
    expect(names(result)).toEqual(["device", "nautobot", "command", "commands", "commands_by_name"]);

    act(() => result.current.toggleCommandVariables(false));
    expect(names(result)).toEqual(["device", "nautobot"]);
  });

  it("disabling when they are absent changes nothing", () => {
    const { result } = setup();
    const before = result.current.variables;
    act(() => result.current.toggleCommandVariables(false));
    expect(result.current.variables).toBe(before);
  });

  it("fills command, commands and commands_by_name from the results (last one is `command`)", () => {
    const { result } = setup();
    act(() => result.current.toggleCommandVariables(true));
    const entries = [command("show ver"), command("show ip int br")];

    act(() => result.current.setCommandResults(entries));

    expect(JSON.parse(byId(result, "auto:commands")!.value)).toEqual(entries);
    expect(Object.keys(JSON.parse(byId(result, "auto:commands_by_name")!.value))).toEqual([
      "show ver",
      "show ip int br",
    ]);
    expect(JSON.parse(byId(result, "auto:command")!.value).name).toBe("show ip int br");
  });

  it("clears `command` for an empty result list", () => {
    const { result } = setup();
    act(() => result.current.toggleCommandVariables(true));
    act(() => result.current.setCommandResults([command("x")]));
    act(() => result.current.setCommandResults([]));
    expect(byId(result, "auto:command")?.value).toBe("");
    expect(byId(result, "auto:commands")?.value).toBe("[]");
  });

  it("keeps only the last entry when two commands share a name", () => {
    const { result } = setup();
    act(() => result.current.toggleCommandVariables(true));
    act(() =>
      result.current.setCommandResults([command("x", { raw: "first" }), command("x", { raw: "second" })]),
    );
    expect(JSON.parse(byId(result, "auto:commands_by_name")!.value).x.raw).toBe("second");
  });

  it("is a no-op for the values when the command variables are disabled", () => {
    const { result } = setup();
    act(() => result.current.setCommandResults([command("x")]));
    expect(names(result)).toEqual(["device", "nautobot"]);
  });
});

describe("parsed config variable", () => {
  it("is added and removed by the toggle", () => {
    const { result } = setup();
    act(() => result.current.toggleParsedConfigVariable(true));
    expect(names(result)).toContain("parsed");
    act(() => result.current.toggleParsedConfigVariable(false));
    expect(names(result)).not.toContain("parsed");
  });

  it("merges named entries instead of replacing the whole value", () => {
    const { result } = setup();
    act(() => result.current.toggleParsedConfigVariable(true));
    act(() => result.current.setParsedConfig({ running: { hostname: "sw1" } }));
    act(() => result.current.setParsedNamespaceEntry("facts", { rows: 3 }));
    expect(parsedValue(result)).toEqual({
      cisco_config: { running: { hostname: "sw1" } },
      facts: { rows: 3 },
    });
  });

  it("removes a key when its entry is cleared and empties the value with the last one", () => {
    const { result } = setup();
    act(() => result.current.toggleParsedConfigVariable(true));
    act(() => result.current.setParsedNamespaceEntry("a", 1));
    act(() => result.current.setParsedNamespaceEntry("b", 2));
    act(() => result.current.clearParsedNamespaceEntry("a"));
    expect(parsedValue(result)).toEqual({ b: 2 });
    act(() => result.current.setParsedNamespaceEntry("b", undefined));
    expect(byId(result, "auto:parsed")?.value).toBe("");
  });

  it("starts over when the current value is not a JSON object", () => {
    const { result } = setup();
    act(() => result.current.toggleParsedConfigVariable(true));
    act(() => result.current.updateVariableValue("auto:parsed", "not json"));
    act(() => result.current.setParsedNamespaceEntry("a", 1));
    expect(parsedValue(result)).toEqual({ a: 1 });

    act(() => result.current.updateVariableValue("auto:parsed", "[1,2]"));
    act(() => result.current.setParsedNamespaceEntry("b", 2));
    expect(parsedValue(result)).toEqual({ b: 2 });
  });

  it("keeps falsy but valid entries (0, false, empty string)", () => {
    const { result } = setup();
    act(() => result.current.toggleParsedConfigVariable(true));
    act(() => {
      result.current.setParsedNamespaceEntry("zero", 0);
      result.current.setParsedNamespaceEntry("no", false);
      result.current.setParsedNamespaceEntry("empty", "");
    });
    expect(parsedValue(result)).toEqual({ zero: 0, no: false, empty: "" });
  });

  it("does nothing while the variable is disabled", () => {
    const { result } = setup();
    act(() => result.current.setParsedConfig({ a: 1 }));
    expect(names(result)).toEqual(["device", "nautobot"]);
  });
});

describe("batfish variable", () => {
  const answer = { success: true, question: "q", network: "n", snapshot: "s", rows: [] } as BatfishQueryResult;

  it("is added and removed by the toggle and carries the result", () => {
    const { result } = setup();
    act(() => result.current.toggleBatfishVariable(true));
    expect(names(result)).toContain("batfish");

    act(() => result.current.setBatfishResult(answer));
    expect(JSON.parse(byId(result, "auto:batfish")!.value)).toEqual(answer);

    act(() => result.current.setBatfishResult(null));
    expect(byId(result, "auto:batfish")?.value).toBe("");

    act(() => result.current.toggleBatfishVariable(false));
    expect(names(result)).not.toContain("batfish");
  });
});

describe("run_input preview", () => {
  const source = {
    workflowName: "Backup",
    attributes: [
      { name: "site", type: "string", required: true, default: "lab" },
      { name: "device_list", type: "string", required: true },
    ],
  } as never;

  it("previews the declared attributes with their defaults (null when none)", () => {
    const { result } = setup();
    act(() => result.current.setRunInputSource(source));
    const variable = byId(result, "auto:run_input")!;
    expect(JSON.parse(variable.value)).toEqual({ site: "lab", device_list: null });
    expect(variable.description).toContain('"Backup"');
  });

  it("replaces the previous preview instead of duplicating it, and null removes it", () => {
    const { result } = setup();
    act(() => result.current.setRunInputSource(source));
    act(() => result.current.setRunInputSource(source));
    expect(names(result).filter((n) => n === "run_input")).toHaveLength(1);

    act(() => result.current.setRunInputSource(null));
    expect(names(result)).not.toContain("run_input");
  });
});

describe("mergeCustomVariables", () => {
  it("adds new variables", () => {
    const { result } = setup();
    act(() => result.current.mergeCustomVariables([{ name: "a", value: "1" }, { name: "b", value: "2" }], "skip"));
    expect(result.current.variables.filter((v) => !v.isAutoFilled).map((v) => [v.name, v.value])).toEqual([
      ["a", "1"],
      ["b", "2"],
    ]);
  });

  it("skip keeps an existing value, overwrite replaces it", () => {
    const { result } = setup();
    act(() => result.current.addVariable("a", "old"));

    act(() => result.current.mergeCustomVariables([{ name: "a", value: "new" }], "skip"));
    expect(result.current.variables.find((v) => v.name === "a")?.value).toBe("old");

    act(() => result.current.mergeCustomVariables([{ name: "a", value: "new" }], "overwrite"));
    expect(result.current.variables.find((v) => v.name === "a")?.value).toBe("new");
  });

  it("never touches an auto variable, even in overwrite mode", () => {
    const { result } = setup();
    act(() => result.current.mergeCustomVariables([{ name: "device", value: "x" }], "overwrite"));
    expect(byId(result, "auto:device")?.value).toBe("");
    expect(names(result).filter((n) => n === "device")).toHaveLength(1);
  });

  it("ignores entries without a name", () => {
    const { result } = setup();
    act(() => result.current.mergeCustomVariables([{ name: "", value: "x" }], "skip"));
    expect(names(result)).toEqual(["device", "nautobot"]);
  });

  it("collapses a name repeated within one import to the first entry", () => {
    const { result } = setup();
    act(() =>
      result.current.mergeCustomVariables(
        [{ name: "a", value: "1" }, { name: "a", value: "2" }],
        "skip",
      ),
    );
    expect(result.current.variables.filter((v) => v.name === "a").map((v) => v.value)).toEqual(["1"]);
  });

  // The auto variables that are currently switched off are still reserved: importing a
  // custom variable with their name would collide as soon as the option is switched on.
  it.each(["command", "commands", "commands_by_name", "parsed", "batfish", "run_input"])(
    "does not create a custom variable named like the disabled auto variable %s",
    (reserved) => {
      const { result } = setup();
      act(() => result.current.mergeCustomVariables([{ name: reserved, value: "x" }], "skip"));
      expect(names(result)).not.toContain(reserved);
    },
  );
});

describe("loadCustomVariables", () => {
  it("replaces everything with the auto variables plus the template's custom ones", () => {
    const { result } = setup();
    act(() => {
      result.current.addVariable("stale", "1");
      result.current.toggleCommandVariables(true);
    });

    act(() =>
      result.current.loadCustomVariables({
        site: { value: "lab", type: "custom" },
        token: { value: "t", type: "secret" },
        bare: {} as never,
      }),
    );

    expect(names(result)).toEqual(["device", "nautobot", "site", "token", "bare"]);
    expect(byId(result, "auto:device")?.value).toBe("");
    const custom = result.current.variables.filter((v) => !v.isAutoFilled);
    expect(custom.map((v) => [v.value, v.type])).toEqual([
      ["lab", "custom"],
      ["t", "secret"],
      ["", "custom"],
    ]);
    expect(new Set(custom.map((v) => v.id)).size).toBe(3);
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
