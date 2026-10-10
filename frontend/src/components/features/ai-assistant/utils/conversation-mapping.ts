import type { DisplayMessage, SavedMessage } from "../types/ai-assistant";

import { nextMessageId } from "./message-id";

/**
 * Display messages to the server's storage shape. A proposal keeps only kind and summary: a
 * stored canvas or template body would be stale on resume. Tool chips still running when the
 * turn was cancelled are stored as finished.
 */
export function toSavedMessages(messages: DisplayMessage[]): SavedMessage[] {
  return messages
    .filter(
      (m) =>
        m.content ||
        m.error ||
        m.tools?.length ||
        m.proposal ||
        m.savedProposal,
    )
    .map((m) => {
      const proposal = m.proposal
        ? { kind: m.proposal.kind, summary: m.proposal.summary }
        : (m.savedProposal ?? null);
      return {
        role: m.role,
        content: m.content,
        error: m.error ?? null,
        tools: (m.tools ?? []).map((tool) => ({
          id: tool.id,
          name: tool.name,
          status: tool.status === "running" ? "done" : tool.status,
          truncated: tool.truncated === true,
          withheld: tool.withheld ?? [],
        })),
        proposal,
      };
    });
}

export function fromSavedMessages(saved: SavedMessage[]): DisplayMessage[] {
  return saved.map((m) => ({
    id: nextMessageId(),
    role: m.role,
    content: m.content,
    ...(m.error ? { error: m.error } : {}),
    ...(m.tools.length > 0 ? { tools: m.tools } : {}),
    ...(m.proposal ? { savedProposal: m.proposal } : {}),
  }));
}
