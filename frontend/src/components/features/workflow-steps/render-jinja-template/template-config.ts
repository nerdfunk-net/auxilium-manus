export const DEFAULT_RENDER_JINJA_TEMPLATE_CONFIG = {
  output_key: "device_config",
  template:
    "! Generated configuration for {{ device.name }}\nhostname {{ device.hostname }}\n",
  editor_nautobot_source_id: "",
  editor_list_of_attributes: ["interfaces", "config_context", "tags"] as string[],
  editor_sample_device_name: "",
};

export interface RenderJinjaTemplateConfig {
  output_key: string;
  template: string;
  editor_nautobot_source_id: string;
  editor_list_of_attributes: string[];
  editor_sample_device_name: string;
}

export function parseRenderJinjaTemplateConfig(
  config: Record<string, unknown>,
): RenderJinjaTemplateConfig {
  const attributes = config.editor_list_of_attributes;
  return {
    output_key:
      typeof config.output_key === "string" && config.output_key.trim()
        ? config.output_key.trim()
        : DEFAULT_RENDER_JINJA_TEMPLATE_CONFIG.output_key,
    template:
      typeof config.template === "string"
        ? config.template
        : DEFAULT_RENDER_JINJA_TEMPLATE_CONFIG.template,
    editor_nautobot_source_id:
      typeof config.editor_nautobot_source_id === "string"
        ? config.editor_nautobot_source_id
        : "",
    editor_list_of_attributes: Array.isArray(attributes)
      ? attributes.filter((item): item is string => typeof item === "string")
      : [...DEFAULT_RENDER_JINJA_TEMPLATE_CONFIG.editor_list_of_attributes],
    editor_sample_device_name:
      typeof config.editor_sample_device_name === "string"
        ? config.editor_sample_device_name
        : "",
  };
}

export function buildRenderJinjaTemplateConfig(
  config: Record<string, unknown>,
  patch: Partial<RenderJinjaTemplateConfig>,
): Record<string, unknown> {
  return {
    ...config,
    ...patch,
  };
}

export function deriveProducesParsed(config: Record<string, unknown>): string[] {
  const key = parseRenderJinjaTemplateConfig(config).output_key.trim();
  return key ? [key] : [];
}
