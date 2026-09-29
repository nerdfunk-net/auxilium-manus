import type { FieldOption } from "../types/device-selector";

/** What the condition builder offers for one field. */
export interface FieldOperatorRule {
  /** Operators to offer; null keeps the server-provided default list. */
  options: FieldOption[] | null;
  /** Operator to select when the field is picked; null leaves the current one. */
  forcedOperator: string | null;
}

const EQUALS: FieldOption = { value: "equals", label: "Equals" };
const NOT_EQUALS: FieldOption = { value: "not_equals", label: "Not Equals" };
const CONTAINS: FieldOption = { value: "contains", label: "Contains" };

const EQUALS_ONLY: FieldOperatorRule = { options: [EQUALS], forcedOperator: "equals" };

// Exact match, with negation. This is also the rule for a location: "Location
// contains City" must never be offered — it would match "City A" (and Nautobot's
// GraphQL has no location name-contains filter). See backend LogicalCondition.
const EQUALS_OR_NOT_EQUALS: FieldOperatorRule = {
  options: [EQUALS, NOT_EQUALS],
  forcedOperator: null,
};

const RULES_BY_FIELD: Readonly<Record<string, FieldOperatorRule>> = {
  platform: EQUALS_ONLY,
  has_primary: EQUALS_ONLY,
  role: EQUALS_OR_NOT_EQUALS,
  manufacturer: EQUALS_OR_NOT_EQUALS,
  device_type: EQUALS_OR_NOT_EQUALS,
  status: EQUALS_OR_NOT_EQUALS,
  location: EQUALS_OR_NOT_EQUALS,
  tag: EQUALS_OR_NOT_EQUALS,
  ip_prefix: {
    options: [
      { value: "within_include", label: "Within Include" },
      { value: "within", label: "Within" },
      { value: "exact", label: "Exact" },
    ],
    forcedOperator: "within_include",
  },
  primary_prefix: {
    options: [{ value: "within_include", label: "Within Include" }],
    forcedOperator: "within_include",
  },
};

// Free-text fields: device names and custom fields are the only ones with "contains".
const SUBSTRING_MATCHABLE: FieldOperatorRule = {
  options: [EQUALS, CONTAINS],
  forcedOperator: null,
};

const DEFAULT_RULE: FieldOperatorRule = { options: null, forcedOperator: null };

export function operatorRuleForField(fieldName: string): FieldOperatorRule {
  const rule = RULES_BY_FIELD[fieldName];
  if (rule) {
    return rule;
  }
  if (fieldName === "name" || fieldName.startsWith("cf_")) {
    return SUBSTRING_MATCHABLE;
  }
  return DEFAULT_RULE;
}
