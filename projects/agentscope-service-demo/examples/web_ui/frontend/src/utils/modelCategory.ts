export type ProviderModelCategory =
  "llm" | "rerank" | "embedding" | "stt" | "tts";

export const PROVIDER_MODEL_CATEGORY_LABEL: Record<
  ProviderModelCategory,
  string
> = {
  llm: "LLM",
  embedding: "Text Embedding",
  rerank: "Rerank",
  stt: "Speech2text",
  tts: "TTS",
};

/**
 * A model is categorized only when the provider supplied an explicit,
 * recognized capability. Model names are deliberately not guessed: a custom
 * OpenAI-compatible endpoint may use any naming convention.
 */
export function explicitProviderModelCategory(
  category: unknown,
): ProviderModelCategory | null {
  return typeof category === "string" &&
    category in PROVIDER_MODEL_CATEGORY_LABEL
    ? (category as ProviderModelCategory)
    : null;
}
