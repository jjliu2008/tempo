/** JSON from Gemma's reply text, tolerating a Markdown fence around it. */
export function parseReply(text) {
  const cleaned = text.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
  return JSON.parse(cleaned);
}
