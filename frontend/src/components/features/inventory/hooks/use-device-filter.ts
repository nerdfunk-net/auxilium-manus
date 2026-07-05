import { useMemo, useCallback, useState } from "react";

import { useGetNautobotDevicesFieldOptionsQuery } from "@/hooks/queries/use-get-nautobot-devices-field-options-query";
import { useGetNautobotDevicesFieldValuesQuery } from "@/hooks/queries/use-get-nautobot-devices-field-values-query";
import { useInventoryCustomFieldsQuery } from "@/hooks/queries/use-inventory-custom-fields-query";

import type { CustomField, FieldOption } from "../types/device-selector";

interface UseDeviceFilterOptions {
  nautobot_url: string;
  nautobot_token: string;
  sourceReady: boolean;
}

export function useDeviceFilter({
  nautobot_url,
  nautobot_token,
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
      nautobot_url,
      nautobot_token,
      enabled: loadCustomFields && sourceReady,
    });

  const { data: fieldValuesData, isLoading: isLoadingFieldValues } =
    useGetNautobotDevicesFieldValuesQuery({
      nautobot_url,
      nautobot_token,
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
    const restrictedFields = ["platform", "has_primary"];
    const isCustomField = fieldName.startsWith("cf_");

    if (restrictedFields.includes(fieldName)) {
      setOperatorOptionsOverride([{ value: "equals", label: "Equals" }]);
      setCurrentOperator("equals");
    } else if (
      ["role", "manufacturer", "device_type", "status", "location", "tag"].includes(
        fieldName,
      )
    ) {
      setOperatorOptionsOverride([
        { value: "equals", label: "Equals" },
        { value: "not_equals", label: "Not Equals" },
      ]);
    } else if (fieldName === "ip_prefix") {
      setOperatorOptionsOverride([
        { value: "within_include", label: "Within Include" },
        { value: "within", label: "Within" },
        { value: "exact", label: "Exact" },
      ]);
      setCurrentOperator("within_include");
    } else if (isCustomField || fieldName === "name") {
      setOperatorOptionsOverride([
        { value: "equals", label: "Equals" },
        { value: "contains", label: "Contains" },
      ]);
    } else {
      setOperatorOptionsOverride(null);
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
