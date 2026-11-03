"use client";

import type { ReportSection } from "@/components/features/reports/types/report-definition";
import type { ReportQuerySpec } from "@/components/features/reports/types/report-query";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { buildApiErrorMessage } from "@/hooks/use-api";
import { useAuthStore } from "@/lib/auth-store";

import type {
  AssistantContext,
  ChatMessage,
  DeviceCommandResult,
  WorkflowRunDevice,
  WorkflowRunResult,
  DisplayMessage,
  ProposalState,
  ToolActivity,
  ToolStatus,
  WorkflowChanges,
  WorkflowProposalWarning,
} from "../types/ai-assistant";
import {
  EMPTY_SESSION,
  useAssistantSessionStore,
} from "../store/assistant-session-store";
import { buildChatHistory } from "../utils/chat-history";
import { canvasFingerprint } from "../utils/canvas-fingerprint";
import { filterTreeFingerprint } from "../utils/filter-tree-fingerprint";
import { parseProposedConditionTree } from "../utils/parse-condition-tree";
import { nextMessageId } from "../utils/message-id";
import { parseSseBuffer } from "../utils/sse-parser";

const CHAT_ENDPOINT = "/api/proxy/ai/chat";
const GENERIC_ERROR = "The assistant request failed";
const INTERRUPTED_ERROR = "The response was interrupted";
const CANCELLED_ERROR = "Cancelled";

interface TextPayload {
  text?: string;
}
interface ErrorPayload {
  message?: string;
}
interface ToolPayload {
  id?: string;
  name?: string;
  status?: ToolStatus;
  truncated?: boolean;
  withheld?: string[];
}
interface ProposalPayload {
  kind?: string;
  content?: string;
  summary?: string;
  warnings?: unknown[];
  canvas_nodes?: Record<string, unknown>[];
  canvas_edges?: Record<string, unknown>[];
  canvas_groups?: Record<string, unknown>[];
  static_attributes?: Record<string, unknown>[];
  changes?: WorkflowChanges;
  query?: ReportQuerySpec;
  name?: string;
  description?: string | null;
  sections?: ReportSection[];
  report_id?: number;
  section_id?: string;
  section_title?: string;
  text?: string;
  tree?: unknown;
  total_count?: number | null;
  token?: unknown;
  expires_at?: unknown;
  device?: unknown;
  commands?: unknown;
  driver_known?: unknown;
  driver_choices?: unknown;
  workflow?: unknown;
  inputs?: unknown;
  devices?: unknown;
  credential_inputs?: unknown;
}

export interface UseAssistantChatOptions {
  /** Which stored conversation this hook shows, for example `workflow_editor:12`. */
  sessionKey: string;
  /** Current surface state, read fresh on every send (a ref keeps this stable). */
  getContext?: () => AssistantContext | undefined;
}

function upsertTool(
  tools: ToolActivity[] | undefined,
  next: ToolActivity,
): ToolActivity[] {
  const current = tools ?? [];
  return current.some((tool) => tool.id === next.id)
    ? current.map((tool) => (tool.id === next.id ? next : tool))
    : [...current, next];
}

const nextId = nextMessageId;

interface ParsedDeviceCommand {
  token: string;
  expiresAt: number;
  device: { id: string; name: string; host: string; platform: string | null };
  commands: string[];
  driverKnown: boolean;
  driverChoices: string[];
}

interface ParsedWorkflowRun {
  token: string;
  expiresAt: number;
  workflow: { id: number; name: string };
  inputs: Record<string, string | number | boolean>;
  devices: WorkflowRunDevice[];
  credentialInputs: string[];
  driverChoices: string[];
}

function isStringList(value: unknown): value is string[] {
  return (
    Array.isArray(value) && value.every((item) => typeof item === "string")
  );
}

/** The workflow-run payload, or null when anything the card needs is missing or mistyped. */
function parseWorkflowRun(payload: ProposalPayload): ParsedWorkflowRun | null {
  const {
    token,
    expires_at: expiresAt,
    workflow,
    inputs,
    devices,
    credential_inputs: credentialInputs,
    driver_choices: driverChoices,
  } = payload;
  if (typeof token !== "string" || !token || typeof expiresAt !== "number") {
    return null;
  }
  if (typeof workflow !== "object" || workflow === null) {
    return null;
  }
  const { id, name } = workflow as Record<string, unknown>;
  if (typeof id !== "number" || typeof name !== "string") {
    return null;
  }
  if (typeof inputs !== "object" || inputs === null || Array.isArray(inputs)) {
    return null;
  }
  const parsedInputs: Record<string, string | number | boolean> = {};
  for (const [key, value] of Object.entries(inputs)) {
    if (
      typeof value !== "string" &&
      typeof value !== "number" &&
      typeof value !== "boolean"
    ) {
      return null;
    }
    parsedInputs[key] = value;
  }
  if (!Array.isArray(devices)) {
    return null;
  }
  const parsedDevices: WorkflowRunDevice[] = [];
  for (const device of devices) {
    const entry = device as Record<string, unknown> | null;
    if (
      !entry ||
      typeof entry.name !== "string" ||
      typeof entry.ip !== "string" ||
      typeof entry.in_inventory !== "boolean"
    ) {
      return null;
    }
    parsedDevices.push({
      name: entry.name,
      ip: entry.ip,
      inInventory: entry.in_inventory,
    });
  }
  if (!isStringList(credentialInputs) || !isStringList(driverChoices)) {
    return null;
  }
  return {
    token,
    expiresAt,
    workflow: { id, name },
    inputs: parsedInputs,
    devices: parsedDevices,
    credentialInputs,
    driverChoices,
  };
}

/** The device-command payload, or null when anything the card needs is missing or mistyped. */
function parseDeviceCommand(
  payload: ProposalPayload,
): ParsedDeviceCommand | null {
  const { token, expires_at: expiresAt, device, commands } = payload;
  if (typeof token !== "string" || !token || typeof expiresAt !== "number") {
    return null;
  }
  if (typeof device !== "object" || device === null) {
    return null;
  }
  const { id, name, host, platform } = device as Record<string, unknown>;
  if (
    typeof id !== "string" ||
    typeof name !== "string" ||
    typeof host !== "string"
  ) {
    return null;
  }
  if (
    !Array.isArray(commands) ||
    commands.length === 0 ||
    !commands.every((command): command is string => typeof command === "string")
  ) {
    return null;
  }
  const choices = payload.driver_choices;
  return {
    token,
    expiresAt,
    device: {
      id,
      name,
      host,
      platform: typeof platform === "string" ? platform : null,
    },
    commands,
    // Unknown unless the server says it is known: the card then asks the user, never guesses.
    driverKnown: payload.driver_known === true,
    driverChoices:
      Array.isArray(choices) && choices.every((c) => typeof c === "string")
        ? (choices as string[])
        : [],
  };
}

/**
 * Client-held chat (the server is stateless): the history is re-sent each turn. Messages live
 * in `useAssistantSessionStore` under `sessionKey`, so they survive leaving and re-entering a
 * page (but not a reload). A running turn is cancelled when the page unmounts or the key
 * changes. Streams the reply over SSE through the Next.js proxy.
 */
export function useAssistantChat({
  sessionKey,
  getContext,
}: UseAssistantChatOptions) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const messages = useAssistantSessionStore(
    (state) => (state.sessions[sessionKey] ?? EMPTY_SESSION).messages,
  );
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const getContextRef = useRef(getContext);

  useEffect(() => {
    getContextRef.current = getContext;
  }, [getContext]);

  // Leaving the page (or switching to another conversation) cancels the running turn.
  useEffect(
    () => () => {
      abortRef.current?.abort();
      abortRef.current = null;
    },
    [sessionKey],
  );

  const patchAssistant = useCallback(
    (id: string, update: (current: DisplayMessage) => DisplayMessage) => {
      useAssistantSessionStore
        .getState()
        .updateMessages(sessionKey, (prev) =>
          prev.map((m) => (m.id === id ? update(m) : m)),
        );
    },
    [sessionKey],
  );

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || abortRef.current) {
        return;
      }

      const history: ChatMessage[] = buildChatHistory(
        (
          useAssistantSessionStore.getState().sessions[sessionKey] ??
          EMPTY_SESSION
        ).messages
          .filter((m) => !m.error && m.content)
          .map(({ role, content }) => ({ role, content })),
        { role: "user", content: trimmed },
      );
      const assistantId = nextId();
      useAssistantSessionStore
        .getState()
        .updateMessages(sessionKey, (prev) => [
          ...prev,
          { id: nextId(), role: "user", content: trimmed },
          { id: assistantId, role: "assistant", content: "" },
        ]);

      const context = getContextRef.current?.();
      const controller = new AbortController();
      abortRef.current = controller;
      setIsStreaming(true);

      const fail = (message: string) =>
        patchAssistant(assistantId, (m) => ({ ...m, error: message }));

      try {
        const response = await fetch(CHAT_ENDPOINT, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(
            context ? { messages: history, context } : { messages: history },
          ),
          signal: controller.signal,
        });

        if (response.status === 401) {
          // The whole session is gone: clear the query cache and every assistant chat too.
          useAuthStore.getState().expireSession(queryClient);
          router.replace("/login");
          return;
        }
        if (!response.ok || !response.body) {
          fail(
            await buildApiErrorMessage(response, () =>
              useAuthStore.getState().markPasswordChangeRequired(),
            ),
          );
          return;
        }

        const reader = response.body
          .pipeThrough(new TextDecoderStream())
          .getReader();
        let buffer = "";
        let sawDone = false;
        for (;;) {
          const { value, done } = await reader.read();
          if (done) {
            break;
          }
          const parsed = parseSseBuffer(buffer + value);
          buffer = parsed.rest;
          for (const { event, data } of parsed.events) {
            if (event === "text") {
              const delta = (data as TextPayload).text ?? "";
              patchAssistant(assistantId, (m) => ({
                ...m,
                content: m.content + delta,
              }));
            } else if (event === "tool") {
              const tool = data as ToolPayload;
              if (tool.id && tool.name && tool.status) {
                const activity: ToolActivity = {
                  id: tool.id,
                  name: tool.name,
                  status: tool.status,
                  truncated: tool.truncated === true,
                  withheld: Array.isArray(tool.withheld) ? tool.withheld : [],
                };
                patchAssistant(assistantId, (m) => ({
                  ...m,
                  tools: upsertTool(m.tools, activity),
                }));
              }
            } else if (event === "proposal") {
              const proposal = data as ProposalPayload;
              if (
                proposal.kind === "template" &&
                typeof proposal.content === "string"
              ) {
                const content = proposal.content;
                const baseContent =
                  context?.surface === "template_editor" ? context.content : "";
                patchAssistant(assistantId, (m) => ({
                  ...m,
                  proposal: {
                    kind: "template",
                    content,
                    summary: proposal.summary ?? "",
                    warnings: (proposal.warnings ?? []) as string[],
                    baseContent,
                    state: "pending",
                  },
                }));
              } else if (proposal.kind === "device_command") {
                const parsed = parseDeviceCommand(proposal);
                if (parsed) {
                  patchAssistant(assistantId, (m) => ({
                    ...m,
                    proposal: {
                      kind: "device_command",
                      summary: `${parsed.commands.join("; ")} on ${parsed.device.name}`,
                      ...parsed,
                      state: "pending",
                    },
                  }));
                }
              } else if (proposal.kind === "workflow_run") {
                const parsed = parseWorkflowRun(proposal);
                if (!parsed) {
                  fail(
                    "The assistant sent a workflow run that could not be read.",
                  );
                  continue;
                }
                patchAssistant(assistantId, (m) => ({
                  ...m,
                  proposal: {
                    kind: "workflow_run",
                    summary: `Run ${parsed.workflow.name}`,
                    ...parsed,
                    state: "pending",
                  },
                }));
              } else if (proposal.kind === "inventory") {
                const tree = parseProposedConditionTree(proposal.tree);
                if (!tree) {
                  fail(
                    "The assistant sent an inventory filter that could not be read.",
                  );
                  continue;
                }
                const baseFingerprint =
                  context?.surface === "inventory" && context.filter_tree
                    ? filterTreeFingerprint(context.filter_tree)
                    : "";
                patchAssistant(assistantId, (m) => ({
                  ...m,
                  proposal: {
                    kind: "inventory",
                    summary: proposal.summary ?? "",
                    tree,
                    totalCount:
                      typeof proposal.total_count === "number"
                        ? proposal.total_count
                        : null,
                    warnings: (proposal.warnings ?? []) as string[],
                    baseFingerprint,
                    state: "pending",
                  },
                }));
              } else if (proposal.kind === "query" && proposal.query) {
                const query = proposal.query;
                patchAssistant(assistantId, (m) => ({
                  ...m,
                  proposal: {
                    kind: "query",
                    summary: proposal.summary ?? "",
                    query,
                    state: "pending",
                  },
                }));
              } else if (
                proposal.kind === "report_outline" &&
                typeof proposal.name === "string" &&
                proposal.sections
              ) {
                const { name, sections } = proposal;
                patchAssistant(assistantId, (m) => ({
                  ...m,
                  proposal: {
                    kind: "report_outline",
                    summary: proposal.summary ?? "",
                    name,
                    description: proposal.description ?? null,
                    sections,
                    state: "pending",
                  },
                }));
              } else if (
                proposal.kind === "section_text" &&
                typeof proposal.report_id === "number" &&
                typeof proposal.section_id === "string" &&
                typeof proposal.text === "string"
              ) {
                const { report_id, section_id, text } = proposal;
                patchAssistant(assistantId, (m) => ({
                  ...m,
                  proposal: {
                    kind: "section_text",
                    summary: proposal.summary ?? "",
                    reportId: report_id,
                    sectionId: section_id,
                    sectionTitle: proposal.section_title ?? section_id,
                    text,
                    state: "pending",
                  },
                }));
              } else if (
                proposal.kind === "workflow" &&
                proposal.canvas_nodes &&
                proposal.changes
              ) {
                const { canvas_nodes, changes } = proposal;
                const baseFingerprint =
                  context?.surface === "workflow_editor"
                    ? canvasFingerprint(
                        context.canvas_nodes,
                        context.canvas_edges,
                      )
                    : "";
                patchAssistant(assistantId, (m) => ({
                  ...m,
                  proposal: {
                    kind: "workflow",
                    summary: proposal.summary ?? "",
                    canvas_nodes,
                    canvas_edges: proposal.canvas_edges ?? [],
                    canvas_groups: proposal.canvas_groups ?? [],
                    static_attributes: proposal.static_attributes ?? [],
                    changes,
                    warnings: (proposal.warnings ??
                      []) as WorkflowProposalWarning[],
                    baseFingerprint,
                    state: "pending",
                  },
                }));
              }
            } else if (event === "error") {
              fail((data as ErrorPayload).message ?? GENERIC_ERROR);
            } else if (event === "done") {
              sawDone = true;
            }
          }
        }
        // A proxy or network cut can end the body without `done`; don't leave a silent,
        // half-finished reply.
        if (!sawDone) {
          fail(INTERRUPTED_ERROR);
        }
      } catch (error) {
        if ((error as Error).name !== "AbortError") {
          fail(GENERIC_ERROR);
        } else {
          // Stop, leaving the page or switching conversation. An empty reply would show a
          // spinner forever once the conversation is restored.
          patchAssistant(assistantId, (m) =>
            m.content || m.proposal ? m : { ...m, error: CANCELLED_ERROR },
          );
        }
      } finally {
        if (abortRef.current === controller || abortRef.current === null) {
          abortRef.current = null;
          setIsStreaming(false);
        }
      }
    },
    [patchAssistant, queryClient, router, sessionKey],
  );

  const setProposalState = useCallback(
    (messageId: string, state: ProposalState) => {
      useAssistantSessionStore
        .getState()
        .updateMessages(sessionKey, (prev) =>
          prev.map((m) =>
            m.id === messageId && m.proposal
              ? { ...m, proposal: { ...m.proposal, state } }
              : m,
          ),
        );
    },
    [sessionKey],
  );

  const completeDeviceCommand = useCallback(
    (messageId: string, result: DeviceCommandResult) => {
      useAssistantSessionStore
        .getState()
        .updateMessages(sessionKey, (prev) =>
          prev.map((m) =>
            m.id === messageId && m.proposal?.kind === "device_command"
              ? { ...m, proposal: { ...m.proposal, state: "applied", result } }
              : m,
          ),
        );
    },
    [sessionKey],
  );

  const completeWorkflowRun = useCallback(
    (messageId: string, result: WorkflowRunResult) => {
      useAssistantSessionStore
        .getState()
        .updateMessages(sessionKey, (prev) =>
          prev.map((m) =>
            m.id === messageId && m.proposal?.kind === "workflow_run"
              ? { ...m, proposal: { ...m.proposal, state: "applied", result } }
              : m,
          ),
        );
    },
    [sessionKey],
  );

  // Null the ref synchronously so a send right after stop/clear is not dropped while the
  // aborted request's `finally` has not run yet.
  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);
  const clear = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
    useAssistantSessionStore.getState().clearSession(sessionKey);
  }, [sessionKey]);

  return useMemo(
    () => ({
      messages,
      isStreaming,
      send,
      stop,
      clear,
      setProposalState,
      completeDeviceCommand,
      completeWorkflowRun,
    }),
    [
      messages,
      isStreaming,
      send,
      stop,
      clear,
      setProposalState,
      completeDeviceCommand,
      completeWorkflowRun,
    ],
  );
}
