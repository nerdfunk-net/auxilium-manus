import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";

interface JinjaPreviewResponse {
  rendered: string;
}

interface JinjaSampleContextResponse {
  context: Record<string, unknown>;
}

export function useJinjaValidateMutation() {
  const { apiCall } = useApi();
  return useMutation<void, Error, { template: string }>({
    mutationFn: async ({ template }) => {
      await apiCall("workflow-steps/render-jinja-template/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ template }),
      });
    },
  });
}

export function useJinjaPreviewMutation() {
  const { apiCall } = useApi();
  return useMutation<string, Error, { template: string; context: Record<string, unknown> }>({
    mutationFn: async ({ template, context }) => {
      const response = await apiCall<JinjaPreviewResponse>(
        "workflow-steps/render-jinja-template/preview",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ template, context }),
        },
      );
      return response.rendered;
    },
  });
}

export function useJinjaNautobotSampleContextMutation() {
  const { apiCall } = useApi();
  return useMutation<
    Record<string, unknown>,
    Error,
    {
      nautobot_source_id: string;
      device_name: string;
      list_of_attributes: string[];
    }
  >({
    mutationFn: async (payload) => {
      const response = await apiCall<JinjaSampleContextResponse>(
        "workflow-steps/render-jinja-template/sample-context/nautobot",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
      return response.context;
    },
  });
}

export function useJinjaDeviceSampleContextMutation() {
  const { apiCall } = useApi();
  return useMutation<Record<string, unknown>, Error, { device: Record<string, unknown> }>({
    mutationFn: async ({ device }) => {
      const response = await apiCall<JinjaSampleContextResponse>(
        "workflow-steps/render-jinja-template/sample-context/device",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ device }),
        },
      );
      return response.context;
    },
  });
}
