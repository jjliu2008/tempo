import type { InputEvent } from "../../api/analysis";
import { calendarApi, calendarError } from "../../api/calendars";
import { connectedRange, makeHandoff } from "./live-data.mjs";

/** Parsed events as /analysis takes them: ids, titles and times only. */
export interface EventsHandoff {
  source: "events";
  events: InputEvent[];
  start: string;
  end: string;
  tz: string;
}

export type ConnectedResult =
  | { handoff: EventsHandoff; error?: undefined }
  | { handoff?: undefined; error: string }
  | null;

/**
 * Events from the calendar the user already connected, so /schedule shows
 * their own week without a visit to /calendars first. Returns null when
 * nothing is connected (or the backend is unreachable), where the page keeps
 * its demo fallback. Once a calendar IS connected, failures come back as
 * `error` instead of quietly showing demo data as if it were theirs.
 *
 * Reads the primary calendar only; /calendars is where the sources are chosen.
 */
export async function connectedHandoff(
  signal: AbortSignal,
  now = new Date(),
): Promise<ConnectedResult> {
  let session;
  try {
    session = await calendarApi.session(signal);
  } catch {
    return null;
  }
  const connection = session.connections[0];
  if (!connection) return null;
  const { start, end } = connectedRange(now);
  try {
    const { calendars } = await calendarApi.list(connection.provider, signal);
    const chosen = calendars.find((item) => item.primary) ?? calendars[0];
    if (!chosen) return { error: "Your connected calendar has no calendars." };
    const parsed = await calendarApi.parse(
      connection.provider,
      {
        calendar_ids: [chosen.id],
        start,
        end,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      },
      session.csrf_token,
      signal,
    );
    if (!parsed.events.length) {
      return { error: `No events on "${chosen.name}" from ${start} to ${end}.` };
    }
    // makeHandoff is plain JS and infers source as string; its shape is EventsHandoff.
    return { handoff: makeHandoff(parsed) as EventsHandoff };
  } catch (failure) {
    if (signal.aborted) throw failure;
    return { error: calendarError(failure) };
  }
}
