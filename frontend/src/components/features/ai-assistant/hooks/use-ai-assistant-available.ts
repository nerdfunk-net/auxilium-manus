"use client";

import { useAiStatusQuery } from "@/hooks/queries/use-ai-status-query";

/**
 * The only way a surface decides whether to render assistant UI. While the status is
 * loading or failed, the answer is `false`: assistant UI never flashes in for a user who has
 * it switched off. This is a UX gate; the backend refuses disabled users on every endpoint.
 */
export function useAiAssistantAvailable(): boolean {
  const { data } = useAiStatusQuery();
  return data?.available === true;
}
