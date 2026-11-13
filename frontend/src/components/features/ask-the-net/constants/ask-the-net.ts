import type { ConversationScope } from "@/components/features/ai-assistant/types/ai-assistant";

/** Where this page keeps its chat in the assistant session store. */
export const ASK_THE_NET_SESSION_KEY = "general";

/** Saved conversations of this page are listed under the `general` surface. */
export const ASK_THE_NET_SCOPE: ConversationScope = {
  surface: "general",
  subjectKey: "ask-the-net",
};

/**
 * The permissions that, held alone, make the backend attach tools to Ask the Net; each tool group
 * checks its own on every call. Used only to tell a user that has none of them what to expect.
 *
 * Not listed on purpose: `git.files:read` (config backups sit inside the Batfish tools) and
 * `workflows:execute` (released workflows also need `workflow_runs:read`) attach nothing by
 * themselves, and `netmiko:execute` / `reports:write` only add to tools another permission gave.
 * `sources.nautobot:read` counts only when a Nautobot source is configured (see `data-access.ts`).
 * The DNS tool has no permission (an operator switch), so it is not here either.
 * `backend/tests/unit/test_ask_the_net_data_permissions.py` pins this list to what
 * `build_general_session` really attaches: change them together.
 */
export const ASK_THE_NET_DATA_PERMISSIONS: readonly (readonly [
  string,
  string,
])[] = [
  ["sources.batfish", "query"],
  ["sources.nautobot", "read"],
  ["sources.catalyst_center", "read"],
  ["sources.aci", "read"],
  ["client_data", "read"],
  ["workflow_runs", "read"],
  ["reports", "read"],
];

export const ASK_THE_NET_PLACEHOLDER =
  "Ask about routes, paths, BGP sessions or interfaces…";
