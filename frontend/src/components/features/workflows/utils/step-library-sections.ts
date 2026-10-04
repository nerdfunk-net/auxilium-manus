import type { PaletteGroup, PaletteItem } from "./step-catalog";
import { ALL_CATEGORY_KEY } from "./step-library-filter";
import { CATEGORY_SUBGROUPS, SUBGROUP_OTHER_LABEL } from "./step-visuals";

export interface StepSection {
  key: string;
  /** null = no header (a single, unlabelled category view). */
  label: string | null;
  categoryKey: string;
  items: PaletteItem[];
}

function sectionsForGroup(group: PaletteGroup, showCategoryLabel: boolean): StepSection[] {
  const subgroups = CATEGORY_SUBGROUPS[group.categoryKey];
  if (!subgroups) {
    return [
      {
        key: group.categoryKey,
        label: showCategoryLabel ? group.label : null,
        categoryKey: group.categoryKey,
        items: group.items,
      },
    ];
  }

  const listed = new Set(subgroups.flatMap((subgroup) => subgroup.kinds));
  const named = subgroups.map((subgroup) => ({
    label: subgroup.label,
    items: group.items.filter((item) => subgroup.kinds.includes(item.kind)),
  }));
  const rest = { label: SUBGROUP_OTHER_LABEL, items: group.items.filter((item) => !listed.has(item.kind)) };

  return [...named, rest]
    .filter((part) => part.items.length > 0)
    .map((part) => ({
      key: `${group.categoryKey}:${part.label}`,
      label: showCategoryLabel ? `${group.label} · ${part.label}` : part.label,
      categoryKey: group.categoryKey,
      items: part.items,
    }));
}

/**
 * Splits the visible steps into labelled sections: one per category in the
 * "All" view (category label), one per sub-group inside a category that
 * defines sub-groups (see CATEGORY_SUBGROUPS), otherwise a single header-less
 * section.
 */
export function buildStepSections(groups: PaletteGroup[], categoryKey: string): StepSection[] {
  const isAll = categoryKey === ALL_CATEGORY_KEY;
  const selected = isAll ? groups : groups.filter((group) => group.categoryKey === categoryKey);
  return selected.flatMap((group) => sectionsForGroup(group, isAll));
}
