"""
ChordCoach LangChain agent — uses native tool calling (function calling API)
instead of text-based ReAct, which is more reliable and uses fewer LLM calls.
"""

import json
import os
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage

import time

from agent.memory import HISTORY_WINDOW_TURNS
from agent.tools import TOOLS, _current_session_id
from observability import agent_run_span, get_agent_callback, record_ttft

# Prefix of the user-facing fallback returned by run_agent when the agent turn
# raises (bad/expired API key, network failure, provider 5xx, …). Exported so
# callers that need to tell an *infrastructure* failure apart from a real answer
# — notably the offline eval runner — can detect it without string-duplicating
# the wording. Keep run_agent's fallback message anchored on this constant.
AGENT_ERROR_PREFIX = "I ran into a technical issue:"

# Sampling temperature for the live chat agent. Kept at 0.7 for varied, lively
# replies in production. Callers that need reproducible output — notably the
# offline eval runner, where a flaky temperature turns the regression gate into
# noise — pass an explicit ``temperature`` (e.g. 0) to build_agent_executor /
# run_agent to override it.
DEFAULT_AGENT_TEMPERATURE = 0.7

SYSTEM_PROMPT = """You are ChordCoach, an expert guitar teacher and music theorist. You help guitarists learn chord progressions, understand music theory, and discover new songs to play.

Your personality: encouraging, knowledgeable, enthusiastic about music, patient with beginners.

When recommending progressions:
1. Use your tools to fetch real data — do not invent chord names or positions
2. Briefly explain WHY the progression works (the theory behind it)
3. Mention the emotional feel and what genres it suits
4. Suggest a simple practice tip

When the user asks for a progression using a specific chord (e.g. "using Em"), use get_progressions_by_key_tool with that chord's key, or use get_scale_chords to find chords in that key and build a progression.

--- PLAYING A SPECIFIC REAL SONG (most important) ---
When a user asks to PLAY, LEARN, or get the chords for a named song ("how do I play
Sailor Song by Gigi Perez", "chords for Wonderwall"), they want the song's ACTUAL
chords — not a generic progression that merely shares a vibe.

Copyright note: chord progressions and keys are NOT copyrighted. It is correct and
expected to give the real chords a song uses. (Only full tablature, sheet music, and
lyrics are protected — don't paste those.) This applies to recent songs too.

Steps:
1. Call find_song_chords(song_title, artist) to look up the real progression and key.
2. Report the song's ACTUAL chords and original key, cross-checking the search results
   for agreement across sources. Never substitute a generic I-vi-IV-V (e.g. C-Am-F-G)
   for the real chords.
3. If the real key needs barre chords and the player is a beginner, call
   transpose_chords(..., capo_fret=N) to give an open-chord capo version, and state the
   capo fret clearly. Show BOTH the original (e.g. "E - G#m - B") and the capo version
   (e.g. "Capo 4: C - Em - G").
4. ONLY if the search genuinely fails to reveal the chords: say so honestly, then offer
   a similar-feel progression — and label it explicitly as an approximation, not the
   song's real chords.
5. Briefly note the feel/why, but accuracy to the real song comes first.

Tool efficiency & grounding for song lookups (read carefully — these avoid wasted calls):
- Get the chords and key STRAIGHT from the find_song_chords results. Do NOT call
  get_progressions_by_key_tool, get_progressions_by_mood_tool, or get_progressions_by_genre_tool
  to "confirm" a real song — those tools only return generic progressions from our internal
  dataset (keys C, G, D, A, E, Am, Em, Gm, Bb), never real songs, so they cannot validate
  anything and only add latency.
- Do NOT call get_chord_info on a song's chord just to discover the progression — the chord
  database only holds the open-chord shapes a beginner plays, not barre/sharp chords like G#m.
  Only call get_chord_info / get_finger_placement_guide if the user explicitly asks how to
  finger a specific chord.
- State only the chords the sources actually support. If the sources are fragmentary and you
  are inferring the loop, say "commonly played as …" rather than presenting it as confirmed.
  Never silently append chords the sources didn't mention.

--- PROGRESSION BY MOOD, GENRE, OR FEEL ---
A request for a progression by mood or vibe ("I'm in a melancholic mood, give me a sad
progression", "something energetic", "a dreamy progression", "in the style of folk
ballads") is a CHORD-DISPLAY request, not just chit-chat — always deliver an actual
progression, never only prose. Do this every time:
1. Call get_progressions_by_mood_tool (for a mood/feel) or get_progressions_by_genre_tool
   (for a genre); for an unusual key/feel you can instead build one with get_scale_chords.
   Pick a real progression from the results — for a sad/melancholic request, a minor-heavy
   one (e.g. an Am/Em-based progression).
2. State the chords (at least 3) and explain WHY they carry that emotional character.
3. ALWAYS end with the show_chords JSON block (see RESPONSE FORMAT) so the chord panel
   updates. A mood/genre reply WITHOUT the show_chords block is a failure — never reply
   with a vague suggestion ("just strum slowly") and no progression.

--- FINGER PLACEMENT GUIDES ---
When a user asks "how do I play [Chord]", "show me [Chord] fingering", or asks about transitions:
1. Call get_finger_placement_guide(chord_name, from_chord, to_chord)
2. Follow with the show_chord JSON action block so the diagram appears
3. Pass from_chord/to_chord when the user mentions transitioning between two chords

--- DIFFICULTY ADAPTATION ---
Default skill level is beginner. Call set_user_skill_level when the user states their level or context implies it.
- beginner: Open chords only (Em, Am, G, C, D, A, E, Dm). Avoid barre chords.
- intermediate: Include barre chords (F, Bm, Fm), 7th chords (Am7, Cmaj7, G7).
- advanced: Full range — jazz voicings, extended chords (maj9, min11), modal progressions.
If the user's level is unknown and they haven't stated it, ask once early in the conversation.

--- PRACTICE LOG ---
Call log_practice_session once per response whenever you present a progression the user engages with.
Do not call it more than once per response.
When asked "what have I been practicing?" or "show my history", call get_practice_log().

--- RESPONSE FORMAT ---
Use markdown. Whenever your reply recommends a progression or chords to play — including
mood, genre, and "vibe" requests — you MUST end the message with the show_chords JSON
block below. Do not describe a progression without emitting the block.
End your message with a JSON block formatted EXACTLY like this:

```json
{{
  "action": "show_chords",
  "chords": ["Em", "C", "G", "D"],
  "progression_name": "Indie Rock Staple",
  "bpm_suggestion": 105
}}
```

If showing a single chord for explanation, use:
```json
{{
  "action": "show_chord",
  "chord": "Am"
}}
```

Keep responses focused, practical, and inspiring."""


# Friendly, present-tense status labels shown in the chat bubble while the agent is
# working, keyed by tool name (matches the @tool function names in agent/tools.py).
# These fill the otherwise-blank "thinking" window before the final answer streams.
TOOL_STATUS_LABELS = {
    "find_song_chords": "Searching the web for the real chords…",
    "get_progressions_by_key_tool": "Finding progressions in that key…",
    "get_progressions_by_genre_tool": "Finding progressions for that style…",
    "get_progressions_by_mood_tool": "Finding progressions for that mood…",
    "get_scale_chords": "Working out the scale's chords…",
    "explain_theory": "Working through the theory…",
    "suggest_next_chord": "Thinking about the next chord…",
    "transpose_chords": "Transposing the chords…",
    "get_finger_placement_guide": "Writing the finger-placement guide…",
    "get_chord_info": "Looking up the chord shape…",
    "log_practice_session": "Saving this to your practice log…",
    "get_practice_log": "Pulling up your practice history…",
    "set_user_skill_level": "Adjusting to your skill level…",
}
DEFAULT_TOOL_LABEL = "Working on it…"


def build_agent_executor(temperature: float | None = None) -> AgentExecutor:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        # Belt-and-suspenders: the /api/chat route already 503s when the key is
        # missing, but guard here too so a misconfigured deploy fails clearly
        # instead of with an opaque KeyError.
        raise RuntimeError("DEEPSEEK_API_KEY is not configured on the server.")

    llm = ChatOpenAI(
        model="deepseek-chat",
        api_key=api_key,
        base_url="https://api.deepseek.com/v1",
        temperature=DEFAULT_AGENT_TEMPERATURE if temperature is None else temperature,
        max_tokens=2048,
        # Required for token-by-token streaming. Without this, langchain calls
        # DeepSeek in non-streaming mode, so AgentExecutor.astream_events surfaces
        # the whole final answer as a single chunk at the end (~25s wait) instead
        # of streaming it as it's generated. See run_agent_stream.
        streaming=True,
        # Surface token usage in the final streamed chunk so the observability
        # callback can record token counts / estimated cost (no-op when export
        # is off). Harmless on the non-streaming path.
        stream_usage=True,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder("chat_history", optional=True),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad"),
    ])

    agent = create_tool_calling_agent(llm=llm, tools=TOOLS, prompt=prompt)

    return AgentExecutor(
        agent=agent,
        tools=TOOLS,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=5,
        early_stopping_method="force",
    )


def _windowed(history: InMemoryChatMessageHistory) -> list:
    """Return the last HISTORY_WINDOW_TURNS turns (human+AI pairs) of history."""
    return history.messages[-(HISTORY_WINDOW_TURNS * 2):]


def _apply_context_prefix(message: str, context: dict | None) -> str:
    """Prepend a bracketed context hint (key/scale/skill) to the user message so
    the agent has session context. Returns the message unchanged if no context."""
    if not context:
        return message
    key = context.get("key", "")
    scale = context.get("scale", "")
    skill = context.get("skill_level", "")
    prefix_parts = []
    if key or scale:
        prefix_parts.append(f"key of {key}, {scale} scale")
    if skill:
        prefix_parts.append(f"user level: {skill}")
    if prefix_parts:
        return f"[Context: {', '.join(prefix_parts)}] " + message
    return message


async def run_agent(
    message: str,
    history: InMemoryChatMessageHistory,
    context: dict | None = None,
    session_id: str = "",
    temperature: float | None = None,
) -> str:
    message = _apply_context_prefix(message, context)

    executor = build_agent_executor(temperature=temperature)
    token = _current_session_id.set(session_id)
    callback = get_agent_callback()
    try:
        with agent_run_span(streaming=False):
            result = await executor.ainvoke(
                {"input": message, "chat_history": _windowed(history)},
                config={"callbacks": [callback]},
            )
        # `or` (not get's default) so an empty-string output — which the
        # tool-calling agent occasionally returns after a tool turn — also falls
        # back instead of surfacing as a blank answer.
        output = result.get("output") or "I couldn't generate a response. Please try again."
        # Persist the turn so subsequent requests in this session have context.
        history.add_messages([HumanMessage(content=message), AIMessage(content=output)])
        return output
    except Exception as exc:
        return (
            f"{AGENT_ERROR_PREFIX} {exc}\n\n"
            "Please try rephrasing your question or ask me something else!"
        )
    finally:
        _current_session_id.reset(token)


def _frame(payload: dict) -> str:
    """Serialise one NDJSON event frame (a JSON object on its own line). JSON
    encoding escapes newlines inside token text, so the client can split on '\n'."""
    return json.dumps(payload, ensure_ascii=False) + "\n"


async def run_agent_stream(
    message: str,
    history: InMemoryChatMessageHistory,
    context: dict | None = None,
    session_id: str = "",
):
    """Async generator that yields the agent turn as NDJSON event frames.

    Frame types (one JSON object per line):
      {"type":"status","label":...}  progress shown while the agent works
      {"type":"token","text":...}    a final-answer text delta
      {"type":"reset"}               discard any answer text streamed so far
      {"type":"error","message":...} a failure (emitted by the caller)

    Uses AgentExecutor.astream_events: an immediate "Thinking…" status covers the
    initial planning call, on_tool_start emits a per-tool status to fill the
    otherwise-blank tool window, and on_chat_model_stream surfaces content
    token-by-token.

    Only the FINAL answer's content is kept. With a tool-calling agent every
    planning iteration is a separate model run that, with DeepSeek, emits a
    conversational preamble (e.g. "Let me look up the chords…") *alongside* its
    tool call — so content is NOT exclusive to the final run. Streaming every
    run's content concatenated those preambles into the reply and, worse,
    persisted them to history, so the next turn replayed and amplified the
    garbage. We therefore track the model run via each event's ``run_id``: when a
    new run starts producing content we drop whatever the previous run streamed
    (a planning preamble) and emit a ``reset`` frame so the client clears it. The
    last run to stream content is the real answer; it has no successor to reset
    it, so it survives in both the stream and the persisted turn.
    """
    message = _apply_context_prefix(message, context)

    executor = build_agent_executor()
    token = _current_session_id.set(session_id)
    callback = get_agent_callback()
    collected: list[str] = []
    # Sentinel distinct from a real run_id and from ``None`` (which some stubbed
    # events use), so the first content token always registers a fresh run.
    _UNSET = object()
    content_run_id: object = _UNSET
    start = time.perf_counter()
    first_token_seen = False
    try:
        with agent_run_span(streaming=True):
            # Immediate feedback so the bubble isn't blank during the first planning call.
            yield _frame({"type": "status", "label": "Thinking…"})

            async for event in executor.astream_events(
                {"input": message, "chat_history": _windowed(history)},
                version="v2",
                config={"callbacks": [callback]},
            ):
                kind = event["event"]
                if kind == "on_tool_start":
                    label = TOOL_STATUS_LABELS.get(event.get("name", ""), DEFAULT_TOOL_LABEL)
                    yield _frame({"type": "status", "label": label})
                    continue
                if kind != "on_chat_model_stream":
                    continue
                chunk = event["data"]["chunk"]
                text = chunk.content
                # OpenAI-compatible models stream content as a plain string; guard
                # against providers that emit a list of content parts.
                if isinstance(text, list):
                    text = "".join(
                        part.get("text", "") if isinstance(part, dict) else str(part)
                        for part in text
                    )
                if not text:
                    continue
                run_id = event.get("run_id")
                if run_id != content_run_id:
                    # A new model run is emitting content. Anything the previous
                    # run streamed was an intermediate planning preamble — drop it
                    # and tell the client to clear what it has shown so far.
                    if collected:
                        collected.clear()
                        yield _frame({"type": "reset"})
                    content_run_id = run_id
                if not first_token_seen:
                    record_ttft(time.perf_counter() - start)
                    first_token_seen = True
                collected.append(text)
                yield _frame({"type": "token", "text": text})

            full = "".join(collected)
            if full:
                history.add_messages([HumanMessage(content=message), AIMessage(content=full)])
    finally:
        _current_session_id.reset(token)
