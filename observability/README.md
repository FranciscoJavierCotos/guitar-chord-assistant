# ChordCoach Observability

OpenTelemetry instrumentation for the FastAPI backend, exporting **traces and
metrics** to the **Grafana Cloud free tier** (Tempo for traces, Mimir for
metrics) over a single OTLP/HTTP endpoint. Implemented in
[`backend/observability.py`](../backend/observability.py).

It is **opt-in and a no-op when unconfigured** — local dev, CI, and the test
suite run unchanged without any Grafana credentials. Export only turns on when
`OTEL_ENABLED=true` *and* an OTLP endpoint is set.

## What's instrumented

- **Traces** — FastAPI auto-instrumentation (a server span per request, excluding
  `/api/health`) plus a manual `agent.run` span with one child `tool.<name>` span
  per LangChain tool call. A single chat request becomes one end-to-end trace:
  request → agent → per-tool spans → DeepSeek LLM call.
- **Metrics** — RED HTTP metrics per route (from auto-instrumentation) plus domain
  metrics:

  | OTLP instrument                  | Prometheus name (in Grafana)             | Labels            |
  | -------------------------------- | ---------------------------------------- | ----------------- |
  | `chordcoach.agent.duration`      | `chordcoach_agent_duration_seconds`      | `streaming`       |
  | `chordcoach.tool.calls`          | `chordcoach_tool_calls_total`            | `tool`, `status`  |
  | `chordcoach.tool.duration`       | `chordcoach_tool_duration_seconds`       | `tool`            |
  | `chordcoach.llm.tokens`          | `chordcoach_llm_tokens_total`            | `kind` (in/out)   |
  | `chordcoach.llm.cost_usd`        | `chordcoach_llm_cost_usd_total`          | —                 |
  | `chordcoach.stream.ttft`         | `chordcoach_stream_ttft_seconds`         | —                 |
  | `chordcoach.ratelimit.rejections`| `chordcoach_ratelimit_rejections_total`  | `scope`           |

  Labels are deliberately low-cardinality — no session ids, IPs, or free text.

## Configuration

Set these backend env vars (see [`backend/.env.example`](../backend/.env.example)).
All are backend-only secrets — never exposed to the browser.

| Variable                       | Purpose                                                                 |
| ------------------------------ | ----------------------------------------------------------------------- |
| `OTEL_ENABLED`                 | `true` to turn export on. Unset/false → fully no-op.                    |
| `OTEL_EXPORTER_OTLP_ENDPOINT`  | Grafana Cloud OTLP gateway base URL (`.../otlp`).                       |
| `OTEL_EXPORTER_OTLP_HEADERS`   | `Authorization=Basic <base64(instanceID:token)>`.                      |
| `OTEL_SERVICE_NAME`            | Service name in traces/metrics (default `chordcoach-backend`).          |
| `DEEPSEEK_INPUT_COST_PER_MTOK` | Optional. $/1M input tokens for the cost estimate (default `0.27`).     |
| `DEEPSEEK_OUTPUT_COST_PER_MTOK`| Optional. $/1M output tokens for the cost estimate (default `1.10`).    |

To get the endpoint + headers: in Grafana Cloud, open **Connections →
OpenTelemetry (OTLP)**, which shows the gateway URL and generates the Basic-auth
token. Paste them into the two `OTEL_EXPORTER_OTLP_*` vars.

## Importing the dashboard

`dashboard.json` is a reproducible Grafana dashboard (traffic, errors, latency
percentiles, tokens/cost, tool usage, rate-limit headroom). In Grafana:
**Dashboards → New → Import → Upload JSON**, then pick your Prometheus/Mimir
datasource when prompted.

The HTTP error-rate panel uses FastAPI auto-instrumentation metric names
(`http_server_request_duration_seconds`, label `http_route`); these vary slightly
across `opentelemetry-instrumentation` versions, so adjust that one panel's query
if your series are named differently. The custom `chordcoach_*` panels are stable.

## Runbook — finding a slow request

1. **Spot it on the dashboard.** A spike in **Agent latency p95/p99** or
   **Streaming time-to-first-token** says turns are slow; **Tool latency p95 by
   tool** usually points at the culprit (`find_song_chords` does live web search
   and is the common hotspot).
2. **Jump to the trace.** In Grafana **Explore**, pick the **Tempo** datasource
   and search by service `chordcoach-backend`, sorted by duration (or filter
   `name = agent.run`). Open a slow trace.
3. **Read the waterfall.** The `agent.run` span holds the child `tool.<name>`
   spans and the DeepSeek LLM span. The widest child bar is where the time went —
   e.g. a long `tool.find_song_chords` means the web search dominated; a long LLM
   span means generation did.
4. **Confirm cost/usage** on the **Tokens & Cost** panels if a turn looks
   unusually expensive.

## Runbook — approaching the daily request cap

The **Rate-limit rejections** panel breaks 429s out by `scope`. A rising
`scope="request"` line is per-IP bursts; sustained rejections mean real traffic
is hitting the global `500/day` cap (see `backend/main.py`). Investigate the
source IPs in the logs before raising the cap, since the cap protects the DeepSeek
bill.
