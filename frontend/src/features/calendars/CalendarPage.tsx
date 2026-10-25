import { useState } from "react";
import type { FormEvent } from "react";

import type { CalendarProvider, ParsedEvent } from "../../api/calendars";
import { giveHandoff } from "../heat-map/live-data.mjs";
import AppleConnectForm from "./AppleConnectForm";
import { useCalendars } from "./useCalendars";
import "./calendars.css";

const providerNames = { google: "Google Calendar", apple: "iCloud Calendar" };

function localDate(value: Date): string {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function schedule(event: ParsedEvent, timezone: string): string {
  const date = new Intl.DateTimeFormat(undefined, {
    timeZone: timezone,
    month: "short",
    day: "numeric",
  });
  if (event.all_day) return `${date.format(new Date(event.start))} · All day`;
  const time = new Intl.DateTimeFormat(undefined, {
    timeZone: timezone,
    hour: "numeric",
    minute: "2-digit",
  });
  return `${date.format(new Date(event.start))}, ${time.format(new Date(event.start))} – ${date.format(new Date(event.end))}, ${time.format(new Date(event.end))}`;
}

export default function CalendarPage() {
  const calendar = useCalendars();
  const [appleOpen, setAppleOpen] = useState(false);
  const [source, setSource] = useState<"account" | "url">(() =>
    new URLSearchParams(window.location.search).get("source") === "url"
      ? "url"
      : "account",
  );
  const [url, setUrl] = useState("");
  const [start, setStart] = useState(() => localDate(new Date()));
  const [end, setEnd] = useState(() => {
    const value = new Date();
    value.setDate(value.getDate() + 30);
    return localDate(value);
  });
  const [timezone, setTimezone] = useState(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  );
  const blocked = calendar.busy !== null;
  const appleConnected = calendar.session?.connections.some(
    (item) => item.provider === "apple",
  );
  const fromUrl = source === "url" || !calendar.session?.connections.length;

  function parse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (fromUrl) void calendar.importUrl({ url, start, end, timezone });
    else void calendar.parse({ start, end, timezone });
  }

  return (
    <main className="calendar-page">
      <title>Calendar connections · Tempo</title>
      <a className="calendar-back" href="/schedule">
        Back to your schedule
      </a>
      <header className="calendar-heading">
        <h1>Connect your calendar</h1>
        <p>
          Connect Google or iCloud, or paste a calendar link. Import your
          schedule with recurring and all-day events, in the timezone you
          choose.
        </p>
      </header>

      {calendar.error && (
        <div className="calendar-message calendar-error" role="alert">
          <p>{calendar.error}</p>
          {!calendar.session && (
            <button
              type="button"
              onClick={() => void calendar.refresh()}
              disabled={calendar.loading}
            >
              Retry connection setup
            </button>
          )}
        </div>
      )}
      {calendar.notice && (
        <p className="calendar-message" role="status">
          {calendar.notice}
        </p>
      )}
      {calendar.loading && (
        <p className="calendar-loading" role="status">
          Checking calendar connections…
        </p>
      )}

      <section
        className="calendar-section"
        aria-labelledby="accounts-heading"
        aria-busy={calendar.loading}
      >
        <div className="calendar-section-heading">
          <h2 id="accounts-heading">Calendar accounts</h2>
          <p>
            Read-only import. This app never creates, changes, or deletes your
            calendar events.
          </p>
        </div>
        <ul className="calendar-accounts">
          {(["google", "apple"] as const).map((provider) => {
            const connection = calendar.session?.connections.find(
              (item) => item.provider === provider,
            );
            return (
              <li key={provider}>
                <div>
                  <h3>{providerNames[provider]}</h3>
                  <p>{connection ? connection.account : "Not connected"}</p>
                </div>
                {connection ? (
                  <button
                    type="button"
                    className="calendar-secondary"
                    disabled={blocked}
                    onClick={() => void calendar.disconnect(provider)}
                  >
                    {calendar.busy === `disconnect-${provider}`
                      ? "Disconnecting…"
                      : `Disconnect ${provider === "google" ? "Google" : "iCloud"}`}
                  </button>
                ) : provider === "google" ? (
                  <button
                    type="button"
                    disabled={blocked || !calendar.session?.google_configured}
                    onClick={() => void calendar.signInGoogle()}
                  >
                    {calendar.busy === "google"
                      ? "Opening Google…"
                      : "Sign in with Google"}
                  </button>
                ) : (
                  <button
                    type="button"
                    className="calendar-secondary"
                    aria-expanded={appleOpen}
                    aria-controls="apple-connection"
                    disabled={blocked || !calendar.session}
                    onClick={() => setAppleOpen((value) => !value)}
                  >
                    {appleOpen ? "Close iCloud form" : "Connect iCloud"}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
        {calendar.session && !calendar.session.google_configured && (
          <p className="calendar-help">
            Google sign-in is not configured yet. The server needs a Google
            Calendar OAuth client ID and secret.
          </p>
        )}
        {appleOpen && !appleConnected && (
          <AppleConnectForm busy={blocked} onConnect={calendar.connectApple} />
        )}
      </section>

      <section className="calendar-section" aria-labelledby="parse-heading">
        <div className="calendar-section-heading">
          <h2 id="parse-heading">Parse your schedule</h2>
          <p>
            Dates are inclusive. Times are converted to the timezone you choose.
          </p>
        </div>
        <form onSubmit={parse}>
          <fieldset disabled={blocked || !calendar.session}>
            <fieldset className="calendar-source">
              <legend>Import from</legend>
              <label>
                <input
                  type="radio"
                  name="calendar-source"
                  value="account"
                  checked={!fromUrl}
                  disabled={!calendar.session?.connections.length}
                  onChange={() => {
                    setSource("account");
                    calendar.clearResult();
                  }}
                />
                Connected account
              </label>
              <label>
                <input
                  type="radio"
                  name="calendar-source"
                  value="url"
                  checked={fromUrl}
                  onChange={() => {
                    setSource("url");
                    calendar.clearResult();
                  }}
                />
                Paste a calendar URL
              </label>
            </fieldset>
            {fromUrl ? (
              <div className="calendar-url">
                <label htmlFor="calendar-url">
                  Google Calendar or ICS feed URL
                  <input
                    id="calendar-url"
                    type="url"
                    autoComplete="off"
                    spellCheck={false}
                    value={url}
                    placeholder="https://calendar.google.com/calendar/… or https://…/calendar.ics"
                    onChange={(event) => {
                      setUrl(event.target.value);
                      calendar.clearResult();
                    }}
                    required
                    aria-describedby="calendar-url-help"
                  />
                </label>
                <p id="calendar-url-help" className="calendar-help">
                  Google share/embed links, ICS feeds, and webcal links are
                  supported. Private Google calendars need the matching
                  connected account. Private ICS URLs work like passwords: the
                  link is used for this import only and is not saved.
                </p>
              </div>
            ) : (
              <>
                <label
                  className="calendar-provider"
                  htmlFor="calendar-provider"
                >
                  Connected account
                  <select
                    id="calendar-provider"
                    value={calendar.provider}
                    onChange={(event) =>
                      calendar.selectProvider(
                        event.target.value as CalendarProvider,
                      )
                    }
                  >
                    {calendar.session?.connections.map((item) => (
                      <option key={item.provider} value={item.provider}>
                        {providerNames[item.provider]} · {item.account}
                      </option>
                    ))}
                  </select>
                </label>
                <fieldset
                  className="calendar-picker"
                  disabled={calendar.calendarsLoading}
                >
                  <legend>Calendars to include</legend>
                  {calendar.calendarsLoading ? (
                    <p role="status">Loading your calendars…</p>
                  ) : calendar.calendars.length ? (
                    <div className="calendar-checkboxes">
                      {calendar.calendars.map((item) => (
                        <label key={item.id}>
                          <input
                            type="checkbox"
                            checked={calendar.selected.includes(item.id)}
                            disabled={
                              calendar.selected.length >= 20 &&
                              !calendar.selected.includes(item.id)
                            }
                            onChange={() => calendar.toggleCalendar(item.id)}
                          />
                          <span>
                            {item.name}
                            {item.primary ? " (primary)" : ""}
                          </span>
                        </label>
                      ))}
                    </div>
                  ) : (
                    <p>
                      No readable calendars were found. Check the account’s
                      calendar permissions, then reload the list.
                    </p>
                  )}
                  <button
                    type="button"
                    className="calendar-text-button"
                    onClick={calendar.retryCalendars}
                    disabled={calendar.calendarsLoading}
                  >
                    Reload calendar list
                  </button>
                </fieldset>
              </>
            )}
            <div className="calendar-form-grid calendar-date-grid">
              <label htmlFor="calendar-start">
                Start date
                <input
                  id="calendar-start"
                  type="date"
                  value={start}
                  onChange={(event) => {
                    setStart(event.target.value);
                    calendar.clearResult();
                  }}
                  required
                />
              </label>
              <label htmlFor="calendar-end">
                End date
                <input
                  id="calendar-end"
                  type="date"
                  value={end}
                  min={start}
                  onChange={(event) => {
                    setEnd(event.target.value);
                    calendar.clearResult();
                  }}
                  required
                />
              </label>
              <label htmlFor="calendar-timezone">
                Timezone
                <input
                  id="calendar-timezone"
                  value={timezone}
                  onChange={(event) => {
                    setTimezone(event.target.value);
                    calendar.clearResult();
                  }}
                  required
                  spellCheck={false}
                  aria-describedby="timezone-help"
                />
              </label>
            </div>
            <p id="timezone-help" className="calendar-help">
              Use an IANA timezone such as America/New_York or Europe/London.
              Select up to 20 calendars and at most 366 days.
            </p>
            <button
              type="submit"
              disabled={
                fromUrl
                  ? !url.trim()
                  : calendar.calendarsLoading || !calendar.selected.length
              }
            >
              {calendar.busy === "parse"
                ? "Importing and parsing…"
                : fromUrl
                  ? "Import calendar"
                  : "Parse selected calendars"}
            </button>
          </fieldset>
        </form>
      </section>

      {calendar.result && (
        <section className="calendar-section" aria-labelledby="results-heading">
          <div className="calendar-section-heading">
            <h2 id="results-heading">Parsed events</h2>
            <p role="status">
              {calendar.result.events.length}{" "}
              {calendar.result.events.length === 1 ? "event" : "events"} ·{" "}
              {calendar.result.start} to {calendar.result.end} ·{" "}
              {calendar.result.timezone}
            </p>
            {calendar.result.events.length > 0 && (
              <button
                type="button"
                className="button primary"
                onClick={() => {
                  if (giveHandoff(sessionStorage, calendar.result!)) {
                    window.location.assign("/schedule");
                  }
                }}
              >
                Find my hell weeks →
              </button>
            )}
          </div>
          {calendar.result.events.length === 0 ? (
            <p className="calendar-empty">
              No events overlap this date range. Choose a different calendar or
              widen the dates, then parse again.
            </p>
          ) : (
            <div
              className="calendar-table-region"
              tabIndex={0}
              role="region"
              aria-label="Parsed calendar events"
            >
              <table>
                <thead>
                  <tr>
                    <th scope="col">Event</th>
                    <th scope="col">Schedule</th>
                    <th scope="col">Calendar</th>
                    <th scope="col">Hours</th>
                  </tr>
                </thead>
                <tbody>
                  {calendar.result.events.map((event) => (
                    <tr key={event.id}>
                      <td>
                        <strong>{event.title}</strong>
                        {event.location && (
                          <span className="calendar-event-detail">
                            {event.location}
                          </span>
                        )}
                        {event.description && (
                          <details>
                            <summary>Description</summary>
                            <p>{event.description}</p>
                          </details>
                        )}
                      </td>
                      <td>{schedule(event, calendar.result!.timezone)}</td>
                      <td>{event.calendar_name}</td>
                      <td className="calendar-number">
                        {event.all_day
                          ? "All day"
                          : event.duration_hours.toLocaleString(undefined, {
                              maximumFractionDigits: 2,
                            })}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
      <footer className="calendar-footer">
        Connections belong to this browser session. Disconnecting removes this
        app’s saved credentials; you can also revoke access in your Google or
        Apple account settings.
      </footer>
    </main>
  );
}
