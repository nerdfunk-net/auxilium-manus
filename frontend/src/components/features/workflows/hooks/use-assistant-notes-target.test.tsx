import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkflowNotesProposal } from "@/components/features/ai-assistant/types/ai-assistant";

import { useAssistantNotesTarget } from "./use-assistant-notes-target";
import { useWorkflowBuilderStore } from "./use-workflow-builder-store";

const h = vi.hoisted(() => ({ mutateAsync: vi.fn(), toast: vi.fn() }));

vi.mock("@/hooks/queries/use-workflow-notes-mutation", () => ({
  useWorkflowNotesMutation: () => ({ mutateAsync: h.mutateAsync }),
}));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast: h.toast }) }));

const proposal: WorkflowNotesProposal = {
  kind: "workflow_notes",
  workflowId: 4,
  summary: "s",
  notes: "new notes",
  baseNotes: "old",
  warnings: [],
  state: "pending",
};

beforeEach(() => {
  vi.clearAllMocks();
  useWorkflowBuilderStore.setState({ workflowNotes: "old" });
});

describe("useAssistantNotesTarget", () => {
  it("exposes the saved notes", () => {
    const { result } = renderHook(() => useAssistantNotesTarget(4));
    expect(result.current.currentNotes).toBe("old");
  });

  it("saves the proposal and updates the store", async () => {
    h.mutateAsync.mockResolvedValue({ notes: "new notes" });
    const { result } = renderHook(() => useAssistantNotesTarget(4));

    let saved = false;
    await act(async () => {
      saved = await result.current.onApply(proposal);
    });

    expect(saved).toBe(true);
    expect(h.mutateAsync).toHaveBeenCalledWith("new notes");
    expect(useWorkflowBuilderStore.getState().workflowNotes).toBe("new notes");
  });

  it("reports a failed save and leaves the store alone", async () => {
    h.mutateAsync.mockRejectedValue(new Error("Access denied"));
    const { result } = renderHook(() => useAssistantNotesTarget(4));

    let saved = true;
    await act(async () => {
      saved = await result.current.onApply(proposal);
    });

    expect(saved).toBe(false);
    expect(useWorkflowBuilderStore.getState().workflowNotes).toBe("old");
    expect(h.toast).toHaveBeenCalledWith(
      expect.objectContaining({
        description: "Access denied",
        variant: "destructive",
      }),
    );
  });

  it("refuses a proposal for another workflow without calling the API", async () => {
    const { result } = renderHook(() => useAssistantNotesTarget(9));

    let saved = true;
    await act(async () => {
      saved = await result.current.onApply(proposal);
    });

    expect(saved).toBe(false);
    expect(h.mutateAsync).not.toHaveBeenCalled();
  });
});
