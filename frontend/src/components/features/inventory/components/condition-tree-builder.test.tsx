import { render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import type { ConditionItem, ConditionTree } from "../types/device-selector";
import { ALL_DEVICES_OR_MESSAGE } from "../utils/all-devices-conflicts";
import { ConditionTreeBuilder } from "./condition-tree-builder";

const item = (field: string, operator = "equals", value = "true"): ConditionItem => ({
  id: `${field}-${operator}`,
  field,
  operator,
  value,
});

const tree = (internalLogic: "AND" | "OR", ...items: ConditionItem[]): ConditionTree => ({
  type: "root",
  internalLogic,
  items,
});

function renderBuilder(conditionTree: ConditionTree, currentField = "") {
  const noop = vi.fn();
  const props = {
    conditionTree,
    setConditionTree: noop,
    currentGroupPath: [],
    setCurrentGroupPath: noop,
    addConditionToTree: noop,
    addGroup: noop,
    removeItemFromTree: noop,
    updateGroupLogic: noop,
    findGroupPath: () => null,
    currentField,
    setCurrentField: noop,
    currentOperator: "equals",
    setCurrentOperator: noop,
    currentValue: currentField === "all_devices" ? "true" : "",
    setCurrentValue: noop,
    currentLogic: "AND",
    setCurrentLogic: noop,
    currentNegate: false,
    setCurrentNegate: noop,
    fieldOptions: [
      { value: "all_devices", label: "All Devices" },
      { value: "location", label: "Location" },
    ],
    operatorOptions: [{ value: "equals", label: "Equals" }],
    fieldValues: [],
    customFields: [],
    handleFieldChange: noop,
    handleOperatorChange: noop,
    handleCustomFieldSelect: noop,
    selectedCustomField: "",
    isLoadingFieldValues: false,
    isLoadingCustomFields: false,
    sourceReady: true,
    onPreview: noop,
    isLoadingPreview: false,
    showActions: true,
    showSaveLoad: true,
    loadedInventoryName: "inv",
    onSaveCurrent: noop,
    isSavingCurrent: false,
    onOpenSaveAsModal: noop,
    onOpenLoadModal: noop,
    onOpenManageModal: noop,
    onShowHelp: noop,
    onShowLogicalTree: noop,
    selectionMode: false,
    onToggleSelectionMode: noop,
  };
  return render(<ConditionTreeBuilder {...(props as unknown as ComponentProps<typeof ConditionTreeBuilder>)} />);
}

const button = (name: RegExp) => screen.getByRole("button", { name }) as HTMLButtonElement;

describe("ConditionTreeBuilder with All Devices", () => {
  it("lets All Devices AND an exclusion be previewed and saved", () => {
    renderBuilder(tree("AND", item("all_devices"), item("location", "not_equals", "City A")));
    expect(screen.queryByText(ALL_DEVICES_OR_MESSAGE)).toBeNull();
    expect(button(/preview results/i).disabled).toBe(false);
    expect(button(/^save$/i).disabled).toBe(false);
    expect(button(/save as/i).disabled).toBe(false);
  });

  it("warns and blocks preview and save when the connector is OR", () => {
    renderBuilder(tree("OR", item("all_devices"), item("location", "not_equals", "City A")));
    expect(screen.getByText(ALL_DEVICES_OR_MESSAGE)).toBeTruthy();
    expect(button(/preview results/i).disabled).toBe(true);
    expect(button(/^save$/i).disabled).toBe(true);
    expect(button(/save as/i).disabled).toBe(true);
  });

  it("shows no editable value box once All Devices is the field", () => {
    renderBuilder(tree("AND"), "all_devices");
    expect(screen.getByText("Selects every device")).toBeTruthy();
    expect(screen.queryByPlaceholderText(/enter all_devices/i)).toBeNull();
    expect(screen.queryByDisplayValue("Every device")).toBeNull();
  });
});
