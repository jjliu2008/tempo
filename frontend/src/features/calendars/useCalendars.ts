import { useCallback, useEffect, useState } from "react";

import { calendarApi, calendarError } from "../../api/calendars";
import type {
  CalendarInfo,
  CalendarParseInput,
  CalendarProvider,
  CalendarSession,
  CalendarUrlImportInput,
  ParsedCalendar,
} from "../../api/calendars";

export function useCalendars() {
  const [session, setSession] = useState<CalendarSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [provider, setProvider] = useState<CalendarProvider | "">("");
  const [calendars, setCalendars] = useState<CalendarInfo[]>([]);
  const [calendarsLoading, setCalendarsLoading] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [result, setResult] = useState<ParsedCalendar | null>(null);
  const [listVersion, setListVersion] = useState(0);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const next = await calendarApi.session(signal);
      if (signal?.aborted) return;
      setSession(next);
      setProvider((previous) =>
        next.connections.some((connection) => connection.provider === previous)
          ? previous
          : (next.connections[0]?.provider ?? ""),
      );
    } catch (failure) {
      if (!signal?.aborted) setError(calendarError(failure));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    const url = new URL(window.location.href);
    if (url.searchParams.get("calendar") === "google") {
      setNotice(
        url.searchParams.get("status") === "connected"
          ? "Google Calendar connected. Choose the calendars to parse."
          : "Google sign-in was cancelled. You can try again when you’re ready.",
      );
      url.searchParams.delete("calendar");
      url.searchParams.delete("status");
      window.history.replaceState(null, "", url);
    }
    return () => controller.abort();
  }, [refresh]);

  useEffect(() => {
    setResult(null);
    setCalendars([]);
    setSelected([]);
    if (
      !provider ||
      !session?.connections.some((item) => item.provider === provider)
    ) {
      setCalendarsLoading(false);
      return;
    }
    const controller = new AbortController();
    setCalendarsLoading(true);
    void calendarApi
      .list(provider, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setCalendars(data.calendars);
        const initial =
          data.calendars.find((item) => item.primary) ?? data.calendars[0];
        setSelected(initial ? [initial.id] : []);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) setError(calendarError(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) setCalendarsLoading(false);
      });
    return () => controller.abort();
  }, [provider, session, listVersion]);

  async function run(name: string, action: () => Promise<void>) {
    setBusy(name);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (failure) {
      setError(calendarError(failure));
    } finally {
      setBusy(null);
    }
  }

  return {
    session,
    loading,
    busy,
    error,
    notice,
    provider,
    calendars,
    calendarsLoading,
    selected,
    result,
    refresh: () => refresh(),
    retryCalendars: () => {
      setError(null);
      setListVersion((value) => value + 1);
    },
    selectProvider: (value: CalendarProvider) => {
      setError(null);
      setProvider(value);
    },
    toggleCalendar: (id: string) => {
      setResult(null);
      setSelected((previous) =>
        previous.includes(id)
          ? previous.filter((value) => value !== id)
          : [...previous, id],
      );
    },
    clearResult: () => setResult(null),
    signInGoogle: () =>
      run("google", async () => {
        if (!session) return;
        const authorization = await calendarApi.authorizeGoogle(
          session.csrf_token,
        );
        window.location.assign(authorization.authorization_url);
      }),
    connectApple: (email: string, password: string) =>
      run("apple", async () => {
        if (!session) return;
        setSession(
          await calendarApi.connectApple(email, password, session.csrf_token),
        );
        setProvider("apple");
        setNotice("iCloud Calendar connected. Choose the calendars to parse.");
      }),
    disconnect: (value: CalendarProvider) =>
      run(`disconnect-${value}`, async () => {
        if (!session) return;
        await calendarApi.disconnect(value, session.csrf_token);
        setResult(null);
        await refresh();
        setNotice(
          "Calendar disconnected. Saved connection credentials have been removed.",
        );
      }),
    parse: (input: Omit<CalendarParseInput, "calendar_ids">) =>
      run("parse", async () => {
        if (!session || !provider) return;
        setResult(null);
        setResult(
          await calendarApi.parse(
            provider,
            { ...input, calendar_ids: selected },
            session.csrf_token,
          ),
        );
      }),
    importUrl: (input: CalendarUrlImportInput) =>
      run("parse", async () => {
        if (!session) return;
        setResult(null);
        setResult(await calendarApi.importUrl(input, session.csrf_token));
      }),
  };
}
