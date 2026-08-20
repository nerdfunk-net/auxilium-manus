"use client";

import { Plus, RotateCcw, Settings } from "lucide-react";

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
import type { ConditionTree, CustomField, FieldOption } from "../types/device-selector";

interface AddConditionBarProps {
  conditionTree: ConditionTree;
  setConditionTree: (
    tree: ConditionTree | ((prev: ConditionTree) => ConditionTree),
  ) => void;
  currentGroupPath: string[];
  getCurrentTargetName: () => string;
  addConditionToTree: (field: string, operator: string, value: string) => void;
  addGroup: (logic: "AND" | "OR", negate: boolean) => void;
  onShowLogicalTree: () => void;
  currentField: string;
  currentOperator: string;
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
}

export function AddConditionBar({
  conditionTree,
  setConditionTree,
  getCurrentTargetName,
  addConditionToTree,
  addGroup,
  onShowLogicalTree,
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
}: AddConditionBarProps) {
  const canAddCondition = Boolean(currentField && currentValue);

  return (
    <>
      <div className="mb-4 flex items-center gap-2 rounded-lg border border-info-border bg-info p-3">
        <span className="text-sm font-medium text-info-foreground">Adding conditions to:</span>
        <Badge className="bg-card" variant="outline">
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
            <SelectTrigger className="border-2 border-input bg-card shadow-sm focus:border-ring focus:ring-2 focus:ring-ring/30">
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
              <SelectTrigger className="border-2 border-input bg-card shadow-sm focus:border-ring focus:ring-2 focus:ring-ring/30">
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
            <SelectTrigger className="border-2 border-input bg-card shadow-sm focus:border-ring focus:ring-2 focus:ring-ring/30">
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
              <SelectTrigger className="border-2 border-input bg-card shadow-sm focus:border-ring focus:ring-2 focus:ring-ring/30">
                <SelectValue placeholder="Select value..." />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="True">True</SelectItem>
                <SelectItem value="False">False</SelectItem>
              </SelectContent>
            </Select>
          ) : fieldValues.length > 0 ? (
            <Select onValueChange={setCurrentValue} value={currentValue}>
              <SelectTrigger className="border-2 border-input bg-card shadow-sm focus:border-ring focus:ring-2 focus:ring-ring/30">
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
              className="border-2 border-input bg-card shadow-sm focus:border-ring focus:ring-2 focus:ring-ring/30 disabled:border-border disabled:bg-muted"
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
              <SelectTrigger className="border-2 border-input bg-card shadow-sm focus:border-ring focus:ring-2 focus:ring-ring/30">
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
                className="h-4 w-4 rounded border-input text-primary focus:ring-2 focus:ring-ring"
                onChange={(e) => setCurrentNegate(e.target.checked)}
                type="checkbox"
              />
              <span className="text-foreground">Negate (NOT)</span>
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
    </>
  );
}
