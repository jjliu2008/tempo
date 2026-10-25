import { ApiError, request } from "./client";

export type CalendarProvider = "google" | "apple";
export type CalendarSource = CalendarProvider | "url";
export type CalendarConnection = {
  provider: CalendarProvider;
  account: string;
  connected_at: string;
};
export type CalendarSession = {
  csrf_token: string;
  google_configured: boolean;
  connections: CalendarConnection[];
};
export type CalendarInfo = {
  id: string;
  name: string;
  timezone: string | null;
  primary: boolean;
};
export type CalendarParseInput = {
  calendar_ids: string[];
  start: string;
  end: string;
  timezone: string;
};
export type CalendarUrlImportInput = Omit<
  CalendarParseInput,
  "calendar_ids"
> & { url: string };
export type ParsedEvent = {
  provider: CalendarSource;
  calendar_id: string;
  calendar_name: string;
  id: string;
  title: string;
  start: string;
  end: string;
  all_day: boolean;
  duration_hours: number;
  location: string;
  description: string;
};
export type ParsedCalendar = {
  provider: CalendarSource;
  start: string;
  end: string;
  timezone: string;
  events: ParsedEvent[];
};

const options = (csrf?: string): RequestInit => ({
  credentials: "include",
  ...(csrf ? { headers: { "X-CSRF-Token": csrf } } : {}),
});

export const calendarApi = {
  session: (signal?: AbortSignal) =>
    request<CalendarSession>("/calendars/session", { ...options(), signal }),
  authorizeGoogle: (csrf: string) =>
    request<{ authorization_url: string }>("/calendars/google/authorize", {
      ...options(csrf),
      method: "POST",
    }),
  connectApple: (email: string, app_password: string, csrf: string) =>
    request<CalendarSession>("/calendars/apple/connect", {
      ...options(csrf),
      method: "POST",
      body: JSON.stringify({ email, app_password }),
    }),
  list: (provider: CalendarProvider, signal?: AbortSignal) =>
    request<{ provider: CalendarProvider; calendars: CalendarInfo[] }>(
      `/calendars/${provider}/calendars`,
      { ...options(), signal },
    ),
  parse: (
    provider: CalendarProvider,
    input: CalendarParseInput,
    csrf: string,
    signal?: AbortSignal,
  ) =>
    request<ParsedCalendar>(`/calendars/${provider}/parse`, {
      ...options(csrf),
      method: "POST",
      body: JSON.stringify(input),
      signal,
    }),
  importUrl: (input: CalendarUrlImportInput, csrf: string) =>
    request<ParsedCalendar>("/calendars/import", {
      ...options(csrf),
      method: "POST",
      body: JSON.stringify(input),
    }),
  disconnect: (provider: CalendarProvider, csrf: string) =>
    request<void>(`/calendars/${provider}`, {
      ...options(csrf),
      method: "DELETE",
    }),
};

export function calendarError(error: unknown): string {
  if (error instanceof ApiError && typeof error.body === "string") {
    try {
      const parsed = JSON.parse(error.body) as {
        detail?: { message?: string } | { msg?: string }[];
      };
      if (Array.isArray(parsed.detail)) {
        return parsed.detail
          .map((item) => item.msg ?? "Invalid input")
          .join(". ");
      }
      if (parsed.detail?.message) return parsed.detail.message;
    } catch {
      // Non-JSON proxy/network errors need an actionable public message too.
    }
  }
  return "The calendar request could not be completed. Check your connection and try again.";
}
