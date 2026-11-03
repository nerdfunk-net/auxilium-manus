/** A workflow's release for the Ask the Net assistant (backend: WorkflowResponse ai_* fields). */
export interface WorkflowAiRelease {
  ai_released: boolean;
  ai_description: string | null;
  ai_result_node_id: string | null;
  ai_released_at: string | null;
  visibility: string;
  /** The saved canvas: the release belongs to this version, so steps are listed from it. */
  canvas_nodes: Array<{ id: string; type?: string; data?: { title?: string } }> | null;
}

export interface WorkflowAiReleaseRequest {
  description: string;
  result_node_id: string | null;
}
