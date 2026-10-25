import { useState } from "react";
import type { FormEvent } from "react";

export default function AppleConnectForm({
  busy,
  onConnect,
}: {
  busy: boolean;
  onConnect: (email: string, password: string) => Promise<void>;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submittedPassword = password;
    setPassword("");
    void onConnect(email, submittedPassword);
  }

  return (
    <form id="apple-connection" className="apple-connection" onSubmit={submit}>
      <h3>Connect an iCloud calendar</h3>
      <p>
        Use your Apple Account email and an{" "}
        <a
          href="https://support.apple.com/en-us/102654"
          target="_blank"
          rel="noopener noreferrer"
        >
          app-specific password
        </a>
        . Your main Apple password is not accepted. Two-factor authentication
        must be enabled on your Apple Account.
      </p>
      <fieldset disabled={busy}>
        <div className="calendar-form-grid">
          <label htmlFor="apple-email">
            Apple Account email
            <input
              id="apple-email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              maxLength={320}
            />
          </label>
          <label htmlFor="apple-password">
            App-specific password
            <input
              id="apple-password"
              type="password"
              autoComplete="new-password"
              placeholder="xxxx-xxxx-xxxx-xxxx"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              aria-describedby="apple-password-help"
            />
          </label>
        </div>
        <p id="apple-password-help" className="calendar-help">
          The password is sent only to the backend and Apple, encrypted when
          stored, and cleared from this form on submit.
        </p>
        <button type="submit">
          {busy ? "Connecting iCloud…" : "Connect iCloud Calendar"}
        </button>
      </fieldset>
    </form>
  );
}
