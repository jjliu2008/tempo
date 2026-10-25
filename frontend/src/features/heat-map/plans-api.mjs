import { gemma } from '../../api/gemma.ts';
import { adviceRequest, parseAdvice } from './advice-model.mjs';
import { parseReply } from './gemma-reply.mjs';
import { parseRemixPlan, remixRequest } from './remix-model.mjs';

async function ask(request, signal) {
  const response = await gemma.generate({ ...request, temperature: 0.6, max_output_tokens: 2048 }, signal);
  return parseReply(response.text);
}

/** Gemma's plan for one week and mode, validated against that week's events. */
export async function fetchRemixPlan(mode, events, social, signal) {
  const plan = parseRemixPlan(await ask(remixRequest(mode, events, social), signal), events);
  if (!plan) throw new Error('Gemma returned an invalid plan.');
  return plan;
}

/** {event id: {verdict, text}} for the events Gemma answered; `mix` is the chosen remix, or null for the original week. */
export async function fetchAdvice(events, social, mix, signal) {
  return parseAdvice(await ask(adviceRequest(events, social, mix), signal), events);
}
