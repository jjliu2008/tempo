# Graph Report - Hacktober  (2026-10-25)

## Corpus Check
- 19 files · ~9,872 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 469 nodes · 929 edges · 38 communities (12 shown, 10 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 80 edges (avg confidence: 0.93)
- Token cost: not measured (assistant-agent token usage is unavailable; stored 0 counters are placeholders).

## Community Hubs (Navigation)
- Gemma Generation and Scheduling
- Calendar Load and Classification
- Documented App Architecture
- Gemma Layering and Ownership
- Hellweek CLI and ICS Parsing
- Security and Load Detection
- Frontend Package Configuration
- Demo Semester Calendar Generation
- FastAPI Application Wiring
- TypeScript Compiler Settings
- Frontend API Contracts
- SQLAlchemy Base Metadata
- Logging Configuration
- Vite Environment Types
- Backend Test Fixtures
- Models Package Documentation
- Schemas Package Documentation
- Gemma Request Type
- Gemma Response Type
- Workers Package Documentation
- Frontend App Shell
- Backend Package Configuration

## God Nodes (most connected - your core abstractions)
1. `Event` - 44 edges
2. `Classification` - 26 edges
3. `compilerOptions` - 19 edges
4. `compute_daily_load()` - 19 edges
5. `GemmaService` - 18 edges
6. `GemmaRequest` - 17 edges
7. `detect_hell_weeks()` - 17 edges
8. `AgentOrchestrator` - 15 edges
9. `classify_events()` - 14 edges
10. `DayLoad` - 14 edges

## Surprising Connections (you probably didn't know these)
- `Multi-agent dependency graph` --semantically_similar_to--> `Request-local dependency graph`  [INFERRED] [semantically similar]
  README.md → backend/app/services/README.md
- `One async Google client per application process` --semantically_similar_to--> `App-scoped Google client`  [INFERRED] [semantically similar]
  README.md → backend/app/services/README.md
- `backend/app/repositories package (placeholder)` --conceptually_related_to--> `Repositories layer (repositories/)`  [INFERRED]
  backend/app/repositories/README.md → README.md
- `Services package (backend/app/services)` --conceptually_related_to--> `Services layer (services/)`  [INFERRED]
  backend/app/services/README.md → README.md
- `Orchestration services compose provider services` --conceptually_related_to--> `AgentOrchestrator`  [INFERRED]
  README.md → backend/app/services/README.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Backend request layer chain** — readme_request_flow, readme_endpoints_layer, readme_services_layer, readme_repositories_layer [EXTRACTED 1.00]
- **Frontend data path** — readme_components_layer, readme_feature_hooks, readme_src_api_module, readme_vite_dev_proxy [EXTRACTED 1.00]
- **Gemma request ownership path** — readme_gemmaservice, backend_app_services_readme_gemmaservice, backend_app_services_readme_agentorchestrator, backend_app_services_readme_app_scoped_google_client, backend_app_services_readme_request_local_dependency_graph [INFERRED 0.85]
- **End-to-end request flow** — readme_frontend_components, readme_frontend_features, readme_frontend_api_layer, readme_vite_proxy, readme_api_v1_router_py, readme_services_layer, readme_repositories_layer, readme_db_layer [EXTRACTED 1.00]
- **Shared Gemma API surface** — readme_gemma_service, readme_gemma_service_generate, readme_gemma_client_generate, readme_gemma_run_agents, readme_gemma_http_generate, readme_gemma_http_agents, readme_multi_agent_dependency_graph [INFERRED 0.85]
- **Backend layered architecture** — readme_api_v1_endpoints, readme_schemas_pydantic, readme_services_layer, readme_repositories_layer, readme_models_sqlalchemy [EXTRACTED 1.00]

## Communities (38 total, 10 thin omitted)

### Community 0 - "Gemma Generation and Scheduling"
Cohesion: 0.06
Nodes (57): AgentOrchestratorDependency, AsyncSession, get_agent_orchestrator(), get_db(), get_gemma_service(), Shared FastAPI dependencies. Import these with `Depends(...)` in endpoints., generate(), App-facing Gemma calls; credentials and Google SDK remain server-side. (+49 more)

### Community 1 - "Calendar Load and Classification"
Cohesion: 0.08
Nodes (50): Classification, classify_events(), keyword_classify(), parse_classifications(), parse_entry(), Any, Path, Event classifications: the model's classes.json, with a keyword fallback. (+42 more)

### Community 2 - "Documented App Architecture"
Cohesion: 0.08
Nodes (44): backend/app/repositories package (placeholder), Adding a feature, Adding a feature procedure, Shared dependencies (api/deps.py), API versioning by URL prefix (/api/v1), v1 endpoints (api/v1/endpoints/), v1 router (api/v1/router.py), URL-prefix API versioning (+36 more)

### Community 3 - "Gemma Layering and Ownership"
Cohesion: 0.07
Nodes (41): AgentOrchestrator, App-scoped Google client, App-scoped versus request-local ownership, GemmaService, HTTP request/response handling stays in api/, Per-agent completion delegation to GemmaService, Request-local dependency graph, Services package (backend/app/services) (+33 more)

### Community 4 - "Hellweek CLI and ICS Parsing"
Cohesion: 0.11
Nodes (36): ArgumentParser, build_parser(), iso_date(), load_classifications(), load_events(), main(), Any, date (+28 more)

### Community 5 - "Security and Load Detection"
Cohesion: 0.11
Nodes (30): Security primitives: password hashing, token creation and verification.…, build_hell_week(), detect_hell_weeks(), Detection, HellWeek, high_stress_by_day(), is_flagged(), KeyEvent (+22 more)

### Community 6 - "Frontend Package Configuration"
Cohesion: 0.06
Nodes (33): dependencies, react, react-dom, react-router-dom, devDependencies, @types/node, @types/react, @types/react-dom (+25 more)

### Community 7 - "Demo Semester Calendar Generation"
Cohesion: 0.15
Nodes (31): all_day(), at(), base_event(), build_calendar(), first_matching_day(), main(), milestones(), Calendar (+23 more)

### Community 8 - "FastAPI Application Wiring"
Cohesion: 0.13
Nodes (19): health(), Liveness endpoint used by local dev, load balancers and container probes., Aggregate every v1 endpoint router in one place., get_settings(), Typed application settings, read from environment / .env., Settings, Engine and session factory. Request-scoped sessions come from api/deps.py., create_app() (+11 more)

### Community 9 - "TypeScript Compiler Settings"
Cohesion: 0.10
Nodes (20): compilerOptions, allowImportingTsExtensions, baseUrl, isolatedModules, jsx, lib, module, moduleResolution (+12 more)

### Community 10 - "Frontend API Contracts"
Cohesion: 0.14
Nodes (13): api, ApiError, HealthResponse, request(), gemma, GemmaAgentRequest, GemmaContext, GemmaMessage (+5 more)

### Community 11 - "SQLAlchemy Base Metadata"
Cohesion: 0.50
Nodes (3): Base, Base metadata for SQLAlchemy models. Alembic autogenerate imports this., DeclarativeBase

## Knowledge Gaps
- **71 isolated node(s):** `ImportMeta`, `ImportMetaEnv`, `HealthResponse`, `GemmaAgentRequest`, `GemmaContext` (+66 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 176 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Event` connect `Demo Semester Calendar Generation` to `Calendar Load and Classification`, `Hellweek CLI and ICS Parsing`, `Security and Load Detection`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Why does `Services layer (services/)` connect `Documented App Architecture` to `Gemma Layering and Ownership`?**
  _High betweenness centrality (0.018) - this node is a cross-community bridge._
- **Are the 20 inferred relationships involving `Event` (e.g. with `classify_events()` and `load_classifications()`) actually correct?**
  _`Event` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `Classification` (e.g. with `load_classifications()` and `build_hell_week()`) actually correct?**
  _`Classification` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `compute_daily_load()` (e.g. with `Classification` and `Event`) actually correct?**
  _`compute_daily_load()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `GemmaService` (e.g. with `get_agent_orchestrator()` and `get_gemma_service()`) actually correct?**
  _`GemmaService` has 5 INFERRED edges - model-reasoned connections that need verification._
- **What connects `ImportMeta`, `ImportMetaEnv`, `HealthResponse` to the rest of the system?**
  _71 weakly-connected nodes found - possible documentation gaps or missing edges._