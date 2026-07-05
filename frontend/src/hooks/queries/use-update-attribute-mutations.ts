import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";

import type { RegexFlags } from "@/components/features/workflow-steps/update-attribute/update-attribute-config";

export interface UpdateAttributeProbeResult {
  matched: boolean;
  source_text: string | null;
  full_match: string | null;
  groups: Record<string, string>;
  named_groups: Record<string, string>;
  destination_value: string | null;
}

interface ProbePayload {
  sample_text: string;
  pattern: string;
  destination_template: string;
  regex_flags: RegexFlags;
}

interface ProbeDevicePayload extends Omit<ProbePayload, "sample_text"> {
  device: Record<string, unknown>;
  source_path: string;
}

export function useUpdateAttributeProbeMutation() {
  const { apiCall } = useApi();
  return useMutation<UpdateAttributeProbeResult, Error, ProbePayload>({
    mutationFn: async (payload) =>
      apiCall<UpdateAttributeProbeResult>("workflow-steps/update-attribute/probe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
  });
}

export function useUpdateAttributeDeviceProbeMutation() {
  const { apiCall } = useApi();
  return useMutation<UpdateAttributeProbeResult, Error, ProbeDevicePayload>({
    mutationFn: async (payload) =>
      apiCall<UpdateAttributeProbeResult>(
        "workflow-steps/update-attribute/probe/device",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      ),
  });
}
