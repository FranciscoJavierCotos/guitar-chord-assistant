"""Regression tests for the NDJSON event-frame streaming in run_agent_stream.

Before this change, /api/chat/stream yielded only the agent's final-answer text,
so the chat bubble sat blank for the whole ~20s planning/tool window. The stream
now yields NDJSON event frames: an immediate "Thinking…" status, a per-tool status
on each on_tool_start, and token frames for the answer. These tests pin that
contract without any DeepSeek/network calls by stubbing the AgentExecutor.
"""

import asyncio
import json

from langchain_core.chat_history import InMemoryChatMessageHistory

import agent.coach_agent as coach_agent


class _FakeChunk:
    """Mimics a LangChain chat-model stream chunk (only .content is read)."""

    def __init__(self, content):
        self.content = content


class _FakeExecutor:
    """Stand-in AgentExecutor whose astream_events replays a scripted event list."""

    def __init__(self, events):
        self._events = events

    async def astream_events(self, _inputs, version="v2", **_kwargs):
        # **_kwargs swallows the observability `config={"callbacks": [...]}` that
        # run_agent_stream now passes through to the real executor.
        for event in self._events:
            yield event


def _drain(message, history, events, monkeypatch):
    """Run run_agent_stream against a fake executor and return the parsed frames."""
    monkeypatch.setattr(coach_agent, "build_agent_executor", lambda: _FakeExecutor(events))

    async def run():
        raw = []
        async for line in coach_agent.run_agent_stream(message=message, history=history):
            raw.append(line)
        return raw

    raw_lines = asyncio.run(run())
    # Every yielded item must be a single NDJSON line (JSON object + trailing newline).
    for line in raw_lines:
        assert line.endswith("\n"), f"frame not newline-terminated: {line!r}"
    return [json.loads(line) for line in raw_lines]


def test_emits_thinking_then_tool_status_then_tokens(monkeypatch):
    events = [
        # A planning chat-model chunk with no content (only a tool call) — must be skipped.
        {"event": "on_chat_model_stream", "data": {"chunk": _FakeChunk("")}},
        {"event": "on_tool_start", "name": "find_song_chords", "data": {}},
        {"event": "on_chat_model_stream", "data": {"chunk": _FakeChunk("Here are ")}},
        {"event": "on_chat_model_stream", "data": {"chunk": _FakeChunk("the chords.")}},
    ]
    history = InMemoryChatMessageHistory()

    frames = _drain("play wonderwall", history, events, monkeypatch)

    # 1. The very first frame is an immediate "Thinking…" status (fills the blank gap).
    assert frames[0] == {"type": "status", "label": "Thinking…"}

    # 2. The tool start surfaces a friendly per-tool status, before any token.
    status_labels = [f["label"] for f in frames if f["type"] == "status"]
    assert coach_agent.TOOL_STATUS_LABELS["find_song_chords"] in status_labels
    first_token_idx = next(i for i, f in enumerate(frames) if f["type"] == "token")
    tool_status_idx = next(
        i for i, f in enumerate(frames)
        if f["type"] == "status" and f["label"] == coach_agent.TOOL_STATUS_LABELS["find_song_chords"]
    )
    assert tool_status_idx < first_token_idx

    # 3. Token frames carry the answer deltas and reassemble to the full text.
    tokens = [f["text"] for f in frames if f["type"] == "token"]
    assert tokens == ["Here are ", "the chords."]
    assert "".join(tokens) == "Here are the chords."


def test_persists_full_answer_to_history(monkeypatch):
    events = [
        {"event": "on_chat_model_stream", "data": {"chunk": _FakeChunk("Em ")}},
        {"event": "on_chat_model_stream", "data": {"chunk": _FakeChunk("C G")}},
    ]
    history = InMemoryChatMessageHistory()

    _drain("blues in E", history, events, monkeypatch)

    # The turn is appended once the stream completes: one human + one AI message.
    assert len(history.messages) == 2
    assert history.messages[0].content == "blues in E"
    assert history.messages[1].content == "Em C G"


def _apply_frames(frames):
    """Reassemble the text a client would display after honouring reset frames."""
    text = ""
    for f in frames:
        if f["type"] == "reset":
            text = ""
        elif f["type"] == "token":
            text += f["text"]
    return text


def test_discards_intermediate_planning_content(monkeypatch):
    # Regression for the second-turn "Let me look up the actual chords…" wall of
    # repeated lines (#13). A tool-calling agent runs several model calls, and
    # DeepSeek emits a conversational preamble *in the same run as the tool call*.
    # Only the final answer run must survive — both on the wire and in history.
    events = [
        # Planning run A: preamble streamed alongside a tool call.
        {"event": "on_chat_model_stream", "run_id": "run-A",
         "data": {"chunk": _FakeChunk("Let me look up the actual chords ")}},
        {"event": "on_chat_model_stream", "run_id": "run-A",
         "data": {"chunk": _FakeChunk("for this song!")}},
        {"event": "on_tool_start", "name": "find_song_chords", "data": {}},
        # Planning run B: another preamble before a second tool call.
        {"event": "on_chat_model_stream", "run_id": "run-B",
         "data": {"chunk": _FakeChunk("Let me search for the real chords.")}},
        {"event": "on_tool_start", "name": "find_song_chords", "data": {}},
        # Final answer run C: the only content the user should keep.
        {"event": "on_chat_model_stream", "run_id": "run-C",
         "data": {"chunk": _FakeChunk("Here are ")}},
        {"event": "on_chat_model_stream", "run_id": "run-C",
         "data": {"chunk": _FakeChunk("the real chords.")}},
    ]
    history = InMemoryChatMessageHistory()

    frames = _drain("play wonderwall", history, events, monkeypatch)

    # A reset frame precedes each new content run so the client drops the preamble.
    assert sum(1 for f in frames if f["type"] == "reset") == 2

    # What the client ultimately renders is only the final-answer run.
    assert _apply_frames(frames) == "Here are the real chords."
    assert "Let me look up" not in _apply_frames(frames)

    # And only the final answer is persisted — so the next turn isn't poisoned.
    assert len(history.messages) == 2
    assert history.messages[1].content == "Here are the real chords."


def test_no_reset_when_only_final_run_emits_content(monkeypatch):
    # The common case (planning runs emit tool calls with no content) must not
    # emit a spurious reset — the first content run is the answer.
    events = [
        {"event": "on_chat_model_stream", "run_id": "run-A", "data": {"chunk": _FakeChunk("")}},
        {"event": "on_tool_start", "name": "find_song_chords", "data": {}},
        {"event": "on_chat_model_stream", "run_id": "run-B", "data": {"chunk": _FakeChunk("All ")}},
        {"event": "on_chat_model_stream", "run_id": "run-B", "data": {"chunk": _FakeChunk("good.")}},
    ]
    history = InMemoryChatMessageHistory()

    frames = _drain("hi", history, events, monkeypatch)

    assert not any(f["type"] == "reset" for f in frames)
    assert _apply_frames(frames) == "All good."
    assert history.messages[1].content == "All good."


def test_unknown_tool_uses_default_label(monkeypatch):
    events = [
        {"event": "on_tool_start", "name": "some_future_tool", "data": {}},
        {"event": "on_chat_model_stream", "data": {"chunk": _FakeChunk("ok")}},
    ]
    history = InMemoryChatMessageHistory()

    frames = _drain("hi", history, events, monkeypatch)

    labels = [f["label"] for f in frames if f["type"] == "status"]
    assert coach_agent.DEFAULT_TOOL_LABEL in labels


def test_system_prompt_guides_progression_minimum_length():
    """Regression for #19: the agent occasionally returned a too-thin 2-chord
    progression. The fix lives in the system prompt — it must steer the agent to
    recommend at least 3 chords (typically 4). Guard that guidance so it isn't
    silently dropped in a future prompt edit, which would let the bug regress."""
    prompt = coach_agent.SYSTEM_PROMPT.lower()
    assert "at least 3 chords" in prompt
    assert "two-chord" in prompt
