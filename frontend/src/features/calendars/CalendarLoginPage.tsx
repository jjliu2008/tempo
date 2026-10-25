import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import AppleConnectForm from "./AppleConnectForm";
import { useCalendars } from "./useCalendars";
import "./calendars.css";

export default function CalendarLoginPage() {
  const calendar = useCalendars();
  const navigate = useNavigate();
  const [appleOpen, setAppleOpen] = useState(false);
  const connected = Boolean(calendar.session?.connections.length);
  const blocked = calendar.loading || calendar.busy !== null;

  useEffect(() => {
    if (!calendar.loading && connected)
      navigate("/calendars", { replace: true });
  }, [calendar.loading, connected, navigate]);

  return (
    <main className="calendar-page calendar-login-page">
      <title>Sign in · Tempo</title>
      <section
        className="calendar-login"
        aria-labelledby="calendar-login-heading"
      >
        <a className="calendar-login-brand" href="/" aria-label="Tempo home">
          tempo<span aria-hidden="true">*</span>
        </a>
        <h1 id="calendar-login-heading">Your week starts here.</h1>
        <p className="calendar-login-intro">
          Sign in with Google to bring your calendar into Tempo.
        </p>

        {calendar.error && (
          <div className="calendar-message calendar-error" role="alert">
            <p>{calendar.error}</p>
            {!calendar.session && (
              <button
                type="button"
                className="calendar-secondary"
                disabled={calendar.loading}
                onClick={() => void calendar.refresh()}
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
            Checking your session…
          </p>
        )}
        {connected && <p role="status">Opening your calendars…</p>}

        <div className="calendar-login-actions">
          <button
            type="button"
            disabled={blocked || !calendar.session?.google_configured}
            onClick={() => void calendar.signInGoogle()}
          >
            {calendar.busy === "google"
              ? "Opening Google…"
              : "Sign in with Google"}
          </button>
          {calendar.session && !calendar.session.google_configured && (
            <p className="calendar-help">
              Google sign-in needs a Google Calendar OAuth client configured on
              the server.
            </p>
          )}
          <button
            type="button"
            className="calendar-secondary"
            disabled={blocked || !calendar.session}
            aria-expanded={appleOpen}
            aria-controls="apple-connection"
            onClick={() => setAppleOpen((value) => !value)}
          >
            {appleOpen ? "Close Apple sign-in" : "Connect Apple Calendar"}
          </button>
        </div>
        {appleOpen && (
          <AppleConnectForm busy={blocked} onConnect={calendar.connectApple} />
        )}
        <a className="calendar-login-link" href="/calendars?source=url">
          Import a Google or ICS link instead
        </a>
        <p className="calendar-login-privacy">
          Read-only calendar import. Your events stay unchanged, and connection
          credentials are encrypted on the server.
        </p>
        <a className="calendar-login-demo" href="/schedule">
          Explore the sample schedule
        </a>
      </section>
    </main>
  );
}
