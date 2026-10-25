# Tempo — Hell Week Detector

Tempo turns a Google Calendar into a daily or weekly workload heat map, calls
out when the user is officially cooked, and uses Gemma 4 to write ridiculous
event-specific excuses. It is a React/TypeScript SPA backed by FastAPI.

## Features

- Daily and weekly calendar-density heat maps
- Gen Z-style workload commentary
- Event-level excuse generation with professional, casual, dramatic, and
  unhinged tones
- Optional user direction such as “texting my professor”
- Server-side Gemma 4 integration through the Gemini API
- Calendar parsing and deterministic workload calculations

```
.
├── backend/                 FastAPI service (layered)
│   ├── app/
│   │   ├── main.py          App factory: middleware, routers
│   │   ├── core/            Config, logging, security primitives
│   │   ├── api/
│   │   │   ├── deps.py      Shared dependencies (db session, current user)
│   │   │   └── v1/
│   │   │       ├── router.py        Mounts every v1 router
│   │   │       └── endpoints/       One module per resource (health.py)
│   │   ├── models/          SQLAlchemy tables (persistence shape)
│   │   ├── schemas/         Pydantic models (API shape)
│   │   ├── services/        Business logic, transactions, orchestration
│   │   ├── repositories/    Data access queries
│   │   ├── db/              Base metadata, engine, session factory
│   │   └── workers/         Background jobs / task queue
│   ├── hellweek/            Calendar parsing + load math (pure, no FastAPI)
│   ├── alembic/             Migrations
│   ├── tests/               Mirrors app/ layout
│   ├── pyproject.toml
│   └── .env.example
├── frontend/                Vite + React + TypeScript SPA
│   ├── src/
│   │   ├── main.tsx         React entrypoint
│   │   ├── App.tsx          Root view
│   │   ├── routes/          Route table
│   │   ├── api/             HTTP client and endpoint modules
│   │   ├── features/        Feature slices (see below)
│   │   ├── components/      Shared UI: ui/ primitives, layout/ chrome
│   │   ├── hooks/           Cross-feature hooks
│   │   ├── lib/             Framework-agnostic helpers
│   │   ├── store/           Global client state
│   │   ├── styles/          Global CSS / tokens
│   │   ├── types/           Shared TypeScript types
│   │   └── assets/          Static files imported by code
│   ├── public/              Static files served as-is
│   ├── vite.config.ts
│   └── .env.example
├── docs/                    ADRs, API notes, diagrams
├── scripts/                 One-off and CI scripts
└── Makefile
```

## Request flow

```
React component → feature hook → src/api module → fetch(/api/v1/...)
      → nginx/dev proxy → FastAPI router → service → repository → database
```

Rules that keep the layers honest:

- **Backend.** Endpoints parse input and call a service; they never query the
  database directly. Services hold business rules and never build HTTP
  responses. Provider-specific services own upstream SDK calls; orchestration
  services compose them. Repositories own SQL. `models/` is the database shape,
  `schemas/` is the wire shape — do not return ORM objects from endpoints.
- **Frontend.** Components render. Data fetching lives in hooks inside the
  feature slice. Only `src/api/` talks to `fetch`. Shared building blocks move
  to `components/`; anything used by one feature stays in that feature.

## Adding a feature

Say the feature is `projects`:

1. Backend: `models/project.py`, `schemas/project.py`,
   `repositories/project.py`, `services/project.py`,
   `api/v1/endpoints/projects.py`; register the router in `api/v1/router.py`.
2. Frontend: `src/features/projects/{api.ts,hooks.ts,components/,ProjectPage.tsx}`;
   add the route in `src/routes/index.tsx`.

Keeping one request in this shape end-to-end means a new feature never has to
touch unrelated folders.

## Running locally

Requires Python 3.11+ and Node 20+.

```bash
make install          # creates backend/.venv and installs npm packages

cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local

make dev-backend      # http://localhost:8000  (docs at /docs)
make dev-frontend     # http://localhost:5173
```

Vite proxies `/api` to `localhost:8000`, so the browser stays on one origin in
development and `VITE_API_BASE_URL` can stay relative. In production, set it to
the real API origin and enable CORS for it in `backend/.env`
(`CORS_ORIGINS`).

Health check: `curl http://localhost:8000/api/v1/health`.

## Local code graph (graphify)

`graphify-out/` holds a knowledge graph of this repo. It is **local only**: the
directory is git-ignored, never committed, and never pushed.

`make watch-graph` keeps it in step with GitHub. Every 60 seconds the watcher
fetches `origin/main` and fast-forwards only when safe; it never rebases or
creates merges, and Git refuses an update that would overwrite local edits.
It runs `graphify update` — AST only, no LLM — when the local graph is stale
relative to the checked-out `HEAD`, including when Git is ahead of or diverged
from GitHub. Divergence still needs a merge or rebase to sync Git; the watcher
records that request while keeping the local graph current. It never commits
or pushes.

When it finds work only an agent can do — changed docs/media that need semantic
extraction, a rebuild failure, or divergence — it writes
`graphify-out/.graphify_watch/agent-task.md` with the reason, files, and a
suggested command, and logs `agent action requested`. An agent working in this
checkout reads that file, updates the graph locally, then deletes it. Logs and
state sit beside it in `graphify-out/.graphify_watch/`.

`make watch-graph-once` runs one check. Stop a background watcher with
`kill "$(cat graphify-out/.graphify_watch/watch.pid)"`. `INTERVAL`, `REMOTE`,
`BRANCH`, `REPO_DIR`, and `GRAPHIFY_BIN` are environment overrides.

## Gemma excuse generator

Select an event in the heat map to open **Need an out?**. Pick a professional,
casual, dramatic, or unhinged vibe, optionally add context such as “texting my
professor,” then generate and copy a playful excuse.

The feature uses the shared `gemma.generate()` frontend client and
`POST /api/v1/gemma/generate`; it does not create a second Google SDK client or
expose the key to the browser. The heat-map calculations remain deterministic
application code. Gemma writes only the human-facing excuse.

Copy the example environment file and add the shared key to `backend/.env`:

```bash
cp backend/.env.example backend/.env
```

Use `GOOGLE_API_KEY` or its supported alias, `GEMINI_API_KEY`. Event metadata
and optional user direction are supplied as application context. The feature
requests and validates JSON containing `subject`, `excuse`, and `disclaimer`.
Its system prompt rejects serious medical, legal, criminal, and emergency
fabrications and treats calendar text as untrusted data.

The frontend helper lives at
`frontend/src/features/heat-map/excuse-api.mjs`:

```js
const result = await generateExcuse(event, "unhinged");
```

### Integration contract

The calendar/UI side owns event selection and passes this shape to the helper:

```js
{
  title: "CS midterm",
  description: "Optional calendar description",
  startLabel: "Tuesday at 2:00pm"
}
```

The calendar/UI side owns event selection and event normalization. The excuse
feature owns prompting, output validation, loading/error states, and
display/copy behavior. The shared Gemma module owns provider transport,
credentials, timeouts, concurrency, and provider error mapping. No frontend
code should import or expose either API-key variable.

## Calendar engine (`backend/hellweek`)

A plain Python package that turns an `.ics` calendar into daily workload and
flagged hell weeks. It has no web or database dependencies; a service in
`app/services/` should call it rather than reimplement it. Run from `backend/`:

```bash
python -m hellweek.make_demo --out demo/demo_semester.ics   # fictional semester
python -m hellweek events CAL.ics --start 2026-08-25 --end 2026-12-15 --out events.json
python -m hellweek analyze CAL.ics --start 2026-08-25 --end 2026-12-15 \
    [--classifications classes.json] [--tz America/New_York] [--hell-hours 50] --out load.json
```

`CAL.ics` may also be an http(s) or `webcal://` URL (see below). `--tz` defaults to the
calendar's own timezone, then UTC; `--out` defaults to stdout. Warnings
(malformed or unmatched `classes.json` entries) go to stderr.

- `events.json`: list of `{id, title, start, end, all_day, duration_hours,
  location, description}`. The model returns `classes.json` keyed by `id`:
  `{"<id>": {"type": "exam|deadline|quiz|class|meeting|social|work|other",
  "prep_hours": 8.0, "stress": 7}}`. Events it omits use keyword rules.
- `load.json`: `meta` (range, timezone, threshold), `days` (every day, with a
  per-event `breakdown`), and `hell_weeks` ranked worst first. Each hell week
  has its merged span (`start`/`end`/`total_hours`), its heaviest 7-day window
  (`peak_start`/`peak_end`/`peak_hours`) and its stress >= 7 `key_events`.

Its tests live in `backend/tests/hellweek/` and run with `make test-backend`.

### Gemma (prep estimates and the forecast)

Gemma does only the two jobs that need judgment or writing. Our code does all
the parsing, prep spreading, load math and detection, so the numbers stay
consistent and explainable.

1. **Hidden prep:** for each unique event title, Gemma returns type,
   prep_hours and stress (e.g. "CSE 232 Midterm 2" → exam, 10h, stress 9).
2. **Weather report:** for each hell week, Gemma writes a headline, a funny
   forecast and specific advice. It sees only facts our code computed (dates,
   events, hours, prep start days). The result goes in
   `hell_weeks[i].report` as `{headline, forecast, advisories, source}`.

```bash
python -m hellweek analyze CAL.ics --start ... --end ... --gemma --out load.json
python -m hellweek classify CAL.ics --start ... --end ... --out classes.json
```

- Uses the same key as the [Shared Gemma API](#shared-gemma-api):
  `GOOGLE_API_KEY` or `GEMINI_API_KEY` in `backend/.env` (gitignored). The key
  travels in a request header and is never printed. That API is the generic
  transport; the prompts, validation and fallbacks for these two jobs live here.
- Gemma is opt-in (`--gemma`). Without it, or if the API fails after retries,
  you get the keyword rules and a template report (`"source": "template"`).
- Only titles are sent: no locations, descriptions or calendar URL. Titles are
  deduplicated, so a class that repeats 40 times is sent once.
- Replies are validated. A malformed entry falls back to keywords for that
  title only. Rate limits and "high demand" errors are retried with backoff,
  then `gemma-4-26b-a4b-it` falls back to `gemma-4-31b-it`. Set
  `HELLWEEK_GEMMA_MODEL` to force one model.
- Results are cached per title in `.gemma_cache.json` (gitignored), so re-runs
  skip the roughly 30 s classification call.
- Gemma is open-weight, so the model can be swapped, self-hosted later, or
  fine-tuned on real student workload data. **With the API, event titles do
  leave your machine (they go to Google)**, so don't claim otherwise.

### Importing from a calendar URL

Google: Settings → your calendar → Integrate calendar → **Secret address in
iCal format**. Apple: share the calendar publicly and use its `webcal://` link.
`webcal://` is fetched as `https://`, and plain `http://` is upgraded to
`https://` too. The fetch has a 30 s timeout and parses the result like a file.
It is a one-time import each time it runs, not a live sync.

**The secret address is a password.** Anyone who has it can read the whole
calendar. Never log it, print it, put it in a URL query string or commit it.

- CLI: don't type it on the command line, where it lands in shell history.
  Leave the calendar argument out and the CLI prompts for it with hidden input,
  or reads `HELLWEEK_CALENDAR_URL`. Errors about it never echo the URL.
- Backend/frontend: send it in a POST body, never as `?url=`. Uvicorn's access
  log records query strings. Don't log request bodies, and don't keep it in
  `localStorage` or the database. Fetch, analyze, then drop it.
- School Google accounts (MSU and others) sometimes have the secret address
  turned off by the admin. If it isn't shown, use a personal account, or export
  the calendar to `.ics` and pass the file.

## Shared Gemma API

The backend uses Google's official `google-genai` SDK and one async client per
application process. Set `GOOGLE_API_KEY` in `backend/.env` (or `GEMINI_API_KEY`),
then restart the backend. Get a key from [Google AI Studio](https://aistudio.google.com/apikey).
Never put the key in a `VITE_` variable or frontend code.

`GEMMA_MODEL` defaults to `gemma-4-26b-a4b-it`; `gemma-4-31b-it` is also supported.
Both support native system instructions through Google's Gemini API.
`backend/.env.example` lists output-token, timeout, temperature, and concurrency
settings. The app and health endpoint still start without a key; Gemma requests
then return `503`.

### Call from any frontend feature

```ts
import { gemma } from "@/api/gemma";

const first = await gemma.generate({
  system_prompt: "You are the app's planning assistant. Use the supplied data.",
  context: { project: { name: "Launch", tasks: ["Review", "Ship"] } },
  prompt: "What should we do first?",
});

const next = await gemma.generate({
  system_prompt: "You are the app's planning assistant. Use the supplied data.",
  history: first.history,
  prompt: "Break that step into smaller tasks.",
});
```

Both client methods accept an optional `AbortSignal` as their second argument.
They call `POST /api/v1/gemma/generate` and `POST /api/v1/gemma/agents`;
the complete request and response schemas are available at `/docs`.

### Call from backend modules

Inject the shared service into endpoints, then pass it to services/workers that
need inference; do not create a Google client for every call:

```python
from typing import Annotated

from fastapi import Depends

from app.api.deps import get_gemma_service
from app.schemas.gemma import GemmaRequest
from app.services.gemma import GemmaService

async def plan(gemma: Annotated[GemmaService, Depends(get_gemma_service)]):
    return await gemma.generate(
        GemmaRequest(
            system_prompt="You are a planning assistant.",
            context={"tasks": ["Review", "Ship"]},
            prompt="Which task comes first?",
        )
    )
```

A standalone worker can own a `GemmaService(settings)` instance and must call
`await service.aclose()` on shutdown. FastAPI manages that lifecycle automatically.

### Context and conversation ownership

- `context` accepts text, a JSON object, or a JSON array. Pass the relevant
  application state, records, documents, and permissions-filtered data explicitly.
  The module does not automatically read the database, filesystem, or other users'
  conversations.
- Every successful response includes `text`, `model`, `history`, `finish_reason`,
  and Google's token `usage`. Pass `history` into the next request to continue;
  it preserves each turn's context as well as user/model messages. System prompts
  apply per request and must be supplied again on follow-ups.
- All supplied history and context are sent without silent truncation or
  summarization. Google's input/context limits still apply. A `MAX_TOKENS`
  finish reason signals a potentially incomplete answer.
- Histories are caller-owned, not globally stored. Save them in the appropriate
  user/session state if persistence is needed, and clear them when switching users.
  Clients control supplied history/context; neither is an authorization boundary.

### Multiple agents

```ts
const run = await gemma.runAgents({
  system_prompt: "Use the supplied context. Be concise.",
  context: { project: "Launch", deadline: "Friday" },
  agents: [
    { id: "planner", system_prompt: "Create a plan.", prompt: "Plan the launch." },
    { id: "risk", system_prompt: "Identify risks.", prompt: "List launch risks." },
    {
      id: "reviewer",
      system_prompt: "Review the planner and risk outputs.",
      prompt: "Produce a final recommendation.",
      depends_on: ["planner", "risk"],
    },
  ],
});
```

Independent agents run concurrently, bounded by the shared
`GEMMA_MAX_CONCURRENT_REQUESTS` limit per process. Agents with `depends_on` wait
for those agents and receive their full output text under
`context.agent_results[id]`, alongside `shared_context` and their own
`agent_context`. Each agent can also supply its own history, temperature, and
output-token limit. Results preserve input order, not completion order.
Unrelated agents do not receive each other's private context/history. A graph
supports up to 16 agents; duplicate ids, missing dependencies, and cycles are
rejected before execution. If an agent fails, unfinished sibling tasks are
cancelled; Google may still charge for provider calls already in progress.

### Errors and deployment

Validation errors return `422`. Service errors have
`{"detail": {"code": "gemma_...", "message": "..."}}`:
missing configuration `503`, invalid/provider-rejected input `400`, quota `429`,
timeout `504`, blocked answer `422`, or upstream failure `502`. Provider error
bodies, credentials, and model thinking are not returned as answers.

This scaffold has **no authentication**. Protect these endpoints with your
application's authentication/authorization and quota policy before public
deployment; CORS alone does not prevent API use. Only send data to Google that
your application is authorized to disclose.

Provider reference: [Run Gemma with the Gemini API](https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api).

## Conventions

- Backend: 4-space indent, `ruff` for lint/format, `mypy --strict` on `app/`.
- Frontend: 2-space indent, `@/` resolves to `src/`.
- Never commit `.env` files; examples are checked in instead.
- API is versioned by URL prefix (`/api/v1`); breaking changes get `/api/v2`.

## License

This project is available under the [MIT License](LICENSE).
