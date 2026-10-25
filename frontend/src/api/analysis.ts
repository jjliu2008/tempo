import { ApiError, request } from "./client";

/** An already-parsed occurrence, e.g. from /calendars/{provider}/parse. */
export type InputEvent = {
  id: string;
  title: string;
  start: string;
  end: string;
  all_day: boolean;
};

/** Exactly one source. The URL is a password: it only travels in this body. */
export type CalendarAnalyzeRequest = {
  source: "demo" | "ics" | "url" | "events";
  /** Which fictional semester `source: "demo"` loads; default engineering. */
  demo?: "engineering" | "social-crunch" | "work-crunch" | "humanities";
  ics?: string;
  url?: string;
  events?: InputEvent[];
  start?: string;
  end?: string;
  tz?: string;
  gemma?: boolean;
};

export type BreakdownItem = {
  event_id: string;
  title: string;
  kind: "scheduled" | "prep";
  hours: number;
};

export type AnalyzedDay = {
  date: string;
  scheduled_hours: number;
  prep_hours: number;
  total_hours: number;
  breakdown: BreakdownItem[];
};

export type HellWeekReport = {
  headline: string;
  forecast: string;
  advisories: string[];
  source: "gemma" | "template";
};

export type HellWeek = {
  start: string;
  end: string;
  total_hours: number;
  peak_start: string;
  peak_end: string;
  peak_hours: number;
  key_events: {
    event_id: string;
    title: string;
    type: string;
    date: string;
    prep_hours: number;
    stress: number;
  }[];
  report: HellWeekReport | null;
};

export type AnalyzedEvent = {
  id: string;
  title: string;
  /** ISO 8601 in the calendar's timezone, e.g. 2026-10-20T19:00:00-04:00 */
  start: string;
  end: string;
  all_day: boolean;
  type: string;
  prep_hours: number;
  stress: number;
};

export type PrepBlock = {
  event_id: string;
  title: string;
  date: string;
  /** Wall-clock hours from that day's midnight; past 24 means after midnight. */
  start_hour: number;
  end_hour: number;
};

export type CalendarAnalysis = {
  meta: {
    start: string | null;
    end: string | null;
    timezone: string;
    threshold_hours: number;
    median_weekly_hours: number;
    classifier: "gemma" | "keywords";
    unplaced_prep_hours: number;
  };
  days: AnalyzedDay[];
  hell_weeks: HellWeek[];
  events: AnalyzedEvent[];
  prep_blocks: PrepBlock[];
};

export const analysisApi = {
  /** A first Gemma run on a calendar takes about 30 s; repeat titles are cached. */
  analyze: (input: CalendarAnalyzeRequest, signal?: AbortSignal) =>
    request<CalendarAnalysis>("/analysis", {
      method: "POST",
      body: JSON.stringify(input),
      signal,
    }),
};

/** The backend's readable message for a failed request, if it sent one. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError && typeof error.body === "string") {
    try {
      const detail = JSON.parse(error.body)?.detail;
      if (typeof detail?.message === "string") return detail.message;
    } catch {
      // not JSON; fall through
    }
    return error.status === 502 || error.status === 504
      ? "The backend isn't reachable. Is it running on port 8000?"
      : `Request failed (${error.status}).`;
  }
  return "The backend isn't reachable. Is it running on port 8000?";
}
