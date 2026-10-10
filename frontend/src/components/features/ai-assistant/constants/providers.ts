import type { AiProvider } from "../types/ai-assistant";

export const PROVIDER_LABELS: Record<AiProvider, string> = {
  anthropic: "Anthropic (Claude)",
  gemini: "Google Gemini",
  openai_compat: "OpenAI-compatible (Ollama, LM Studio, …)",
};
