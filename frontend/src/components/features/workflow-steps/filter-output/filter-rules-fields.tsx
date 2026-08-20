"use client";

import { Plus, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type RuleType = "pattern" | "path";

export interface FilterRule {
  type: RuleType;
  value: string;
}

export interface FilterRulesFieldsProps {
  rules: FilterRule[];
  onAddRule: () => void;
  onRuleTypeChange: (index: number, type: RuleType) => void;
  onRuleValueChange: (index: number, value: string) => void;
  onRemoveRule: (index: number) => void;
}

export function FilterRulesFields({
  rules,
  onAddRule,
  onRuleTypeChange,
  onRuleValueChange,
  onRemoveRule,
}: FilterRulesFieldsProps) {
  return (
    <div className="space-y-2 border-t pt-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">filter_rules</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            list
          </Badge>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-6 gap-1 px-2 text-[11px]"
          onClick={onAddRule}
        >
          <Plus className="size-3" aria-hidden />
          Add rule
        </Button>
      </div>

      {rules.length === 0 ? (
        <p className="text-[11px] text-warning-foreground">Add at least one filter rule.</p>
      ) : null}

      <div className="space-y-2">
        {rules.map((rule, index) => (
          <div key={index} className="flex items-center gap-1.5">
            <Select
              value={rule.type}
              onValueChange={(value) => onRuleTypeChange(index, value as RuleType)}
            >
              <SelectTrigger className="h-7 w-[80px] shrink-0 text-[11px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="pattern">pattern</SelectItem>
                <SelectItem value="path">path</SelectItem>
              </SelectContent>
            </Select>
            <Input
              value={rule.value}
              onChange={(e) => onRuleValueChange(index, e.target.value)}
              placeholder={rule.type === "pattern" ? "^uptime" : "route.ospf"}
              className="h-7 flex-1 font-mono text-xs"
            />
            <button
              type="button"
              onClick={() => onRemoveRule(index)}
              className="shrink-0 text-muted-foreground hover:text-destructive"
              aria-label="Remove rule"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          </div>
        ))}
      </div>

      <div className="rounded-lg bg-muted/30 px-3 py-2 text-[11px] text-muted-foreground">
        <p className="font-medium text-foreground">Rule types</p>
        <p className="mt-1">
          <span className="font-mono">pattern</span> — regex on key names (JSON, recursive) or line
          content (text). E.g. <span className="font-mono">^uptime</span> removes all keys starting
          with uptime.
        </p>
        <p className="mt-1">
          <span className="font-mono">path</span> — dot-notation path to remove a specific nested
          JSON key. E.g. <span className="font-mono">route.ospf</span> removes{" "}
          <span className="font-mono">data.route.ospf</span>.
        </p>
      </div>
    </div>
  );
}
