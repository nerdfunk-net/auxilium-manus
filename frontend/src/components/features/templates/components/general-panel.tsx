"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { TEMPLATE_TYPES } from "../constants";
import type { TemplateType } from "../types";

interface GeneralPanelProps {
  name: string;
  description: string;
  templateType: TemplateType;
  onNameChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
  onTemplateTypeChange: (value: TemplateType) => void;
}

export function GeneralPanel({
  name,
  description,
  templateType,
  onNameChange,
  onDescriptionChange,
  onTemplateTypeChange,
}: GeneralPanelProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Template Details</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-12">
          <div className="space-y-1.5 md:col-span-4">
            <Label htmlFor="template-name">
              Template Name <span className="text-destructive">*</span>
            </Label>
            <Input
              id="template-name"
              placeholder="e.g. base-config"
              value={name}
              onChange={(event) => onNameChange(event.target.value)}
            />
          </div>
          <div className="space-y-1.5 md:col-span-4">
            <Label htmlFor="template-description">Description</Label>
            <Input
              id="template-description"
              placeholder="Brief description of the template"
              value={description}
              onChange={(event) => onDescriptionChange(event.target.value)}
            />
          </div>
          <div className="space-y-1.5 md:col-span-2">
            <Label htmlFor="template-category">Category</Label>
            <Input id="template-category" value="Netmiko" readOnly disabled />
          </div>
          <div className="space-y-1.5 md:col-span-2">
            <Label>Type</Label>
            <Select
              value={templateType}
              onValueChange={(value) => onTemplateTypeChange(value as TemplateType)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TEMPLATE_TYPES.map((type) => (
                  <SelectItem key={type.value} value={type.value}>
                    {type.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
