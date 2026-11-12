"use client";

import Link from "next/link";
import {
  FolderOpen,
  Loader2,
  Save,
  Send,
  Square,
  Trash2,
  Wrench,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useAiConversationsMutations } from "@/hooks/queries/use-ai-conversations-mutations";

import { dataClassLabel } from "../constants/data-classes";
import { useAssistantChat } from "../hooks/use-assistant-chat";
import {
  EMPTY_SESSION,
  useAssistantSessionStore,
} from "../store/assistant-session-store";
import {
  COMMAND_PARSER_LABELS,
  type AssistantContext,
  type ConversationScope,
  type DeviceCommandResult,
  type WorkflowRunResult,
  type DisplayMessage,
  type InventoryProposal,
  type QueryProposal,
  type ReportOutlineProposal,
  type SectionTextProposal,
  type SavedConversation,
  type WorkflowNotesProposal,
  type WorkflowProposal,
} from "../types/ai-assistant";
import {
  fromSavedMessages,
  toSavedMessages,
} from "../utils/conversation-mapping";
import { AssistantMessageText } from "./assistant-message-text";
import { SavedConversationsDialog } from "./saved-conversations-dialog";
import { ConfigDownloadCard } from "./config-download-card";
import { DeviceCommandProposalCard } from "./device-command-proposal-card";
import { WorkflowRunProposalCard } from "./workflow-run-proposal-card";
import { InventoryProposalCard } from "./inventory-proposal-card";
import { QueryProposalCard } from "./query-proposal-card";
import { ReportOutlineCard, SectionTextCard } from "./report-proposal-cards";
import { WorkflowProposalCard } from "./workflow-proposal-card";
import { TemplateProposalCard } from "./template-proposal-card";
import { WorkflowNotesProposalCard } from "./workflow-notes-proposal-card";

/** Where a template proposal is applied: the editor's unsaved buffer. */
export interface TemplateProposalTarget {
  currentContent: string;
  onApply: (content: string) => void;
}

/** Where a workflow proposal is applied: the builder canvas, as unsaved state. */
export interface WorkflowProposalTarget {
  currentFingerprint: string;
  onApply: (proposal: WorkflowProposal) => void;
}

/** Where wiki notes are shown and saved (the open workflow's notes). */
export interface WorkflowNotesTarget {
  /** The saved notes right now. */
  currentNotes: string;
  /** Saves the notes as the user; true when saved (a failure is reported by the target). */
  onApply: (proposal: WorkflowNotesProposal) => Promise<boolean>;
}

/** Where report drafts are applied: the report editor on the Reports tab. */
export interface ReportProposalTarget {
  onApplyOutline: (proposal: ReportOutlineProposal) => void;
  onApplySectionText: (proposal: SectionTextProposal) => void;
}

/** Where an inventory proposal is applied: the inventory builder, as unsaved state. */
export interface InventoryProposalTarget {
  /** Fingerprint of the builder's filter right now (see `filterTreeFingerprint`). */
  currentFingerprint: string;
  onApply: (proposal: InventoryProposal) => void;
}

/** Where a query proposal is applied: the Explore query builder. */
export interface QueryProposalTarget {
  onApply: (proposal: QueryProposal) => void;
}

interface AssistantPanelProps {
  /** Stored conversation to show, for example `workflow_editor:12` (see the session store). */
  sessionKey: string;
  /** Enables Save and Saved conversations for this surface and subject. Omit to hide them. */
  conversationScope?: ConversationScope;
  /** Shown in the input; surfaces use it to say what the assistant can see. */
  placeholder?: string;
  /** Current surface state, sent with every turn (enables the surface's tools). */
  getContext?: () => AssistantContext | undefined;
  templateTarget?: TemplateProposalTarget;
  workflowTarget?: WorkflowProposalTarget;
  notesTarget?: WorkflowNotesTarget;
  queryTarget?: QueryProposalTarget;
  reportTarget?: ReportProposalTarget;
  inventoryTarget?: InventoryProposalTarget;
}

const DEFAULT_PLACEHOLDER = "Ask the assistant…";

const TOOL_LABELS: Record<string, string> = {
  get_template_reference: "Reading the template reference",
  list_templates: "Looking through templates",
  get_template: "Reading a template",
  render_template: "Trial-rendering",
  propose_template: "Preparing a proposal",
  get_workflow_reference: "Reading the workflow guide",
  get_workflow_recipes: "Reading the workflow recipes",
  list_steps: "Looking through workflow steps",
  get_step_schema: "Reading a step's settings",
  list_references: "Looking up credentials, repositories and sources",
  validate_workflow: "Validating the workflow",
  propose_workflow: "Preparing a proposal",
  get_run: "Reading the run",
  get_step_result: "Reading a step's result",
  get_artifact: "Reading stored output",
  list_run_events: "Reading run events",
  list_runs: "Looking up runs",
  get_run_workflow: "Reading the workflow definition",
  list_inventories: "Looking through inventories",
  resolve_inventory: "Resolving an inventory",
  search_devices: "Searching devices",
  get_device_attributes: "Reading device attributes",
  get_inventory_reference: "Reading the inventory guide",
  get_glossary: "Looking up the glossary",
  list_field_values: "Looking up names in Nautobot",
  preview_filter: "Trying a filter",
  propose_inventory: "Preparing an inventory",
  list_datasets: "Looking through report datasets",
  describe_dataset: "Reading a dataset's fields",
  run_query: "Running a report query",
  list_reports: "Looking through saved reports",
  get_report_results: "Reading report results",
  propose_query: "Checking a query",
  propose_report_outline: "Drafting a report",
  propose_section_text: "Drafting section text",
  propose_device_command: "Preparing a device command",
  list_released_workflows: "Looking for released workflows",
  describe_workflow: "Reading a released workflow",
  propose_workflow_run: "Preparing a workflow run",
  get_run_result: "Reading the run result",
  list_config_backups: "Looking for config backups",
  get_config_backup: "Reading a config backup",
  search_config_backups: "Searching config backups",
  get_config_section: "Reading config sections",
  offer_config_download: "Preparing a config download",
  list_playbooks: "Looking for a matching playbook",
  get_playbook: "Reading a playbook",
  list_batfish_networks: "Listing Batfish networks",
  list_batfish_snapshots: "Listing Batfish snapshots",
  get_routes: "Reading routes",
  get_traceroute: "Tracing the path of a packet",
  get_bgp_session_status: "Checking BGP sessions",
  get_interface_properties: "Reading interface settings",
  get_device_facts: "Reading device facts",
  analyze_acl: "Testing a packet against an ACL",
  check_reachability: "Checking reachability",
  query_result: "Reading a stored result",
  fetch_slice: "Reading a stored result",
  diff_results: "Comparing two results",
  compare_filters: "Comparing ACLs between snapshots",
  differential_reachability: "Comparing reachability between snapshots",
  get_snapshot_parse_issues: "Reading the snapshot parse issues",
  get_device_name_matches: "Matching a device name",
  list_interfaces: "Listing the interfaces of a Nautobot device",
  list_snapshot_devices: "Listing the devices of the snapshot",
  get_ip_owners: "Looking up IP address owners",
  list_locations: "Looking through Nautobot locations",
  get_location: "Reading a Nautobot location",
  list_location_types: "Reading Nautobot location types",
  list_roles: "Looking up Nautobot roles",
  list_statuses: "Looking up Nautobot statuses",
  list_tags: "Looking up Nautobot tags",
  list_devices: "Looking through Nautobot devices",
  get_device: "Reading a Nautobot device",
  list_device_types: "Looking up Nautobot device types",
  list_platforms: "Looking up Nautobot platforms",
  list_ip_addresses: "Looking through Nautobot IP addresses",
  list_prefixes: "Looking through Nautobot prefixes",
  list_namespaces: "Looking up Nautobot namespaces",
  get_next_free_ip: "Looking for the next free IP address",
  find_catalyst_center_device: "Looking up a device in Catalyst Center",
  get_catalyst_center_device_details: "Reading Catalyst Center device details",
  find_aci_device: "Looking up a switch in ACI",
  list_aci_devices: "Listing the ACI fabric switches",
  get_aci_device_details: "Reading ACI switch details",
  find_aci_endpoint: "Looking up an address in the ACI fabric",
  list_aci_subnets: "Listing ACI subnets",
  search_aci_epgs: "Searching ACI EPGs",
  get_aci_epg: "Reading an ACI EPG",
  search_aci_contracts: "Searching ACI contracts",
  get_aci_contract: "Reading an ACI contract",
  find_aci_contracts_between: "Finding the ACI contracts between two EPGs",
  list_aci_l3outs: "Listing ACI L3Outs",
  list_aci_endpoints: "Listing ACI endpoints",
  get_aci_endpoint_history: "Reading the history of an ACI endpoint",
  check_aci_connectivity: "Checking the ACI contracts between two hosts",
};

function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name;
}

/**
 * Reusable chat panel. Callers must gate rendering on `useAiAssistantAvailable()` so that
 * nothing assistant-related is shown when the user has switched it off.
 */
const FOLLOW_THRESHOLD_PX = 48;
/** A result handle as the server makes it; anything else is not put into a message. */
const STORED_HANDLE = /^res_[0-9a-f]{12}$/;
/** A ping or traceroute: the only kind of run whose partial result is read after a failure. */
const PROBE_COMMAND = /^(ping|traceroute) /;

export function AssistantPanel({
  sessionKey,
  conversationScope,
  placeholder = DEFAULT_PLACEHOLDER,
  getContext,
  templateTarget,
  workflowTarget,
  notesTarget,
  queryTarget,
  reportTarget,
  inventoryTarget,
}: AssistantPanelProps) {
  const {
    messages,
    isStreaming,
    send,
    stop,
    clear,
    setProposalState,
    completeDeviceCommand,
    completeWorkflowRun,
  } = useAssistantChat({
    sessionKey,
    getContext,
  });
  const draft = useAssistantSessionStore(
    (state) => (state.sessions[sessionKey] ?? EMPTY_SESSION).draft,
  );
  const savedId = useAssistantSessionStore(
    (state) => (state.sessions[sessionKey] ?? EMPTY_SESSION).savedId,
  );
  const [savedOpen, setSavedOpen] = useState(false);
  const isStreamingRef = useRef(false);
  // Follow-ups that finished while an answer was streaming; all are sent as one turn afterwards.
  const pendingFollowUpsRef = useRef<string[]>([]);
  const messageIdsRef = useRef<ReadonlySet<string>>(new Set());
  const scrollRef = useRef<HTMLDivElement>(null);
  // Follow the newest text like a console, unless the user scrolled up to read.
  const followRef = useRef(true);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (el) {
      followRef.current =
        el.scrollHeight - el.scrollTop - el.clientHeight < FOLLOW_THRESHOLD_PX;
    }
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && followRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);
  const { save } = useAiConversationsMutations();

  // After a confirmed device command the assistant is told which stored result holds the output
  // (its handle). The output itself never goes into the chat text: the assistant reads it with
  // fetch_slice, which applies the content opt-in and the redaction again.
  const handleDeviceResult = useCallback(
    (messageId: string, result: DeviceCommandResult) => {
      // The conversation was cleared while the command ran: the card is gone, so a follow-up
      // would start a turn about something the user no longer sees.
      if (!messageIdsRef.current.has(messageId)) {
        return;
      }
      completeDeviceCommand(messageId, result);
      // A failed run is read only when it was a ping/traceroute: the backend stores what finished
      // (the ping) while a timed-out traceroute fails the run. A failed show run keeps no handle.
      const probeOnly = result.commands.every((command) =>
        PROBE_COMMAND.test(command),
      );
      if (
        (result.success || probeOnly) &&
        result.handle &&
        STORED_HANDLE.test(result.handle)
      ) {
        // The parsed rows have their own handle; the raw one is kept for what no template covers.
        const parsedPart =
          result.parsedHandle && STORED_HANDLE.test(result.parsedHandle)
            ? ` I also parsed it with ${COMMAND_PARSER_LABELS[result.parser]}; the parsed rows are stored as ${result.parsedHandle}.`
            : "";
        // A cut output leaves later lines (or whole commands) out of the parsed rows too.
        const cutPart = result.truncated
          ? " The output was cut for size, so the parsed rows may be incomplete."
          : "";
        const failedPart = result.success
          ? ""
          : " The run did not finish (for example a traceroute timed out): only the commands that completed are stored, so say what is missing.";
        const followUp =
          `I ran ${result.commands.join(", ")} on ${result.deviceName}. ` +
          `The output is stored as ${result.handle}.${parsedPart}${cutPart}${failedPart} Please read it and answer my request.`;
        // `send` ignores a message while an answer is streaming, which would lose this one: the
        // user can start another question while the command runs. Hold it until the stream ends.
        if (isStreamingRef.current) {
          pendingFollowUpsRef.current = [
            ...pendingFollowUpsRef.current,
            followUp,
          ];
        } else {
          void send(followUp);
        }
      }
    },
    [completeDeviceCommand, send],
  );

  // The run is asynchronous: the user decides when to ask for the result, and the message carries
  // the run id so the assistant can read it (get_run_result applies the opt-ins and redaction).
  const handleWorkflowRunStarted = useCallback(
    (messageId: string, result: WorkflowRunResult) => {
      if (!messageIdsRef.current.has(messageId)) {
        return;
      }
      completeWorkflowRun(messageId, result);
    },
    [completeWorkflowRun],
  );
  const handleAskRunResult = useCallback(
    (result: WorkflowRunResult, workflowName: string) => {
      void send(
        `I started the workflow "${workflowName}" as run ${result.runId} and it has finished. ` +
          "Please read its result and answer my request.",
      );
    },
    [send],
  );

  useEffect(() => {
    isStreamingRef.current = isStreaming;
    if (!isStreaming && pendingFollowUpsRef.current.length > 0) {
      const followUp = pendingFollowUpsRef.current.join("\n");
      pendingFollowUpsRef.current = [];
      void send(followUp);
    }
  }, [isStreaming, send]);

  // A cleared conversation has nothing for the follow-up to refer to.
  useEffect(() => {
    messageIdsRef.current = new Set(messages.map((message) => message.id));
    if (messages.length === 0) {
      pendingFollowUpsRef.current = [];
    }
  }, [messages]);

  const handleSave = useCallback(() => {
    if (!conversationScope) {
      return;
    }
    save.mutate(
      {
        scope: conversationScope,
        messages: toSavedMessages(messages),
        savedId,
      },
      {
        onSuccess: (saved) =>
          useAssistantSessionStore.getState().setSavedId(sessionKey, saved.id),
      },
    );
  }, [conversationScope, messages, save, savedId, sessionKey]);

  const handleResume = useCallback(
    (conversation: SavedConversation) => {
      stop();
      useAssistantSessionStore
        .getState()
        .loadSaved(
          sessionKey,
          fromSavedMessages(conversation.messages),
          conversation.id,
        );
    },
    [sessionKey, stop],
  );

  const handleDeleted = useCallback(
    (id: number) => {
      if (id === savedId) {
        useAssistantSessionStore.getState().setSavedId(sessionKey, null);
      }
    },
    [savedId, sessionKey],
  );

  const setDraft = useCallback(
    (value: string) =>
      useAssistantSessionStore.getState().setDraft(sessionKey, value),
    [sessionKey],
  );

  const handleSend = useCallback(() => {
    if (!draft.trim() || isStreaming) {
      return;
    }
    followRef.current = true;
    void send(draft);
    setDraft("");
  }, [draft, isStreaming, send, setDraft]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const renderMessage = (message: DisplayMessage) => (
    <div
      key={message.id}
      className={
        message.role === "user"
          ? "ml-8 rounded-md bg-primary/10 p-3 text-sm"
          : "mr-2 space-y-2 rounded-md bg-muted p-3 text-sm"
      }
    >
      {message.tools && message.tools.length > 0 && (
        <ul className="space-y-1" aria-label="Assistant activity">
          {message.tools.map((tool) => (
            <li
              key={tool.id}
              className="flex items-center gap-1 text-xs text-muted-foreground"
            >
              {tool.status === "running" ? (
                <Loader2 className="size-3 animate-spin" />
              ) : (
                <Wrench className="size-3" />
              )}
              {toolLabel(tool.name)}
              {tool.status === "error" && " (failed)"}
              {tool.truncated && " (partial result)"}
              {tool.withheld && tool.withheld.length > 0 && (
                <span className="text-warning-foreground">
                  {" "}
                  – needs {tool.withheld.map(dataClassLabel).join(", ")}{" "}
                  <Link
                    href="/settings/ai-assistant"
                    className="underline underline-offset-2"
                  >
                    enable
                  </Link>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {message.content &&
        (message.role === "assistant" ? (
          <AssistantMessageText markdown={message.content} />
        ) : (
          // What the user typed is shown as typed, never interpreted as Markdown.
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
        ))}
      {message.role === "assistant" &&
        !message.content &&
        !message.error &&
        !message.proposal &&
        !message.tools?.length && (
          <Loader2 className="size-4 animate-spin text-muted-foreground" />
        )}
      {message.proposal?.kind === "device_command" && (
        <DeviceCommandProposalCard
          proposal={message.proposal}
          busy={isStreaming}
          onResult={(result) => handleDeviceResult(message.id, result)}
          onReject={() => setProposalState(message.id, "rejected")}
        />
      )}
      {message.proposal?.kind === "config_download" && (
        <ConfigDownloadCard proposal={message.proposal} />
      )}
      {message.proposal?.kind === "workflow_run" && (
        <WorkflowRunProposalCard
          proposal={message.proposal}
          busy={isStreaming}
          onResult={(result) => handleWorkflowRunStarted(message.id, result)}
          onAskResult={handleAskRunResult}
          onReject={() => setProposalState(message.id, "rejected")}
        />
      )}
      {message.proposal?.kind === "template" && templateTarget && (
        <TemplateProposalCard
          proposal={message.proposal}
          currentContent={templateTarget.currentContent}
          onApply={() => {
            if (message.proposal?.kind === "template") {
              templateTarget.onApply(message.proposal.content);
              setProposalState(message.id, "applied");
            }
          }}
          onReject={() => setProposalState(message.id, "rejected")}
        />
      )}
      {message.proposal?.kind === "workflow" && workflowTarget && (
        <WorkflowProposalCard
          proposal={message.proposal}
          currentFingerprint={workflowTarget.currentFingerprint}
          onApply={() => {
            if (message.proposal?.kind === "workflow") {
              workflowTarget.onApply(message.proposal);
              setProposalState(message.id, "applied");
            }
          }}
          onReject={() => setProposalState(message.id, "rejected")}
        />
      )}
      {message.proposal?.kind === "workflow_notes" && notesTarget && (
        <WorkflowNotesProposalCard
          proposal={message.proposal}
          currentNotes={notesTarget.currentNotes}
          onApply={async () => {
            if (message.proposal?.kind !== "workflow_notes") return false;
            const saved = await notesTarget.onApply(message.proposal);
            if (saved) setProposalState(message.id, "applied");
            return saved;
          }}
          onReject={() => setProposalState(message.id, "rejected")}
        />
      )}
      {message.proposal?.kind === "inventory" && inventoryTarget && (
        <InventoryProposalCard
          proposal={message.proposal}
          currentFingerprint={inventoryTarget.currentFingerprint}
          onApply={() => {
            if (message.proposal?.kind === "inventory") {
              inventoryTarget.onApply(message.proposal);
              setProposalState(message.id, "applied");
            }
          }}
          onReject={() => setProposalState(message.id, "rejected")}
        />
      )}
      {message.proposal?.kind === "query" && queryTarget && (
        <QueryProposalCard
          proposal={message.proposal}
          onApply={() => {
            if (message.proposal?.kind === "query") {
              queryTarget.onApply(message.proposal);
              setProposalState(message.id, "applied");
            }
          }}
          onReject={() => setProposalState(message.id, "rejected")}
        />
      )}
      {message.proposal?.kind === "report_outline" && reportTarget && (
        <ReportOutlineCard
          proposal={message.proposal}
          onApply={() => {
            if (message.proposal?.kind === "report_outline") {
              reportTarget.onApplyOutline(message.proposal);
              setProposalState(message.id, "applied");
            }
          }}
          onReject={() => setProposalState(message.id, "rejected")}
        />
      )}
      {message.proposal?.kind === "section_text" && reportTarget && (
        <SectionTextCard
          proposal={message.proposal}
          onApply={() => {
            if (message.proposal?.kind === "section_text") {
              reportTarget.onApplySectionText(message.proposal);
              setProposalState(message.id, "applied");
            }
          }}
          onReject={() => setProposalState(message.id, "rejected")}
        />
      )}
      {message.savedProposal && (
        <p className="rounded border border-dashed p-2 text-xs text-muted-foreground">
          Earlier {message.savedProposal.kind} proposal (not applicable after
          resuming): {message.savedProposal.summary || "no summary"}
        </p>
      )}
      {message.error && <p className="text-destructive">{message.error}</p>}
    </div>
  );

  return (
    <div
      className="flex h-full min-h-0 flex-col gap-3"
      data-testid="assistant-panel"
    >
      {conversationScope && (
        <div className="flex items-center justify-end gap-1">
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={handleSave}
            disabled={messages.length === 0 || isStreaming || save.isPending}
            title="Save this conversation on the server (secrets are redacted on a best-effort basis)"
          >
            <Save className="size-4" />
            {savedId === null ? "Save" : "Update saved"}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => setSavedOpen(true)}
          >
            <FolderOpen className="size-4" />
            Saved
          </Button>
        </div>
      )}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="min-h-0 flex-1 space-y-3 overflow-y-auto"
        aria-live="polite"
      >
        {messages.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Ask a question. The conversation is kept while you use the app and
            cleared when you reload or sign out.
            {conversationScope && " Use Save to keep it for later."}
          </p>
        ) : (
          messages.map(renderMessage)
        )}
      </div>
      <div className="flex items-end gap-2">
        <Textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={2}
          aria-label="Message the assistant"
          maxLength={20000}
        />
        <div className="flex flex-col gap-1">
          {isStreaming ? (
            <Button
              type="button"
              size="icon"
              variant="outline"
              onClick={stop}
              aria-label="Stop"
            >
              <Square className="size-4" />
            </Button>
          ) : (
            <Button
              type="button"
              size="icon"
              onClick={handleSend}
              disabled={!draft.trim()}
              aria-label="Send"
            >
              <Send className="size-4" />
            </Button>
          )}
          <Button
            type="button"
            size="icon"
            variant="ghost"
            onClick={clear}
            disabled={messages.length === 0}
            aria-label="Clear conversation"
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
      </div>
      {conversationScope && (
        <SavedConversationsDialog
          scope={conversationScope}
          open={savedOpen}
          onOpenChange={setSavedOpen}
          hasCurrentMessages={messages.length > 0}
          currentSavedId={savedId}
          onResume={handleResume}
          onDeleted={handleDeleted}
        />
      )}
    </div>
  );
}
