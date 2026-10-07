# Controller API

Base URL `http://localhost:8080`. Interactive docs (Swagger UI): `/docs`, OpenAPI schema: `/openapi.json`. No authentication (local demo).

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness |
| GET | `/api/config` | LLM provider/model, remediation mode, safety policy values, service inventory |
| GET | `/api/overview` | Everything the dashboard shows in one call: services + 90-point series, call graph, anomalies, predictions, current incident, timeline, logs |
| GET | `/api/incidents` | Incident list (newest first) |
| GET | `/api/incidents/{id}` | Full incident: RCA ranking, analysis, plan, gate checks, approval, execution, before/after, history, events |
| POST | `/api/incidents/{id}/approval` | Human decision `{"approved": true, "by": "alice", "note": "..."}`. 404 if nothing is pending |
| POST | `/api/incidents/trigger` | Open an incident from currently active anomalies (409 if none or one is running) |
| POST | `/api/mode` | `{"mode": "auto"}` or `{"mode": "approve_all"}` |
| GET | `/api/anomalies?limit=50` | Recent anomalies |
| GET | `/api/logs?service=&level=&limit=` | Recent logs from the Redis buffer |
| GET | `/api/graph` | Dependency edges (observed, plus static topology with `calls: 0`) |
| GET | `/api/traces/{trace_id}` | Spans for one trace |
| POST | `/api/chaos` | Inject a fault `{"service": "payment-service", "type": "latency", "intensity": 1500, "duration_s": 0}` |
| POST | `/api/chaos/reset` | Clear faults on all services and start any stopped container |

## Fault types (`type`)

| type | intensity | effect |
|---|---|---|
| `cpu` | 0..1 duty cycle (default 0.9) | busy-loop thread, plus latency penalty divided by replicas |
| `latency` | milliseconds (default 1500) | delay on every request |
| `memory` | MB per second (default 3) | leaks until about 93% of `MEM_LIMIT_MB`, then errors and slowness |
| `errors` | probability 0..1 (default 0.5) | HTTP 500s with an error log |
| `crash` | n/a | process exits after 1 s (container stays down until restarted) |
| `bad_deploy` | n/a | desired version set to `v2` in Redis: 40% errors, +150 ms; only rollback clears it |

Each service also exposes `GET /health`, `GET /metrics` (Prometheus), `POST|DELETE /chaos`, `POST /admin/reload` and `GET /admin/state` on port 8000 inside the network.

## Kafka topics and Redis keys

* `telemetry.metrics`, `telemetry.logs`, `telemetry.traces` (services → processor), `aiops.anomalies` (processor → controller)
* Redis: `svc:{name}:latest`, `svc:{name}:series`, `anomalies:active`, `anomalies:recent`, `logs:recent`, `traces:recent`, `tpl:{svc}:ERROR`, `graph`, `predictions`, `deploy:{svc}`, `replicas:{svc}`

## Incident states

`analyzing → (awaiting_approval) → remediating → verifying → resolved`, or `escalated` when the gate denies, a human rejects or times out, the action fails, the playbook is exhausted, or `MAX_ITERATIONS` is reached. Every transition is an event in the timeline and the SQLite audit trail.
