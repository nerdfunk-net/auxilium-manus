import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryWrapper } from "@/test/query-wrapper";

import { useDeviceFilter } from "./use-device-filter";

const h = vi.hoisted(() => ({ apiCall: vi.fn() }));
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall: h.apiCall }) }));

const SERVER_OPERATORS = [
  { value: "equals", label: "Equals" },
  { value: "contains", label: "Contains" },
  { value: "not_equals", label: "Not Equals" },
];

const READY = { sourceId: "src-1", sourceReady: true };
const NOT_READY = { sourceId: "src-1", sourceReady: false };

function route(url: string) {
  if (url.startsWith("sources/nautobot/field-options")) {
    return Promise.resolve({
      fields: [{ value: "location", label: "Location" }],
      operators: SERVER_OPERATORS,
    });
  }
  if (url.startsWith("sources/nautobot/custom-fields")) {
    return Promise.resolve({ custom_fields: [{ name: "owner", label: "Owner" }] });
  }
  const match = /field-values\/([^?]+)/.exec(url);
  if (match) {
    const field = decodeURIComponent(match[1]);
    return Promise.resolve({ field, values: [`${field}-a`, `${field}-b`], input_type: "text" });
  }
  return Promise.reject(new Error(`unexpected ${url}`));
}

function setup(options = READY) {
  const { wrapper } = createQueryWrapper();
  return renderHook(() => useDeviceFilter(options), { wrapper });
}

const fieldValueCalls = () =>
  h.apiCall.mock.calls.filter(([url]) => String(url).includes("field-values/"));

beforeEach(() => {
  h.apiCall.mockReset();
  h.apiCall.mockImplementation((url: string) => route(url));
});

describe("useDeviceFilter", () => {
  it("starts empty and offers the server operators", async () => {
    const { result } = setup();
    await waitFor(() => expect(result.current.fieldOptions).toHaveLength(1));
    expect(result.current.currentField).toBe("");
    expect(result.current.currentOperator).toBe("equals");
    expect(result.current.operatorOptions).toEqual(SERVER_OPERATORS);
  });

  it("returns the same object when nothing changed", async () => {
    const { result, rerender } = setup();
    await waitFor(() => expect(result.current.fieldOptions).toHaveLength(1));
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });

  it("loads the values of a normal field and clears the typed value", async () => {
    const { result } = setup();
    act(() => result.current.setCurrentValue("old"));
    act(() => result.current.handleFieldChange("location"));
    expect(result.current.currentValue).toBe("");
    await waitFor(() =>
      expect(result.current.fieldValues).toEqual([
        { value: "location-a", label: "location-a" },
        { value: "location-b", label: "location-b" },
      ]),
    );
  });

  it("does not load values for fields that take free input", async () => {
    const { result } = setup();
    for (const field of ["has_primary", "ip_prefix", "primary_prefix"]) {
      act(() => result.current.handleFieldChange(field));
    }
    await waitFor(() => expect(result.current.currentField).toBe("primary_prefix"));
    expect(fieldValueCalls()).toHaveLength(0);
  });

  it("does not load values while the source is not ready", async () => {
    const { result } = setup(NOT_READY);
    act(() => result.current.handleFieldChange("location"));
    await Promise.resolve();
    expect(fieldValueCalls()).toHaveLength(0);
  });

  it("forces the operator a field requires and restricts the choices", () => {
    const { result } = setup();
    act(() => result.current.handleFieldChange("ip_prefix"));
    expect(result.current.currentOperator).toBe("within_include");
    expect(result.current.operatorOptions.map((o) => o.value)).toEqual([
      "within_include",
      "within",
      "exact",
    ]);
  });

  it("resets an operator the next field does not offer", () => {
    const { result } = setup();
    act(() => result.current.handleFieldChange("ip_prefix"));
    expect(result.current.currentOperator).toBe("within_include");
    act(() => result.current.handleFieldChange("name"));
    expect(result.current.operatorOptions.map((o) => o.value)).toEqual(["equals", "contains"]);
    expect(result.current.currentOperator).toBe("equals");
  });

  it("resets 'contains' when the next field only offers exact matches", () => {
    const { result } = setup();
    act(() => result.current.handleFieldChange("name"));
    act(() => result.current.handleOperatorChange("contains"));
    act(() => result.current.handleFieldChange("location"));
    expect(result.current.operatorOptions.map((o) => o.value)).toEqual(["equals", "not_equals"]);
    expect(result.current.currentOperator).toBe("equals");
  });

  it("resets against the server operators when the next field has no rule of its own", async () => {
    const { result } = setup();
    await waitFor(() => expect(result.current.fieldOptions).toHaveLength(1));
    act(() => result.current.handleFieldChange("ip_prefix"));
    act(() => result.current.handleFieldChange("serial"));
    expect(result.current.operatorOptions).toEqual(SERVER_OPERATORS);
    expect(result.current.currentOperator).toBe("equals");
  });

  it("resets a rule-specific operator even before the server operator list has loaded", () => {
    // The field-options request never answers: there is no server list to check against.
    h.apiCall.mockImplementation((url: string) =>
      url.startsWith("sources/nautobot/field-options") ? new Promise(() => {}) : route(url),
    );
    const { result } = setup();
    act(() => result.current.handleFieldChange("ip_prefix"));
    expect(result.current.currentOperator).toBe("within_include");
    act(() => result.current.handleFieldChange("serial"));
    expect(result.current.currentOperator).toBe("equals");
  });

  it("keeps an operator that the next field still offers", () => {
    const { result } = setup();
    act(() => result.current.handleFieldChange("role"));
    act(() => result.current.handleOperatorChange("not_equals"));
    act(() => result.current.handleFieldChange("location"));
    expect(result.current.currentOperator).toBe("not_equals");
  });

  it("drops the previous field's values when custom_fields is picked", async () => {
    const { result } = setup();
    act(() => result.current.handleFieldChange("location"));
    await waitFor(() => expect(result.current.fieldValues).toHaveLength(2));
    act(() => result.current.handleFieldChange("custom_fields"));
    expect(result.current.currentField).toBe("custom_fields");
    expect(result.current.fieldValues).toEqual([]);
  });

  it("loads custom fields once custom_fields is picked and selects one", async () => {
    const { result } = setup();
    act(() => result.current.handleFieldChange("custom_fields"));
    await waitFor(() => expect(result.current.customFields).toHaveLength(1));
    act(() => result.current.handleCustomFieldSelect("cf_owner"));
    expect(result.current.selectedCustomField).toBe("owner");
    expect(result.current.currentField).toBe("cf_owner");
    expect(result.current.operatorOptions.map((o) => o.value)).toEqual(["equals", "contains"]);
    await waitFor(() => expect(result.current.fieldValues).toHaveLength(2));
    expect(fieldValueCalls().at(-1)?.[0]).toContain("field-values/cf_owner");
  });

  it("clears the custom field values when the selection is emptied", async () => {
    const { result } = setup();
    act(() => result.current.handleFieldChange("custom_fields"));
    act(() => result.current.handleCustomFieldSelect("cf_owner"));
    await waitFor(() => expect(result.current.fieldValues).toHaveLength(2));
    act(() => result.current.handleCustomFieldSelect(""));
    expect(result.current.fieldValues).toEqual([]);
  });

  it("clears a custom field selection when another field is picked", () => {
    const { result } = setup();
    act(() => result.current.handleFieldChange("custom_fields"));
    act(() => result.current.handleCustomFieldSelect("cf_owner"));
    act(() => result.current.handleFieldChange("location"));
    expect(result.current.selectedCustomField).toBe("");
  });
});
