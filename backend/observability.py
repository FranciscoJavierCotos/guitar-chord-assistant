"""
OpenTelemetry instrumentation for the ChordCoach backend (issue #6).

Why this exists
---------------
The backend is a public, multi-step LLM agent — without metrics/traces it is a
black box in production. This module wires up OpenTelemetry so a single chat
request produces an end-to-end trace (request → agent → per-tool spans → DeepSeek
call) plus RED + domain metrics (agent/tool latency, token usage & estimated
cost, time-to-first-token, rate-limit rejections), exported via OTLP to Grafana
Cloud (Tempo for traces, Mimir for metrics).

Opt-in / no-op by design
-------------------------
Instrumentation is **only** configured when ``OTEL_ENABLED`` is truthy *and* an
OTLP endpoint is set. The manual instrumentation sprinkled through the code
(``_tracer.start_as_current_span(...)``, the metric instruments below) always
goes through the OpenTelemetry *API*, which resolves to cheap no-ops until a real
SDK provider is installed by :func:`setup_observability`. So local ``uvicorn``,
CI, and the test suite run unchanged without any Grafana credentials.

Security invariants (see CLAUDE.md / issue #6 — do not regress these)
--------------------------------------------------------------------
- Never put ``DEEPSEEK_API_KEY`` / ``INTERNAL_API_TOKEN`` in span attributes,
  metric labels, or logs.
- Never export request/response bodies or auth headers.
- Keep label/attribute cardinality bounded — no per-session-id or per-IP labels.
  Tool names come from a fixed set; the only other labels are small enums
  (status ok/error, token kind input/output, streaming true/false).
"""

import logging
import os
import time
from contextlib import contextmanager

from opentelemetry import metrics, trace

logger = logging.getLogger("chordcoach.observability")

SERVICE_NAME_DEFAULT = "chordcoach-backend"

# DeepSeek deepseek-chat list price (USD per 1M tokens) used to *estimate* spend.
# These are estimates for a dashboard, not billing — override via env if pricing
# changes. As of 2026 deepseek-chat is ~$0.27 / 1M input, ~$1.10 / 1M output.
_DEFAULT_INPUT_COST_PER_MTOK = 0.27
_DEFAULT_OUTPUT_COST_PER_MTOK = 1.10


def _enabled() -> bool:
    """True when observability export is switched on. Requires an explicit
    opt-in flag *and* an OTLP endpoint, so a half-configured deploy stays a
    no-op rather than crashing on a missing exporter target."""
    flag = os.getenv("OTEL_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
    has_endpoint = bool(
        os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        or os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        or os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
    )
    return flag and has_endpoint


# ─── Metric instruments (API proxy — backed by the real provider once set) ──────
# Created at import time against the global proxy meter. If a MeterProvider is
# later installed by setup_observability(), the proxy forwards these to it; if
# not, they stay no-ops. Dotted names map to Prometheus as
# chordcoach_<...>_<unit> when Grafana Cloud ingests the OTLP metrics.
_meter = metrics.get_meter("chordcoach")

AGENT_DURATION = _meter.create_histogram(
    "chordcoach.agent.duration",
    unit="s",
    description="End-to-end agent run latency (one chat turn).",
)
TOOL_CALLS = _meter.create_counter(
    "chordcoach.tool.calls",
    description="Count of LangChain tool invocations, labelled by tool + status.",
)
TOOL_DURATION = _meter.create_histogram(
    "chordcoach.tool.duration",
    unit="s",
    description="Per-tool execution latency.",
)
LLM_TOKENS = _meter.create_counter(
    "chordcoach.llm.tokens",
    description="DeepSeek token usage, labelled by kind (input/output).",
)
LLM_COST = _meter.create_counter(
    "chordcoach.llm.cost_usd",
    unit="USD",
    description="Estimated DeepSeek spend (token usage × list price).",
)
STREAM_TTFT = _meter.create_histogram(
    "chordcoach.stream.ttft",
    unit="s",
    description="Streaming time-to-first-token for /api/chat/stream.",
)
RATELIMIT_REJECTIONS = _meter.create_counter(
    "chordcoach.ratelimit.rejections",
    description="slowapi 429 rejections (per-IP or global daily cap).",
)

# API-level tracer — no-op until a TracerProvider is installed.
_tracer = trace.get_tracer("chordcoach")


# ─── Public helpers used by the agent / routes ──────────────────────────────────
@contextmanager
def agent_run_span(streaming: bool):
    """Wrap one agent turn in a span and record its duration. The span is made
    the current context, so tool spans started by the callback handler nest
    underneath it, yielding request → agent → tool → LLM traces."""
    start = time.perf_counter()
    attrs = {"agent.streaming": streaming}
    with _tracer.start_as_current_span("agent.run", attributes=attrs):
        try:
            yield
        finally:
            AGENT_DURATION.record(time.perf_counter() - start, {"streaming": str(streaming).lower()})


def record_ttft(seconds: float) -> None:
    """Record streaming time-to-first-token (no-op when not exporting)."""
    STREAM_TTFT.record(seconds)


def record_rate_limit_rejection(scope: str = "request") -> None:
    """Increment the rate-limit rejection counter. `scope` is a tiny enum so
    cardinality stays bounded."""
    RATELIMIT_REJECTIONS.add(1, {"scope": scope})


def _input_cost_per_mtok() -> float:
    try:
        return float(os.getenv("DEEPSEEK_INPUT_COST_PER_MTOK", _DEFAULT_INPUT_COST_PER_MTOK))
    except ValueError:
        return _DEFAULT_INPUT_COST_PER_MTOK


def _output_cost_per_mtok() -> float:
    try:
        return float(os.getenv("DEEPSEEK_OUTPUT_COST_PER_MTOK", _DEFAULT_OUTPUT_COST_PER_MTOK))
    except ValueError:
        return _DEFAULT_OUTPUT_COST_PER_MTOK


def _record_tokens(input_tokens: int, output_tokens: int) -> None:
    """Record token counts and the matching estimated cost."""
    if input_tokens:
        LLM_TOKENS.add(input_tokens, {"kind": "input"})
    if output_tokens:
        LLM_TOKENS.add(output_tokens, {"kind": "output"})
    cost = (
        input_tokens / 1_000_000 * _input_cost_per_mtok()
        + output_tokens / 1_000_000 * _output_cost_per_mtok()
    )
    if cost:
        LLM_COST.add(cost)


# ─── LangChain callback: per-tool spans/metrics + token usage ───────────────────
from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402  (kept local to module)


class ObservabilityCallbackHandler(BaseCallbackHandler):
    """Turns LangChain's tool/LLM lifecycle into spans + metrics.

    One handler instance is created per agent run so its per-run bookkeeping
    dicts (keyed by LangChain ``run_id``) can't leak across requests. Every
    method is defensive: instrumentation must never break a chat turn, so any
    extraction failure is swallowed.
    """

    def __init__(self) -> None:
        self._tool_starts: dict = {}
        self._tool_spans: dict = {}

    # -- tools --
    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):  # type: ignore[override]
        name = "unknown"
        if isinstance(serialized, dict):
            name = serialized.get("name") or kwargs.get("name") or "unknown"
        else:
            name = kwargs.get("name") or "unknown"
        self._tool_starts[run_id] = (name, time.perf_counter())
        try:
            self._tool_spans[run_id] = _tracer.start_span(
                f"tool.{name}", attributes={"tool.name": name}
            )
        except Exception:  # pragma: no cover - defensive
            pass

    def on_tool_end(self, output, *, run_id, **kwargs):  # type: ignore[override]
        self._finish_tool(run_id, "ok")

    def on_tool_error(self, error, *, run_id, **kwargs):  # type: ignore[override]
        self._finish_tool(run_id, "error")

    def _finish_tool(self, run_id, status: str) -> None:
        name, started = self._tool_starts.pop(run_id, (None, None))
        span = self._tool_spans.pop(run_id, None)
        if name is None:
            return
        attrs = {"tool": name, "status": status}
        TOOL_CALLS.add(1, attrs)
        if started is not None:
            TOOL_DURATION.record(time.perf_counter() - started, {"tool": name})
        if span is not None:
            try:
                span.set_attribute("tool.status", status)
                span.end()
            except Exception:  # pragma: no cover - defensive
                pass

    # -- token usage / cost --
    def on_llm_end(self, response, *, run_id=None, **kwargs):  # type: ignore[override]
        try:
            in_tok, out_tok = self._extract_usage(response)
        except Exception:  # pragma: no cover - defensive
            return
        if in_tok or out_tok:
            _record_tokens(in_tok, out_tok)

    @staticmethod
    def _extract_usage(response) -> tuple[int, int]:
        """Pull (input, output) token counts from an LLMResult, handling both the
        streaming path (usage_metadata on the message, needs stream_usage=True)
        and the non-streaming path (token_usage in llm_output)."""
        # Streaming / chat models: usage_metadata on the AIMessage.
        try:
            gen = response.generations[0][0]
            message = getattr(gen, "message", None)
            usage = getattr(message, "usage_metadata", None) if message else None
            if usage:
                return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        except (IndexError, AttributeError, TypeError):
            pass
        # Non-streaming: aggregate token_usage in llm_output.
        llm_output = getattr(response, "llm_output", None) or {}
        token_usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
        return (
            int(token_usage.get("prompt_tokens", 0)),
            int(token_usage.get("completion_tokens", 0)),
        )


def get_agent_callback() -> ObservabilityCallbackHandler:
    """A fresh callback handler for one agent run."""
    return ObservabilityCallbackHandler()


# ─── SDK setup (called once at app startup) ─────────────────────────────────────
def setup_observability(app) -> bool:
    """Install the OTel SDK + OTLP exporters and auto-instrument FastAPI.

    No-op (returns False) unless OTEL_ENABLED is set with an OTLP endpoint, so
    callers can invoke this unconditionally. Returns True when export is live.
    """
    if not _enabled():
        logger.info(
            "Observability disabled (set OTEL_ENABLED=true + OTEL_EXPORTER_OTLP_ENDPOINT to export)."
        )
        return False

    try:
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError as exc:  # pragma: no cover - exercised only without the deps
        logger.warning("Observability requested but OTel packages are missing: %s", exc)
        return False

    service_name = os.getenv("OTEL_SERVICE_NAME", SERVICE_NAME_DEFAULT)
    resource = Resource.create({SERVICE_NAME: service_name})

    # Endpoint + auth headers are read from the standard OTEL_EXPORTER_OTLP_*
    # env vars by the exporters themselves — we never log or echo them.
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter())
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # Auto-instrument FastAPI: server spans + RED HTTP metrics per route.
    # /api/health is excluded so Render's frequent health probe doesn't swamp
    # the traces/metrics with noise.
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        excluded_urls="/api/health",
    )

    logger.info("Observability enabled → exporting OTLP traces+metrics as service '%s'", service_name)
    return True
