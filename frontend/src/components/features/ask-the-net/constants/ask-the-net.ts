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

/** Starting points that match what the tools can answer. Clicking one fills the message box. */
export const EXAMPLE_QUESTIONS: readonly string[] = [
  "Which route does 10.1.2.3 use on r1, and where does a packet to it go?",
  "Are all BGP sessions established?",
  "What are the interface settings of r1?",
  "How old is the data you are using?",
];
