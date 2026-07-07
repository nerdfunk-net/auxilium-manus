export const DEFAULT_RENDER_JINJA_TEMPLATE_CONFIG = {
  output_key: "device_config",
  template_id: null as number | null,
};

export interface RenderJinjaTemplateConfig {
  output_key: string;
  template_id: number | null;
}

function coerceTemplateId(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function parseRenderJinjaTemplateConfig(
  config: Record<string, unknown>,
): RenderJinjaTemplateConfig {
  return {
    output_key:
      typeof config.output_key === "string" && config.output_key.trim()
        ? config.output_key.trim()
        : DEFAULT_RENDER_JINJA_TEMPLATE_CONFIG.output_key,
    template_id: coerceTemplateId(config.template_id),
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
