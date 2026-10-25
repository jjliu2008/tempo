# React + Python App

Monorepo with a React/TypeScript SPA and a FastAPI service. The two halves are
independent deployables that share only an HTTP contract.

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
  responses. Repositories own SQL. `models/` is the database shape, `schemas/`
  is the wire shape — do not return ORM objects from endpoints.
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

## Conventions

- Backend: 4-space indent, `ruff` for lint/format, `mypy --strict` on `app/`.
- Frontend: 2-space indent, `@/` resolves to `src/`.
- Never commit `.env` files; examples are checked in instead.
- API is versioned by URL prefix (`/api/v1`); breaking changes get `/api/v2`.
