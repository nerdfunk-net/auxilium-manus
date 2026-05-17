export interface PluginIOField {
  name: string;
  description: string;
  data_type: string;
  required: boolean;
  default?: unknown;
  example?: unknown;
}

export interface PluginOutcome {
  name: string;
  description: string;
}

export interface PluginMetadata {
  mandatory_input: PluginIOField[];
  configuration_input: PluginIOField[];
  supported_output: PluginIOField[];
  outcomes: PluginOutcome[];
}

export interface PluginDefinition {
  id: string;
  name: string;
  description: string;
  artifact_type: string;
  filename: string;
  enabled: boolean;
  metadata: PluginMetadata;
}

export interface PluginListResponse {
  plugins: PluginDefinition[];
}
