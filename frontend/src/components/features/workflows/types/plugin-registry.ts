export interface PluginStepOutcome {
  name: string;
}

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
  data_type?: string;
  example?: unknown;
}

export interface PluginMetadata {
  mandatory_input: PluginIOField[];
  configuration_input: PluginIOField[];
  outcomes: PluginOutcome[];
}

export interface PluginDefinition {
  id: string;
  name: string;
  description: string;
  artifact_type: string;
  directory: string;
  enabled: boolean;
  requires: string[];
  produces: string[];
  consumes: string[];
  requires_parsed: string[];
  produces_parsed: string[];
  outcomes: PluginStepOutcome[];
  metadata: PluginMetadata;
}

export interface PluginListResponse {
  plugins: PluginDefinition[];
}
