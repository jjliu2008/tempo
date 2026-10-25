import { request } from "./client";

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export type GemmaContext = string | JsonValue[] | { [key: string]: JsonValue };

export type GemmaMessage = {
  role: "user" | "model";
  content: string;
  context?: GemmaContext | null;
};

export type GemmaRequest = {
  prompt: string;
  system_prompt?: string | null;
  context?: GemmaContext | null;
  history?: GemmaMessage[];
  temperature?: number | null;
  max_output_tokens?: number | null;
};

export type GemmaResponse = {
  text: string;
  model: string;
  history: GemmaMessage[];
  finish_reason: string | null;
  usage: {
    input_tokens: number | null;
    output_tokens: number | null;
    total_tokens: number | null;
  };
};

export type GemmaAgentRequest = GemmaRequest & {
  id: string;
  depends_on?: string[];
};

export type GemmaMultiAgentRequest = {
  agents: GemmaAgentRequest[];
  system_prompt?: string | null;
  context?: GemmaContext | null;
};

export type GemmaMultiAgentResponse = {
  results: (GemmaResponse & { id: string })[];
};

/** Shared across features; Google's key is held only by the backend. */
export const gemma = {
  generate: (input: GemmaRequest, signal?: AbortSignal) =>
    request<GemmaResponse>("/gemma/generate", {
      method: "POST",
      body: JSON.stringify(input),
      signal,
    }),
  runAgents: (input: GemmaMultiAgentRequest, signal?: AbortSignal) =>
    request<GemmaMultiAgentResponse>("/gemma/agents", {
      method: "POST",
      body: JSON.stringify(input),
      signal,
    }),
};
