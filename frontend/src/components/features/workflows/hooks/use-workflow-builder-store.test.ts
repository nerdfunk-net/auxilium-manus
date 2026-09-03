import { beforeEach, describe, expect, it } from "vitest";

import type {
  CanvasGroup,
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "../types/workflow-canvas";
import { useWorkflowBuilderStore } from "./use-workflow-builder-store";

const EMPTY_NODES: PersistedCanvasNode[] = [];
const EMPTY_EDGES: WorkflowCanvasEdge[] = [];
const EMPTY_GROUPS: CanvasGroup[] = [];

function makeDraft(userId: number | null, workflowId: number | null = null) {
  return {
    userId,
    workflowId,
    nodes: EMPTY_NODES,
    edges: EMPTY_EDGES,
    groups: EMPTY_GROUPS,
    staticAttributes: [],
    viewport: null,
  };
}

beforeEach(() => {
  useWorkflowBuilderStore.setState({ canvasDraft: null });
  useWorkflowBuilderStore.getState().resetToNew();
});

describe("reconcileDraftOwner", () => {
  it("keeps the draft and metadata when the owner matches (idle-logout resume)", () => {
    const store = useWorkflowBuilderStore.getState();
    store.setCanvasDraft(makeDraft(7, 42));
    useWorkflowBuilderStore.setState({
      workflowId: 42,
      workflowName: "Router upgrade",
      isDirty: true,
    });

    useWorkflowBuilderStore.getState().reconcileDraftOwner(7);

    const next = useWorkflowBuilderStore.getState();
    expect(next.canvasDraft).not.toBeNull();
    expect(next.canvasDraft?.userId).toBe(7);
    expect(next.workflowId).toBe(42);
    expect(next.workflowName).toBe("Router upgrade");
    expect(next.isDirty).toBe(true);
  });

  it("wipes the draft and metadata when a different user logs in", () => {
    const store = useWorkflowBuilderStore.getState();
    store.setCanvasDraft(makeDraft(7, 42));
    useWorkflowBuilderStore.setState({
      workflowId: 42,
      workflowUuid: "uuid-42",
      workflowName: "Router upgrade",
      isDirty: true,
      selectedNodeId: "node-1",
    });

    useWorkflowBuilderStore.getState().reconcileDraftOwner(9);

    const next = useWorkflowBuilderStore.getState();
    expect(next.canvasDraft).toBeNull();
    expect(next.workflowId).toBeNull();
    expect(next.workflowUuid).toBeNull();
    expect(next.workflowName).toBe("Untitled Workflow");
    expect(next.isDirty).toBe(false);
    expect(next.selectedNodeId).toBeNull();
  });

  it("wipes a pre-identity draft (userId null) for any logged-in user", () => {
    useWorkflowBuilderStore.getState().setCanvasDraft(makeDraft(null, null));

    useWorkflowBuilderStore.getState().reconcileDraftOwner(3);

    expect(useWorkflowBuilderStore.getState().canvasDraft).toBeNull();
  });

  it("is a no-op on a blank store with no draft", () => {
    const before = useWorkflowBuilderStore.getState();
    useWorkflowBuilderStore.getState().reconcileDraftOwner(5);
    const after = useWorkflowBuilderStore.getState();

    expect(after.canvasDraft).toBeNull();
    expect(after.workflowName).toBe(before.workflowName);
    expect(after.lastAction).toBe(before.lastAction);
  });

  it("clears a stale draft even when the previous owner id is unknown but equal to null target", () => {
    // A different user whose id we somehow read as null must still not inherit
    // an owned draft — matched only when both sides are a real, equal id.
    useWorkflowBuilderStore.getState().setCanvasDraft(makeDraft(7, 1));

    useWorkflowBuilderStore.getState().reconcileDraftOwner(null);

    expect(useWorkflowBuilderStore.getState().canvasDraft).toBeNull();
  });
});

describe("resetToNew", () => {
  it("restores blank metadata", () => {
    useWorkflowBuilderStore.setState({
      workflowId: 5,
      workflowName: "Something",
      isDirty: true,
      selectedNodeId: "node-9",
    });

    useWorkflowBuilderStore.getState().resetToNew();

    const next = useWorkflowBuilderStore.getState();
    expect(next.workflowId).toBeNull();
    expect(next.workflowName).toBe("Untitled Workflow");
    expect(next.isDirty).toBe(false);
    expect(next.selectedNodeId).toBeNull();
    expect(next.lastAction).toBe("New workflow created");
  });
});

describe("requestWorkflowLoad / clearPendingWorkflowLoad", () => {
  it("queues a load request with the thenRuns flag", () => {
    useWorkflowBuilderStore.getState().requestWorkflowLoad(42, true);
    expect(useWorkflowBuilderStore.getState().pendingWorkflowLoad).toEqual({
      workflowId: 42,
      thenRuns: true,
    });
  });

  it("defaults thenRuns to false", () => {
    useWorkflowBuilderStore.getState().requestWorkflowLoad(7);
    expect(useWorkflowBuilderStore.getState().pendingWorkflowLoad).toEqual({
      workflowId: 7,
      thenRuns: false,
    });
  });

  it("clears the pending request", () => {
    useWorkflowBuilderStore.getState().requestWorkflowLoad(7);
    useWorkflowBuilderStore.getState().clearPendingWorkflowLoad();
    expect(useWorkflowBuilderStore.getState().pendingWorkflowLoad).toBeNull();
  });
});
