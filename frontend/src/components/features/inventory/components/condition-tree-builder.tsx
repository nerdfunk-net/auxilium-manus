"use client";

import {
  ChevronLeft,
  Filter,
  FolderOpen,
  HelpCircle,
  Play,
  Plus,
  RotateCcw,
  Save,
  Settings,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { createEmptyTree } from "../hooks/use-condition-tree";
import type {
  ConditionGroup as ConditionGroupType,
  ConditionItem as ConditionItemType,
  ConditionTree,
  CustomField,
  FieldOption,
} from "../types/device-selector";

import { ConditionGroup } from "./condition-group";
import { ConditionItem } from "./condition-item";

interface ConditionTreeBuilderProps {
  conditionTree: ConditionTree;
  setConditionTree: (
    tree: ConditionTree | ((prev: ConditionTree) => ConditionTree),
  ) => void;
  currentGroupPath: string[];
  setCurrentGroupPath: (path: string[]) => void;
  addConditionToTree: (field: string, operator: string, value: string) => void;
  addGroup: (logic: "AND" | "OR", negate: boolean) => void;
  removeItemFromTree: (id: string) => void;
  updateGroupLogic: (id: string, logic: "AND" | "OR") => void;
  findGroupPath: (id: string) => string[] | null;
  currentField: string;
  setCurrentField: (value: string) => void;
  currentOperator: string;
  setCurrentOperator: (value: string) => void;
  currentValue: string;
  setCurrentValue: (value: string) => void;
  currentLogic: string;
  setCurrentLogic: (value: string) => void;
  currentNegate: boolean;
  setCurrentNegate: (value: boolean) => void;
  fieldOptions: FieldOption[];
  operatorOptions: FieldOption[];
  fieldValues: FieldOption[];
  customFields: CustomField[];
  handleFieldChange: (field: string) => void;
  handleOperatorChange: (operator: string) => void;
  handleCustomFieldSelect: (value: string) => void;
  selectedCustomField: string;
  isLoadingFieldValues: boolean;
  isLoadingCustomFields: boolean;
  sourceReady: boolean;
  onPreview: () => void;
  isLoadingPreview: boolean;
  showActions?: boolean;
  showSaveLoad?: boolean;
  loadedInventoryName?: string;
  onSaveCurrent?: () => void;
  isSavingCurrent?: boolean;
  onOpenSaveAsModal: () => void;
  onOpenLoadModal: () => void;
  onOpenManageModal: () => void;
  onShowHelp: () => void;
  onShowLogicalTree: () => void;
}

export function ConditionTreeBuilder({
  conditionTree,
  setConditionTree,
  currentGroupPath,
  setCurrentGroupPath,
  addConditionToTree,
  addGroup,
  removeItemFromTree,
  updateGroupLogic,
  findGroupPath,
  currentField,
  currentOperator,
  currentValue,
  setCurrentValue,
  currentLogic,
  setCurrentLogic,
  currentNegate,
  setCurrentNegate,
  fieldOptions,
  operatorOptions,
  fieldValues,
  customFields,
  handleFieldChange,
  handleOperatorChange,
  handleCustomFieldSelect,
  selectedCustomField,
  isLoadingFieldValues,
  isLoadingCustomFields,
  sourceReady,
  onPreview,
  isLoadingPreview,
  showActions = true,
  showSaveLoad = true,
  loadedInventoryName,
  onSaveCurrent,
  isSavingCurrent,
  onOpenSaveAsModal,
  onOpenLoadModal,
  onOpenManageModal,
  onShowHelp,
  onShowLogicalTree,
}: ConditionTreeBuilderProps) {
  const getFieldLabel = (field: string) => {
    const option = fieldOptions.find((opt) => opt.value === field);
    return option?.label ?? field;
  };

  const setTargetGroup = (groupId: string | null) => {
    if (groupId === null) {
      setCurrentGroupPath([]);
    } else {
      const path = findGroupPath(groupId);
      if (path) {
        setCurrentGroupPath(path);
      }
    }
  };

  const getCurrentTargetName = () => {
    if (currentGroupPath.length === 0) {
      return "Root";
    }

    const findGroupById = (
      items: (ConditionItemType | ConditionGroupType)[],
      groupId: string,
    ): ConditionGroupType | null => {
      for (const item of items) {
        if ("type" in item && item.type === "group") {
          if (item.id === groupId) {
            return item;
          }
          const found = findGroupById(item.items, groupId);
          if (found) return found;
        }
      }
      return null;
    };

    const targetGroupId = currentGroupPath[currentGroupPath.length - 1];
    if (!targetGroupId) {
      return `Group ${currentGroupPath.length}`;
    }

    const group = findGroupById(conditionTree.items, targetGroupId);
    if (group) {
      return `Group (${group.internalLogic})`;
    }

    return `Group ${currentGroupPath.length}`;
  };

  const isItemAtRootLevel = (itemId: string): boolean =>
    conditionTree.items.some((item) => item.id === itemId);

  const canAddCondition = Boolean(currentField && currentValue);

  return (
    <div className="rounded-lg border-0 bg-white p-0 shadow-lg">
      <div className="flex items-center justify-between rounded-t-lg bg-gradient-to-r from-blue-400/80 to-blue-500/80 px-4 py-2 text-white">
        <div className="flex items-center space-x-2">
          <Filter className="h-4 w-4" />
          <span className="text-sm font-medium">Device Filter</span>
          {loadedInventoryName ? (
            <span className="ml-1 rounded bg-white/10 px-2 py-0.5 text-xs text-white/80">
              Inventory loaded: {loadedInventoryName}
            </span>
          ) : null}
        </div>
        <button
          className="flex items-center gap-1.5 rounded px-2.5 py-1 text-xs text-white/90 transition-colors hover:bg-white/10 hover:text-white"
          onClick={onShowHelp}
          title="Show help and examples"
          type="button"
        >
          <HelpCircle className="h-3.5 w-3.5" />
          <span>Help</span>
        </button>
      </div>
      <div className="bg-gradient-to-b from-white to-gray-50 p-6">
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 p-3">
          <span className="text-sm font-medium text-blue-900">Adding conditions to:</span>
          <Badge className="bg-white" variant="outline">
            {getCurrentTargetName()}
          </Badge>
        </div>

        <div
          className={`grid grid-cols-1 gap-4 ${currentField === "custom_fields" || selectedCustomField ? "md:grid-cols-[1fr_1fr_1fr_2fr_1fr_auto]" : "md:grid-cols-[1fr_1fr_2fr_1fr_auto]"}`}
        >
          <div className="space-y-2">
            <Label htmlFor="field">Field</Label>
            <Select
              onValueChange={handleFieldChange}
              value={
                currentField === "custom_fields" || selectedCustomField
                  ? "custom_fields"
                  : currentField
              }
            >
              <SelectTrigger className="border-2 border-slate-300 bg-white shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200">
                <SelectValue placeholder="Select field..." />
              </SelectTrigger>
              <SelectContent>
                {fieldOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {(currentField === "custom_fields" || selectedCustomField) && (
            <div className="space-y-2">
              <Label htmlFor="custom-field">Custom Field</Label>
              <Select
                disabled={isLoadingCustomFields || !sourceReady}
                onValueChange={handleCustomFieldSelect}
                value={selectedCustomField ? `cf_${selectedCustomField}` : ""}
              >
                <SelectTrigger className="border-2 border-slate-300 bg-white shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200">
                  <SelectValue
                    placeholder={
                      isLoadingCustomFields ? "Loading..." : "Select custom field..."
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {customFields.map((field) => (
                    <SelectItem key={field.name} value={`cf_${String(field.name)}`}>
                      {String(field.label || field.name)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="operator">Operator</Label>
            <Select onValueChange={handleOperatorChange} value={currentOperator}>
              <SelectTrigger className="border-2 border-slate-300 bg-white shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200">
                <SelectValue placeholder="Select operator..." />
              </SelectTrigger>
              <SelectContent>
                {operatorOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="value">Value</Label>
            {currentField === "has_primary" ? (
              <Select onValueChange={setCurrentValue} value={currentValue}>
                <SelectTrigger className="border-2 border-slate-300 bg-white shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200">
                  <SelectValue placeholder="Select value..." />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="True">True</SelectItem>
                  <SelectItem value="False">False</SelectItem>
                </SelectContent>
              </Select>
            ) : fieldValues.length > 0 ? (
              <Select onValueChange={setCurrentValue} value={currentValue}>
                <SelectTrigger className="border-2 border-slate-300 bg-white shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200">
                  <SelectValue placeholder="Choose value..." />
                </SelectTrigger>
                <SelectContent>
                  {fieldValues.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Input
                className="border-2 border-slate-300 bg-white shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200 disabled:border-slate-200 disabled:bg-slate-100"
                disabled={!currentField || isLoadingFieldValues}
                onChange={(e) => setCurrentValue(e.target.value)}
                placeholder={
                  currentField ? `Enter ${currentField}...` : "Select a field first"
                }
                value={currentValue}
              />
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="logic">Connector</Label>
            <div className="flex flex-col gap-2">
              <Select onValueChange={setCurrentLogic} value={currentLogic}>
                <SelectTrigger className="border-2 border-slate-300 bg-white shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200">
                  <SelectValue placeholder="Select connector..." />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="AND">AND</SelectItem>
                  <SelectItem value="OR">OR</SelectItem>
                </SelectContent>
              </Select>
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input
                  checked={currentNegate}
                  className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-2 focus:ring-blue-500"
                  onChange={(e) => setCurrentNegate(e.target.checked)}
                  type="checkbox"
                />
                <span className="text-gray-700">Negate (NOT)</span>
              </label>
            </div>
          </div>

          <div className="space-y-2">
            <Label>&nbsp;</Label>
            <div className="flex space-x-2">
              <Button
                disabled={!canAddCondition}
                onClick={() => addConditionToTree(currentField, currentOperator, currentValue)}
                size="sm"
                title="Add Condition"
                type="button"
              >
                <Plus className="h-4 w-4" />
              </Button>
              <Button
                onClick={() => addGroup(currentLogic as "AND" | "OR", currentNegate)}
                size="sm"
                title="Add Group"
                type="button"
                variant="secondary"
              >
                <Plus className="mr-1 h-4 w-4" />
                <span className="text-xs">Group</span>
              </Button>
              <Button
                onClick={() => setConditionTree(createEmptyTree())}
                size="sm"
                title="Clear All"
                type="button"
                variant="outline"
              >
                <RotateCcw className="h-4 w-4" />
              </Button>
              <Button
                className="ml-auto"
                disabled={conditionTree.items.length === 0}
                onClick={onShowLogicalTree}
                size="sm"
                title="Show Logical Tree"
                type="button"
                variant="outline"
              >
                <Settings className="mr-1 h-4 w-4" />
                <span className="text-xs">Show Tree</span>
              </Button>
            </div>
          </div>
        </div>

        <div className="mt-6">
          <Label className="text-base font-medium">Logical Expression</Label>
          <div className="mt-2 min-h-[60px] rounded-lg bg-gray-50 p-4">
            {conditionTree.items.length === 0 ? (
              <p className="text-sm italic text-gray-500">
                No conditions added yet. Add conditions or groups above to filter devices.
              </p>
            ) : (
              <div className="space-y-2">
                <div className="mb-2 flex flex-wrap items-center gap-1 text-xs text-gray-500">
                  Root logic:{" "}
                  <Badge variant="outline">{conditionTree.internalLogic}</Badge>
                  <Button
                    className="h-5 text-xs"
                    onClick={() => {
                      setConditionTree((prev) => ({
                        ...prev,
                        internalLogic: prev.internalLogic === "AND" ? "OR" : "AND",
                      }));
                    }}
                    size="sm"
                    type="button"
                    variant="ghost"
                  >
                    Toggle
                  </Button>
                  {currentGroupPath.length > 0 ? (
                    <Button
                      className="h-5 text-xs"
                      onClick={() => setTargetGroup(null)}
                      size="sm"
                      title="Return to root level"
                      type="button"
                      variant="outline"
                    >
                      <ChevronLeft className="mr-1 h-3 w-3" />
                      Back to Root
                    </Button>
                  ) : null}
                </div>
                {conditionTree.items.map((item, index) => (
                  <div key={item.id}>
                    {"type" in item && item.type === "group" ? (
                      <ConditionGroup
                        currentGroupPath={currentGroupPath}
                        getFieldLabel={getFieldLabel}
                        group={item as ConditionGroupType}
                        isAtRoot
                        isFirst={index === 0}
                        isItemAtRootLevel={isItemAtRootLevel}
                        onRemove={removeItemFromTree}
                        onSetTargetGroup={setTargetGroup}
                        onUpdateLogic={updateGroupLogic}
                      />
                    ) : (
                      <ConditionItem
                        getFieldLabel={getFieldLabel}
                        item={item as ConditionItemType}
                        onRemove={removeItemFromTree}
                      />
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {showActions ? (
          <div className="mt-4 flex justify-start gap-2">
            <Button
              className="flex items-center space-x-2 border-0 bg-green-600 text-white hover:bg-green-700 disabled:bg-gray-400"
              disabled={conditionTree.items.length === 0 || isLoadingPreview || !sourceReady}
              onClick={onPreview}
              type="button"
            >
              <Play className="h-4 w-4" />
              <span>{isLoadingPreview ? "Loading..." : "Preview Results"}</span>
            </Button>
            {showSaveLoad ? (
              <>
                <Button
                  className="flex items-center space-x-2 border-0 bg-blue-600 text-white hover:bg-blue-700 disabled:bg-gray-400"
                  disabled={
                    !loadedInventoryName ||
                    conditionTree.items.length === 0 ||
                    isSavingCurrent
                  }
                  onClick={onSaveCurrent}
                  title={
                    !loadedInventoryName
                      ? "Load an inventory first to use Save"
                      : "Overwrite the loaded inventory"
                  }
                  type="button"
                >
                  <Save className="h-4 w-4" />
                  <span>{isSavingCurrent ? "Saving..." : "Save"}</span>
                </Button>
                <Button
                  className="flex items-center space-x-2 border-0 bg-blue-500 text-white hover:bg-blue-600 disabled:bg-gray-400"
                  disabled={conditionTree.items.length === 0}
                  onClick={onOpenSaveAsModal}
                  title="Save as a new inventory"
                  type="button"
                >
                  <Save className="h-4 w-4" />
                  <span>Save as</span>
                </Button>
                <Button
                  className="flex items-center space-x-2"
                  onClick={onOpenLoadModal}
                  type="button"
                  variant="outline"
                >
                  <FolderOpen className="h-4 w-4" />
                  <span>Load</span>
                </Button>
                <Button
                  className="flex items-center space-x-2 border-purple-300 text-purple-600 hover:bg-purple-50 hover:text-purple-700"
                  onClick={onOpenManageModal}
                  type="button"
                  variant="outline"
                >
                  <Settings className="h-4 w-4" />
                  <span>Manage Inventory</span>
                </Button>
              </>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
