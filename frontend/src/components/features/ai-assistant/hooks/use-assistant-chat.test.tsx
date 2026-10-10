import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/lib/auth-store";

import type {
  AssistantContext,
  TemplateProposal,
  WorkflowProposal,
} from "../types/ai-assistant";
import { canvasFingerprint } from "../utils/canvas-fingerprint";
import { useAssistantChat } from "./use-assistant-chat";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const fetchMock = vi.fn();

/** `event: x\ndata: {...}\n\n` frame as the backend emits it. */
const frame = (event: string, data: unknown) =>
  `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

const encoder = new TextEncoder();

function sseResponse(chunks: string[], status = 200): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
  return new Response(body, {
    status,
    headers: { "Content-Type": "text/event-stream" },
  });
}

/** A stream that stays open until the request is aborted, like a slow model. */
function hangingResponse(signal: AbortSignal, first?: string): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      if (first) {
        controller.enqueue(encoder.encode(first));
      }
      signal.addEventListener("abort", () =>
        controller.error(new DOMException("Aborted", "AbortError")),
      );
    },
  });
  return new Response(body, { status: 200 });
}

const jsonResponse = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

function lastRequestBody(): Record<string, unknown> {
  const calls = fetchMock.mock.calls;
  return JSON.parse(calls[calls.length - 1][1].body as string);
}

async function send(
  result: { current: ReturnType<typeof useAssistantChat> },
  text: string,
) {
  await act(async () => {
    await result.current.send(text);
  });
}

beforeEach(() => {
  fetchMock.mockReset();
  replace.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useAssistantChat", () => {
  it("streams text into the assistant message and posts the history", async () => {
    fetchMock.mockResolvedValue(
      sseResponse([
        frame("text", { text: "Hel" }),
        frame("text", { text: "lo" }),
        frame("usage", { input_tokens: 1, output_tokens: 1 }),
        frame("done", {}),
      ]),
    );
    const { result } = renderHook(() => useAssistantChat());

    await send(result, "  hi  ");

    expect(result.current.messages.map((m) => [m.role, m.content])).toEqual([
      ["user", "hi"],
      ["assistant", "Hello"],
    ]);
    expect(result.current.messages[1].error).toBeUndefined();
    expect(result.current.isStreaming).toBe(false);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/proxy/ai/chat");
    expect(lastRequestBody()).toEqual({
      messages: [{ role: "user", content: "hi" }],
    });
  });

  it("reassembles a frame that arrives split across chunks", async () => {
    const whole = frame("text", { text: "split" });
    fetchMock.mockResolvedValue(
      sseResponse([whole.slice(0, 12), whole.slice(12), frame("done", {})]),
    );
    const { result } = renderHook(() => useAssistantChat());

    await send(result, "go");

    expect(result.current.messages[1].content).toBe("split");
    expect(result.current.messages[1].error).toBeUndefined();
  });

  it("ignores blank messages", async () => {
    const { result } = renderHook(() => useAssistantChat());

    await send(result, "   ");

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.messages).toEqual([]);
  });

  it("updates a tool chip in place by id", async () => {
    fetchMock.mockResolvedValue(
      sseResponse([
        frame("tool", { id: "t1", name: "list_steps", status: "running" }),
        frame("tool", {
          id: "t1",
          name: "list_steps",
          status: "done",
          truncated: true,
          withheld: ["content_data"],
        }),
        frame("tool", { id: "t2", name: "get_run", status: "error" }),
        frame("done", {}),
      ]),
    );
    const { result } = renderHook(() => useAssistantChat());

    await send(result, "go");

    expect(result.current.messages[1].tools).toEqual([
      {
        id: "t1",
        name: "list_steps",
        status: "done",
        truncated: true,
        withheld: ["content_data"],
      },
      {
        id: "t2",
        name: "get_run",
        status: "error",
        truncated: false,
        withheld: [],
      },
    ]);
  });

  it("sends the fresh surface context and keeps the editor content a template proposal was based on", async () => {
    const context: AssistantContext = {
      surface: "template_editor",
      name: "t",
      description: null,
      template_type: "jinja2",
      content: "hostname {{ x }}",
      variables: [],
    };
    fetchMock.mockResolvedValue(
      sseResponse([
        frame("proposal", {
          kind: "template",
          content: "hostname {{ y }}",
          summary: "rename",
          warnings: ["w"],
        }),
        frame("done", {}),
      ]),
    );
    const { result } = renderHook(() =>
      useAssistantChat({ getContext: () => context }),
    );

    await send(result, "change it");

    expect(lastRequestBody().context).toEqual(context);
    expect(result.current.messages[1].proposal).toEqual<TemplateProposal>({
      kind: "template",
      content: "hostname {{ y }}",
      summary: "rename",
      warnings: ["w"],
      baseContent: "hostname {{ x }}",
      state: "pending",
    });
  });

  it("fingerprints the canvas as it was when a workflow proposal was requested", async () => {
    const nodes = [{ id: "a", data: { kind: "k", title: "A" } }];
    const edges: Record<string, unknown>[] = [];
    const context: AssistantContext = {
      surface: "workflow_editor",
      name: "w",
      canvas_nodes: nodes,
      canvas_edges: edges,
      canvas_groups: [],
      static_attributes: [],
    };
    const changes = {
      nodes_added: [],
      nodes_removed: [],
      nodes_changed: [],
      edges_added: [],
      edges_removed: [],
      static_attributes_changed: false,
    };
    fetchMock.mockResolvedValue(
      sseResponse([
        frame("proposal", {
          kind: "workflow",
          summary: "s",
          canvas_nodes: [{ id: "b" }],
          canvas_edges: [],
          canvas_groups: [],
          static_attributes: [],
          changes,
          warnings: [{ node_id: null, code: "c", message: "m" }],
        }),
        frame("done", {}),
      ]),
    );
    const { result } = renderHook(() =>
      useAssistantChat({ getContext: () => context }),
    );

    await send(result, "build");

    const proposal = result.current.messages[1].proposal as WorkflowProposal;
    expect(proposal.kind).toBe("workflow");
    expect(proposal.baseFingerprint).toBe(canvasFingerprint(nodes, edges));
    expect(proposal.canvas_nodes).toEqual([{ id: "b" }]);
    expect(proposal.warnings).toHaveLength(1);
    expect(proposal.state).toBe("pending");
  });

  it("drops a malformed proposal instead of showing a broken card", async () => {
    fetchMock.mockResolvedValue(
      sseResponse([
        frame("proposal", { kind: "template" }),
        frame("proposal", { kind: "workflow", canvas_nodes: [] }),
        frame("proposal", { kind: "unknown", content: "x" }),
        frame("done", {}),
      ]),
    );
    const { result } = renderHook(() => useAssistantChat());

    await send(result, "go");

    expect(result.current.messages[1].proposal).toBeUndefined();
  });

  it("marks the reply failed on an error event and leaves it out of the next history", async () => {
    fetchMock
      .mockResolvedValueOnce(
        sseResponse([
          frame("text", { text: "partial" }),
          frame("error", { code: "provider_auth", message: "Key rejected" }),
          frame("done", {}),
        ]),
      )
      .mockResolvedValueOnce(
        sseResponse([frame("text", { text: "ok" }), frame("done", {})]),
      );
    const { result } = renderHook(() => useAssistantChat());

    await send(result, "first");
    expect(result.current.messages[1].error).toBe("Key rejected");

    await send(result, "second");
    expect(lastRequestBody().messages).toEqual([
      { role: "user", content: "first" },
      { role: "user", content: "second" },
    ]);
  });

  it("reports an interrupted reply when the stream ends without done", async () => {
    fetchMock.mockResolvedValue(
      sseResponse([frame("text", { text: "half an ans" })]),
    );
    const { result } = renderHook(() => useAssistantChat());

    await send(result, "go");

    expect(result.current.messages[1].content).toBe("half an ans");
    expect(result.current.messages[1].error).toBe(
      "The response was interrupted",
    );
    expect(result.current.isStreaming).toBe(false);
  });

  it("redirects to login on 401", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 401 }));
    const { result } = renderHook(() => useAssistantChat());

    await send(result, "go");

    expect(replace).toHaveBeenCalledWith("/login");
    expect(result.current.messages[1].error).toBe("Authentication required");
  });

  it("shows the server's message for a failed request", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(409, {
        detail: { code: "ai_assistant_not_configured", message: "No key" },
      }),
    );
    const { result } = renderHook(() => useAssistantChat());

    await send(result, "go");

    expect(result.current.messages[1].error).toBe("No key");
    expect(result.current.isStreaming).toBe(false);
  });

  it("flags a forced password change from a 403", async () => {
    const markPasswordChangeRequired = vi.fn();
    const original = useAuthStore.getState().markPasswordChangeRequired;
    useAuthStore.setState({ markPasswordChangeRequired });
    fetchMock.mockResolvedValue(
      jsonResponse(403, {
        detail: { code: "password_change_required", message: "Change it" },
      }),
    );
    const { result } = renderHook(() => useAssistantChat());

    await send(result, "go");

    expect(markPasswordChangeRequired).toHaveBeenCalled();
    useAuthStore.setState({ markPasswordChangeRequired: original });
  });

  it("shows a generic error when the network fails", async () => {
    fetchMock.mockRejectedValue(new TypeError("network down"));
    const { result } = renderHook(() => useAssistantChat());

    await send(result, "go");

    expect(result.current.messages[1].error).toBe(
      "The assistant request failed",
    );
  });

  it("ignores a send while a reply is streaming", async () => {
    fetchMock.mockImplementation((_url, init: RequestInit) =>
      Promise.resolve(hangingResponse(init.signal as AbortSignal)),
    );
    const { result } = renderHook(() => useAssistantChat());

    let first: Promise<void> = Promise.resolve();
    await act(async () => {
      first = result.current.send("one");
      await Promise.resolve();
    });
    await send(result, "two");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.isStreaming).toBe(true);

    await act(async () => {
      result.current.stop();
      await first;
    });
  });

  it("stop aborts quietly and a send right after is accepted", async () => {
    fetchMock
      .mockImplementationOnce((_url, init: RequestInit) =>
        Promise.resolve(
          hangingResponse(
            init.signal as AbortSignal,
            frame("text", { text: "typing" }),
          ),
        ),
      )
      .mockResolvedValueOnce(
        sseResponse([frame("text", { text: "next" }), frame("done", {})]),
      );
    const { result } = renderHook(() => useAssistantChat());

    let first: Promise<void> = Promise.resolve();
    await act(async () => {
      first = result.current.send("one");
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
    expect(result.current.messages[1].content).toBe("typing");

    await act(async () => {
      result.current.stop();
      // Not awaiting the aborted request: a new send must not be dropped meanwhile.
      await result.current.send("two");
      await first;
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(result.current.messages[1].error).toBeUndefined();
    expect(result.current.messages[3].content).toBe("next");
    expect(result.current.isStreaming).toBe(false);
  });

  it("setProposalState changes only the targeted proposal", async () => {
    fetchMock.mockResolvedValue(
      sseResponse([
        frame("proposal", {
          kind: "template",
          content: "b",
          summary: "s",
        }),
        frame("done", {}),
      ]),
    );
    const { result } = renderHook(() => useAssistantChat());
    await send(result, "go");
    const assistantId = result.current.messages[1].id;

    act(() => result.current.setProposalState(assistantId, "applied"));
    expect(result.current.messages[1].proposal?.state).toBe("applied");

    act(() => result.current.setProposalState("nope", "rejected"));
    expect(result.current.messages[1].proposal?.state).toBe("applied");
  });

  it("clear empties the conversation", async () => {
    fetchMock.mockResolvedValue(sseResponse([frame("done", {})]));
    const { result } = renderHook(() => useAssistantChat());
    await send(result, "go");

    act(() => result.current.clear());

    expect(result.current.messages).toEqual([]);
    expect(result.current.isStreaming).toBe(false);
  });
});
