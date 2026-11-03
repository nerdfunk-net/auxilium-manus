import type { ConversationScope } from "@/components/features/ai-assistant/types/ai-assistant";

/** Where this page keeps its chat in the assistant session store. */
export const ASK_THE_NET_SESSION_KEY = "general";

/** Saved conversations of this page are listed under the `general` surface. */
export const ASK_THE_NET_SCOPE: ConversationScope = {
  surface: "general",
  subjectKey: "ask-the-net",
};

export const ASK_THE_NET_PLACEHOLDER =
  "Ask about routes, paths, BGP sessions or interfaces…";
