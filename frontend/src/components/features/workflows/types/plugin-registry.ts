export interface PluginIOField {
  name: string;
  description: string;
  data_type: string;
  required: boolean;
  default?: unknown;
  example?: unknown;
}

export interface PluginStepOutcome {
  name: string;
}

export interface PluginMetadata {
  configuration_input: PluginIOField[];
}

export interface PluginDefinition {
  id: string;
  name: string;
  overview: string;
  description: string;
  artifact_type: string;
  palette_category?: string | null;
  directory: string;
  enabled: boolean;
  requires: string[];
  produces: string[];
  consumes: string[];
  requires_parsed: string[];
  produces_parsed: string[];
  outcomes: PluginStepOutcome[];
  metadata: PluginMetadata;
  primary_output?: string;
}

export interface PluginListResponse {
  plugins: PluginDefinition[];
}
