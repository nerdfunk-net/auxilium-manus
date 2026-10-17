import type { PaletteGroup } from "./step-catalog";

/** Pseudo-category that lists every available step. */
export const ALL_CATEGORY_KEY = "__all__";

// These steps read/write an external Secret Manager connection and make no
// sense to offer until one is configured under Settings -> Secret Manager.
// Other "secrets" category steps (encrypt-attribute, decrypt-attribute) use
// the credential vault instead and stay visible regardless.
const SECRET_MANAGER_STEP_KINDS = new Set(["secret-generate", "secret-get", "secret-set"]);

export interface StepAvailability {
  hasPyatsSource: boolean;
  hasBatfishSource: boolean;
  hasSecretManagerConnection: boolean;
}

/**
 * Hides categories/steps that cannot be configured yet: PyATS and Batfish need
 * a source under Settings -> Sources, Secret Get/Set/Generate need a Secret
 * Manager connection (only those steps — not the whole "secrets" category).
 */
export function filterAvailableGroups(
  groups: PaletteGroup[],
  availability: StepAvailability,
): PaletteGroup[] {
  return groups
    .filter((group) => availability.hasPyatsSource || group.categoryKey !== "pyats")
    .filter((group) => availability.hasBatfishSource || group.categoryKey !== "batfish")
    .map((group) =>
      availability.hasSecretManagerConnection
        ? group
        : { ...group, items: group.items.filter((item) => !SECRET_MANAGER_STEP_KINDS.has(item.kind)) },
    )
    .filter((group) => group.items.length > 0);
}

export function filterGroupsByQuery(groups: PaletteGroup[], search: string): PaletteGroup[] {
  const query = search.trim().toLowerCase();
  if (!query) return groups;
  return groups
    .map((group) => ({
      ...group,
      items: group.items.filter(
        (item) =>
          item.title.toLowerCase().includes(query) ||
          item.overview.toLowerCase().includes(query) ||
          item.description.toLowerCase().includes(query) ||
          item.kind.toLowerCase().includes(query),
      ),
    }))
    .filter((group) => group.items.length > 0);
}
