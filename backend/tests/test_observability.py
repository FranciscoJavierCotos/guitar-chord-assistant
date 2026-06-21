"""Tests for the OpenTelemetry instrumentation (observability.py, issue #6).

The instrumentation must be **opt-in and a no-op when unconfigured** — local dev,
CI, and the rest of this suite run without any Grafana credentials — and it must
never break a chat turn or leak token usage incorrectly. These tests pin:

- the enable/disable gating (flag + endpoint required);
- setup_observability staying a no-op when off;
- the callback's token extraction across the streaming and non-streaming shapes;
- tool-call + token + cost metrics actually being recorded (via an in-memory
  reader), with bounded labels.

No network or DeepSeek calls are involved.
"""

import pytest

import observability as obs


# ─── Enable/disable gating ──────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "flag, endpoint, expected",
    [
        (None, None, False),                       # nothing set → off (default)
        ("true", None, False),                     # flag without endpoint → off
        (None, "https://otlp.example", False),     # endpoint without flag → off
        ("true", "https://otlp.example", True),    # both → on
        ("1", "https://otlp.example", True),       # truthy synonyms
        ("yes", "https://otlp.example", True),
        ("false", "https://otlp.example", False),  # explicit off wins
        ("nonsense", "https://otlp.example", False),
    ],
)
def test_enabled_requires_flag_and_endpoint(monkeypatch, flag, endpoint, expected):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", raising=False)
    if flag is not None:
        monkeypatch.setenv("OTEL_ENABLED", flag)
    if endpoint is not None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint)

    assert obs._enabled() is expected


def test_setup_observability_is_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    # Passing a sentinel as the app proves setup never touches it when disabled.
    sentinel = object()
    assert obs.setup_observability(sentinel) is False


def test_record_helpers_never_raise_when_disabled():
    # These run on every request/stream; they must be safe no-ops without a provider.
    obs.record_ttft(0.42)
    obs.record_rate_limit_rejection()
    obs.record_rate_limit_rejection("global")


# ─── Token-usage extraction (the part most likely to silently mis-read) ─────────
class _Msg:
    def __init__(self, usage_metadata):
        self.usage_metadata = usage_metadata


class _Gen:
    def __init__(self, message):
        self.message = message


class _Resp:
    def __init__(self, generations=None, llm_output=None):
        self.generations = generations or []
        self.llm_output = llm_output


def test_extract_usage_streaming_usage_metadata():
    # The streaming path carries counts on the message (needs stream_usage=True).
    resp = _Resp(generations=[[_Gen(_Msg({"input_tokens": 120, "output_tokens": 45}))]])
    assert obs.ObservabilityCallbackHandler._extract_usage(resp) == (120, 45)


def test_extract_usage_non_streaming_llm_output():
    # The non-streaming path aggregates token_usage in llm_output.
    resp = _Resp(
        generations=[[_Gen(_Msg(None))]],
        llm_output={"token_usage": {"prompt_tokens": 80, "completion_tokens": 30}},
    )
    assert obs.ObservabilityCallbackHandler._extract_usage(resp) == (80, 30)


def test_extract_usage_returns_zeros_when_absent():
    assert obs.ObservabilityCallbackHandler._extract_usage(_Resp()) == (0, 0)


# ─── Metric recording via an in-memory reader ──────────────────────────────────
# Installing a real (in-memory) MeterProvider makes the module-level instruments
# — created against the API proxy at import time — forward to it, so we can assert
# the instrumentation actually records. The provider can only be set once per
# process, so this fixture is session-scoped and tests measure deltas.
@pytest.fixture(scope="session")
def reader():
    from opentelemetry import metrics
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader

    in_mem = InMemoryMetricReader()
    metrics.set_meter_provider(MeterProvider(metric_readers=[in_mem]))
    return in_mem


def _point_total(reader, instrument_name, attr_filter=None):
    """Sum the matching data points for a counter/histogram by name + attributes."""
    data = reader.get_metrics_data()
    if data is None:
        return 0.0
    total = 0.0
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                if metric.name != instrument_name:
                    continue
                for dp in metric.data.data_points:
                    attrs = dict(dp.attributes or {})
                    if attr_filter and any(attrs.get(k) != v for k, v in attr_filter.items()):
                        continue
                    # counters expose .value; histograms expose .count.
                    total += getattr(dp, "value", None) or getattr(dp, "count", 0)
    return total


def test_record_tokens_and_cost(reader, monkeypatch):
    # Pin pricing so the estimated cost is deterministic: $1/1M in, $2/1M out.
    monkeypatch.setenv("DEEPSEEK_INPUT_COST_PER_MTOK", "1.0")
    monkeypatch.setenv("DEEPSEEK_OUTPUT_COST_PER_MTOK", "2.0")

    before_in = _point_total(reader, "chordcoach.llm.tokens", {"kind": "input"})
    before_out = _point_total(reader, "chordcoach.llm.tokens", {"kind": "output"})
    before_cost = _point_total(reader, "chordcoach.llm.cost_usd")

    obs._record_tokens(1_000_000, 500_000)

    assert _point_total(reader, "chordcoach.llm.tokens", {"kind": "input"}) - before_in == 1_000_000
    assert _point_total(reader, "chordcoach.llm.tokens", {"kind": "output"}) - before_out == 500_000
    # 1M * $1/1M + 0.5M * $2/1M = 1.0 + 1.0 = 2.0
    assert _point_total(reader, "chordcoach.llm.cost_usd") - before_cost == pytest.approx(2.0)


def test_tool_lifecycle_records_calls_and_latency(reader):
    handler = obs.get_agent_callback()
    before_ok = _point_total(reader, "chordcoach.tool.calls", {"tool": "get_chord_info", "status": "ok"})
    before_dur = _point_total(reader, "chordcoach.tool.duration", {"tool": "get_chord_info"})

    handler.on_tool_start({"name": "get_chord_info"}, "Am", run_id="r1")
    handler.on_tool_end("result", run_id="r1")

    assert _point_total(reader, "chordcoach.tool.calls", {"tool": "get_chord_info", "status": "ok"}) - before_ok == 1
    # Latency histogram saw exactly one observation for this tool.
    assert _point_total(reader, "chordcoach.tool.duration", {"tool": "get_chord_info"}) - before_dur == 1


def test_tool_error_records_error_status(reader):
    handler = obs.get_agent_callback()
    before = _point_total(reader, "chordcoach.tool.calls", {"tool": "find_song_chords", "status": "error"})

    handler.on_tool_start({"name": "find_song_chords"}, "x", run_id="e1")
    handler.on_tool_error(RuntimeError("boom"), run_id="e1")

    assert _point_total(reader, "chordcoach.tool.calls", {"tool": "find_song_chords", "status": "error"}) - before == 1


def test_unknown_tool_falls_back_to_bounded_label(reader):
    # Cardinality stays bounded: a serialized payload with no name → "unknown".
    handler = obs.get_agent_callback()
    before = _point_total(reader, "chordcoach.tool.calls", {"tool": "unknown", "status": "ok"})

    handler.on_tool_start(None, "x", run_id="u1")
    handler.on_tool_end("r", run_id="u1")

    assert _point_total(reader, "chordcoach.tool.calls", {"tool": "unknown", "status": "ok"}) - before == 1


def test_rate_limit_and_ttft_metrics_record(reader):
    before_rl = _point_total(reader, "chordcoach.ratelimit.rejections", {"scope": "request"})
    before_ttft = _point_total(reader, "chordcoach.stream.ttft")

    obs.record_rate_limit_rejection()
    obs.record_ttft(1.5)

    assert _point_total(reader, "chordcoach.ratelimit.rejections", {"scope": "request"}) - before_rl == 1
    assert _point_total(reader, "chordcoach.stream.ttft") - before_ttft == 1
