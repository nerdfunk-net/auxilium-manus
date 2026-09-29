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

  const updateOperatorOptions = useCallback((fieldName: string) => {
    const { options, forcedOperator } = operatorRuleForField(fieldName);
    setOperatorOptionsOverride(options);
    if (forcedOperator) {
      setCurrentOperator(forcedOperator);
    }
  }, []);

  const handleFieldChange = useCallback(
    (fieldName: string) => {
      setCurrentField(fieldName);
      setCurrentValue("");
      setSelectedCustomField("");

      if (fieldName === "custom_fields") {
        setLoadCustomFields(true);
        return;
      }

      updateOperatorOptions(fieldName);

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
      if (customFieldName) {
        setFieldNameToLoad(customFieldName);
      }
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
