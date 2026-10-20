import { useMemo, useCallback, useState } from "react";

import { useGetNautobotDevicesFieldOptionsQuery } from "@/hooks/queries/use-get-nautobot-devices-field-options-query";
import { useGetNautobotDevicesFieldValuesQuery } from "@/hooks/queries/use-get-nautobot-devices-field-values-query";
import { useInventoryCustomFieldsQuery } from "@/hooks/queries/use-inventory-custom-fields-query";

import type { CustomField, FieldOption } from "../types/device-selector";
import { operatorRuleForField } from "../utils/field-operators";

interface UseDeviceFilterOptions {
  sourceId: string;
  sourceReady: boolean;
}

export function useDeviceFilter({
  sourceId,
  sourceReady,
}: UseDeviceFilterOptions) {
  const [currentField, setCurrentField] = useState("");
  const [currentOperator, setCurrentOperator] = useState("equals");
  const [currentValue, setCurrentValue] = useState("");
  const [currentLogic, setCurrentLogic] = useState("AND");
  const [currentNegate, setCurrentNegate] = useState(false);
  const [operatorOptionsOverride, setOperatorOptionsOverride] = useState<
    FieldOption[] | null
  >(null);
  const [selectedCustomField, setSelectedCustomField] = useState("");
  const [loadCustomFields, setLoadCustomFields] = useState(false);
  const [fieldNameToLoad, setFieldNameToLoad] = useState<string | null>(null);

  const { data: fieldOptionsData } = useGetNautobotDevicesFieldOptionsQuery();

  const { data: customFieldsData, isLoading: isLoadingCustomFields } =
    useInventoryCustomFieldsQuery({
      sourceId,
      enabled: loadCustomFields && sourceReady,
    });

  const { data: fieldValuesData, isLoading: isLoadingFieldValues } =
    useGetNautobotDevicesFieldValuesQuery({
      sourceId,
      field: fieldNameToLoad ?? "",
      enabled: sourceReady && Boolean(fieldNameToLoad),
    });

  const fieldOptions = useMemo(
    () => fieldOptionsData?.fields ?? [],
    [fieldOptionsData?.fields],
  );

  const customFields: CustomField[] = useMemo(
    () => customFieldsData?.custom_fields ?? [],
    [customFieldsData?.custom_fields],
  );

  const fieldValues = useMemo(
    () => fieldValuesData?.values ?? [],
    [fieldValuesData?.values],
  );

  const operatorOptions = useMemo(
    () => operatorOptionsOverride ?? fieldOptionsData?.operators ?? [],
    [operatorOptionsOverride, fieldOptionsData?.operators],
  );

  const serverOperators = fieldOptionsData?.operators;

  // The operator list changes with the field; an operator the new list lacks (for
  // example "within_include" after switching to the name field) would be submitted as
  // a condition the field cannot evaluate, so fall back to "equals".
  const updateOperatorOptions = useCallback(
    (fieldName: string) => {
      const { options, forcedOperator } = operatorRuleForField(fieldName);
      setOperatorOptionsOverride(options);
      setCurrentOperator((previous) => {
        if (forcedOperator) return forcedOperator;
        const offered = options ?? serverOperators;
        // Server list not loaded yet: only "equals" is safe for a field without its own rule.
        if (!offered || offered.length === 0) return "equals";
        return offered.some((option) => option.value === previous) ? previous : "equals";
      });
    },
    [serverOperators],
  );

  const handleFieldChange = useCallback(
    (fieldName: string) => {
      setCurrentField(fieldName);
      setCurrentValue("");
      setSelectedCustomField("");

      updateOperatorOptions(fieldName);

      if (fieldName === "custom_fields") {
        // No value list until a custom field is chosen; the previous field's values must go.
        setFieldNameToLoad(null);
        setLoadCustomFields(true);
        return;
      }

      if (
        fieldName &&
        fieldName !== "has_primary" &&
        fieldName !== "ip_prefix" &&
        fieldName !== "primary_prefix" &&
        fieldName !== "custom_fields"
      ) {
        setFieldNameToLoad(fieldName);
      } else {
        setFieldNameToLoad(null);
      }
    },
    [updateOperatorOptions],
  );

  const handleCustomFieldSelect = useCallback(
    (customFieldName: string) => {
      const actualFieldName = customFieldName.replace(/^cf_/, "");
      setSelectedCustomField(actualFieldName);
      setCurrentField(customFieldName);
      setCurrentValue("");
      updateOperatorOptions(customFieldName);
      setFieldNameToLoad(customFieldName || null);
    },
    [updateOperatorOptions],
  );

  const handleOperatorChange = useCallback((operator: string) => {
    setCurrentOperator(operator);
  }, []);

  return useMemo(
    () => ({
      currentField,
      setCurrentField,
      currentOperator,
      setCurrentOperator,
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
      selectedCustomField,
      isLoadingFieldValues,
      isLoadingCustomFields,
      handleFieldChange,
      handleCustomFieldSelect,
      handleOperatorChange,
    }),
    [
      currentField,
      currentOperator,
      currentValue,
      currentLogic,
      currentNegate,
      fieldOptions,
      operatorOptions,
      fieldValues,
      customFields,
      selectedCustomField,
      isLoadingFieldValues,
      isLoadingCustomFields,
      handleFieldChange,
      handleCustomFieldSelect,
      handleOperatorChange,
    ],
  );
}
