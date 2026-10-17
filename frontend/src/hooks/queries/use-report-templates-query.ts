"use client";

import { useMemo } from "react";

import { useTemplatesQuery } from "@/components/features/templates/hooks/use-templates-query";
import type { TemplateListItem } from "@/components/features/templates/types";

export const REPORT_TEMPLATE_CATEGORY = "report";

const NO_TEMPLATES: TemplateListItem[] = [];

/** Templates of category "report", the ones that can shape a report's text. */
export function useReportTemplatesQuery() {
  const query = useTemplatesQuery();
  const templates = useMemo(
    () =>
      (query.data?.templates ?? NO_TEMPLATES).filter(
        (template) => template.category === REPORT_TEMPLATE_CATEGORY,
      ),
    [query.data],
  );
  return { templates, isLoading: query.isLoading, isError: query.isError };
}
