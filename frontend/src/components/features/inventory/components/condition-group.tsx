"use client";

import { X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import type {
  ConditionGroup as ConditionGroupType,
  ConditionItem as ConditionItemType,
} from "../types/device-selector";

import { ConditionItem } from "./condition-item";

interface ConditionGroupProps {
  group: ConditionGroupType;
  currentGroupPath: string[];
  onSetTargetGroup: (id: string | null) => void;
  onUpdateLogic: (id: string, logic: "AND" | "OR") => void;
  onRemove: (id: string) => void;
  getFieldLabel: (field: string) => string;
  isFirst: boolean;
  isAtRoot: boolean;
  isItemAtRootLevel: (id: string) => boolean;
}

export function ConditionGroup({
  group,
  currentGroupPath,
  onSetTargetGroup,
  onUpdateLogic,
  onRemove,
  getFieldLabel,
  isFirst,
  isAtRoot,
  isItemAtRootLevel,
}: ConditionGroupProps) {
  const isActiveTarget =
    currentGroupPath.length > 0 &&
    currentGroupPath[currentGroupPath.length - 1] === group.id;

  const getLogicBadgeColor = (logic: string) => {
    switch (logic) {
      case "AND":
        return "bg-green-100 text-green-800";
      case "OR":
        return "bg-yellow-100 text-yellow-800";
      case "NOT":
        return "bg-red-100 text-red-800";
      default:
        return "bg-blue-100 text-blue-800";
    }
  };

  return (
    <div
      className={`cursor-pointer rounded-r border-l-4 py-2 pl-4 transition-colors ${
        isActiveTarget
          ? "border-blue-500 bg-blue-50/70"
          : "border-purple-300 bg-purple-50/50 hover:bg-purple-100/50"
      }`}
      onClick={(e) => {
        e.stopPropagation();
        onSetTargetGroup(group.id);
      }}
      title="Click to add conditions to this group"
    >
      <div className="mb-2 flex items-center gap-2">
        {!isFirst && !isAtRoot ? (
          <Badge className={getLogicBadgeColor(group.logic)}>{group.logic}</Badge>
        ) : null}
        <Badge
          className={
            isActiveTarget
              ? "border-blue-300 bg-blue-100 text-blue-800"
              : "border-purple-300 bg-purple-100 text-purple-800"
          }
          variant="outline"
        >
          GROUP ({group.internalLogic})
        </Badge>
        {isActiveTarget ? (
          <Badge className="bg-blue-500 text-xs text-white">Active Target</Badge>
        ) : null}
        <Button
          className="h-5 px-2 text-xs"
          onClick={(e) => {
            e.stopPropagation();
            onUpdateLogic(group.id, group.internalLogic === "AND" ? "OR" : "AND");
          }}
          size="sm"
          title="Toggle group logic"
          type="button"
          variant="ghost"
        >
          Toggle
        </Button>
        <Button
          className="ml-auto h-5 w-5 p-0 hover:bg-red-100"
          onClick={(e) => {
            e.stopPropagation();
            onRemove(group.id);
          }}
          size="sm"
          title="Delete group"
          type="button"
          variant="ghost"
        >
          <X className="h-3 w-3 text-red-600" />
        </Button>
      </div>
      <div className="space-y-1">
        {group.items.length === 0 ? (
          <p className="text-xs italic text-gray-400">Empty group - add conditions here</p>
        ) : (
          group.items.map((subItem, subIndex) => (
            <div key={subItem.id}>
              {"type" in subItem && subItem.type === "group" ? (
                <ConditionGroup
                  currentGroupPath={currentGroupPath}
                  getFieldLabel={getFieldLabel}
                  group={subItem as ConditionGroupType}
                  isAtRoot={isItemAtRootLevel(subItem.id)}
                  isFirst={subIndex === 0}
                  isItemAtRootLevel={isItemAtRootLevel}
                  onRemove={onRemove}
                  onSetTargetGroup={onSetTargetGroup}
                  onUpdateLogic={onUpdateLogic}
                />
              ) : (
                <ConditionItem
                  getFieldLabel={getFieldLabel}
                  item={subItem as ConditionItemType}
                  onRemove={onRemove}
                />
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
