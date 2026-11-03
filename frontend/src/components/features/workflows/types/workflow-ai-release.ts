/** A workflow's release for the Ask the Net assistant (backend: WorkflowResponse ai_* fields). */
export interface WorkflowAiRelease {
  ai_released: boolean;
  ai_description: string | null;
  ai_result_node_id: string | null;
  ai_released_at: string | null;
  ai_devices_input: string | null;
  ai_credential_inputs: string[];
  ai_allow_free_ip: boolean;
  /** False when released but a workflow it starts changed, so the assistant no longer offers it. */
  ai_release_current?: boolean;
  visibility: string;
  /** The saved canvas: the release belongs to this version, so steps are listed from it. */
  canvas_nodes: AiReleaseNode[] | null;
  /** The saved run inputs: the devices and credential inputs are chosen from these. */
  static_attributes: AiReleaseInput[] | null;
}

export interface AiReleaseNode {
  id: string;
  type?: string;
  data?: {
    title?: string;
    kind?: string;
    disabled?: boolean;
    pluginConfig?: { device_param?: unknown };
  };
}

export interface AiReleaseInput {
  name: string;
  type: string;
  ref_kind?: string | null;
}

export interface WorkflowAiReleaseRequest {
  description: string;
  result_node_id: string | null;
  devices_input: string | null;
  credential_inputs: string[];
  allow_free_ip: boolean;
}
