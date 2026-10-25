`GemmaService` owns the app-scoped Google client and single-request generation.
`AgentOrchestrator` runs request-local dependency graphs and delegates each
agent completion to `GemmaService`; HTTP request/response handling stays in `api/`.
