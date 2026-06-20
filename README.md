# ChordCoach — AI Guitar Progression Coach

> A conversational AI agent that teaches guitar chord progressions through music-theory reasoning,
> interactive SVG diagrams, and session-aware skill adaptation — built with a LangChain
> function-calling agent, FastAPI, and Next.js 14.

---

## The Problem

Learning guitar stalls at the same place for most people: they can play a few open chords but have
no mental model of *why* certain chords sound good together. Static resources (YouTube, chord
books, tabs) tell you *what* to play but not *why it works* or *what to play next*. The feedback
loop is slow — a student has to context-switch between multiple tools just to get an answer and
see what the chords look like under their fingers.

ChordCoach collapses that loop into a single conversational interface: ask a question in plain
English, receive a music-theory explanation, and see interactive chord diagrams rendered instantly
in the same view.

---

## What It Does

- **Progression recommendations** by genre, key, mood, or song style
- **Music theory explanations** — automatic key detection, Roman numeral analysis, diatonic chord
  sets, tension/resolution mechanics — computed from first principles rather than looked up from a
  static table. The key is inferred from the whole progression, so off-tonic progressions are
  labelled correctly (e.g. `Am-F-C-G` is read as C major, `vi-IV-I-V`)
- **Finger placement guides** with step-by-step instructions and transition tips between specific
  chords
- **Song-inspired progressions** — searches the web for a song's key and feel, then builds a
  matching progression from the local dataset without reproducing copyrighted chord sheets
- **Skill-level adaptation** — beginner sessions filter out barre and advanced chords
  automatically; the agent detects level from context or asks once early
- **Practice log** — the agent tracks every progression and chord the user engages with per
  session

---

## Architecture

```
Browser
  |
  |── GET/POST ──> Next.js (port 3000)
  |                  app/page.tsx            split layout: chat 55%, diagrams 45%
  |                  components/Chat.tsx     session management, message loop
  |                  components/ChordDiagram.tsx  hand-coded SVG renderer (no library)
  |                  lib/types.ts            shared TypeScript interfaces
  |
  |── POST /api/chat/stream ──> FastAPI (port 8000)   NDJSON event-frame stream (status/token)
                         main.py             routes, CORS, request logging
                         agent/coach_agent.py  LangChain AgentExecutor + system prompt
                         agent/tools.py        13 @tool functions
                         agent/memory.py       in-process session store, 2-hour TTL
                         data/chords.py        40+ chord fingering definitions
                         data/progressions.py  30+ named progressions
```

### Structured Output Protocol

The most important architectural decision is how the LLM drives the UI without hallucinating
chord names. Every agent response that includes chord recommendations ends with a fenced JSON
block:

```
```json
{
  "action": "show_chords",
  "chords": ["Am", "F", "C", "G"],
  "progression_name": "Indie Pop Staple",
  "bpm_suggestion": 110
}
```
```

`Chat.tsx` parses this block with a regex, strips it from the displayed message text, then
fetches real fingering data for each chord name from the backend's `/api/chord/{name}` endpoint.
The chord diagram panel renders from that verified data — not from LLM output. This separation
means the LLM can describe chords in any prose style while the visual layer stays grounded in
the authoritative database.

Because the reply is **streamed**, `/api/chat/stream` sends **NDJSON event frames** — one JSON
object per line — rather than raw text:

```
{"type":"status","label":"Searching the web…"}   ← progress shown while the agent works
{"type":"token","text":"Let me"}                  ← one answer-text delta
{"type":"error","message":"…"}                    ← emitted on failure
```

A leading `status` frame (`"Thinking…"`) is sent immediately, and each agent `on_tool_start`
emits a friendly per-tool `status` (e.g. `"Searching the web for the real chords…"`), so the
chat bubble shows live activity within ~1–2s instead of sitting blank during the agent's
planning/tool window. `Chat.tsx` parses the stream line-by-line: it renders the `status` label
under a typing indicator until the first `token` arrives, then appends `token` deltas into the
live message. The trailing action block streams as `token` frames and is reassembled, so
`Chat.tsx` still parses it with the same regex once the stream finishes (the full JSON has
arrived). `MessageBubble` strips both completed and still-unterminated trailing ` ```json `
fences, so the raw JSON never flashes on screen mid-stream.

### Agent Design: Native Function Calling, Not ReAct

The agent uses `create_tool_calling_agent` (LangChain's function-calling pattern) instead of
text-based ReAct. This has two practical advantages for this domain:

1. **Reliability** — the LLM does not need to parse its own "Action: / Observation:" output
   lines, which is fragile. Tool calls are structured JSON submitted through the API.
2. **Fewer LLM calls** — the function-calling path resolves tool results in fewer round-trips
   than a ReAct scratchpad, which matters for response latency.

`max_iterations=5` is intentional: complex questions (song-style search + progression lookup +
theory explanation) can legitimately need three or four tool calls, but an uncapped loop would
run up API costs on edge cases.

### Music Theory Computed at Runtime

The `get_scale_chords` tool does not look up diatonic chord sets from a table — it computes
them from interval patterns:

```python
SCALE_PATTERNS = {
    "major":     [0, 2, 4, 5, 7, 9, 11],
    "dorian":    [0, 2, 3, 5, 7, 9, 10],
    "mixolydian":[0, 2, 4, 5, 7, 9, 10],
    ...
}
```

Given any root note and scale, it builds the full diatonic chord set by stacking intervals.
This means the agent can answer "what chords are in F# Dorian?" correctly without that specific
key appearing in any dataset.

### Session Memory

Each session gets an `InMemoryChatMessageHistory` plus a `practice_log` list and a `skill_level`
field, all stored in a plain Python dict keyed by UUID. The agent feeds back the last 10 turns
(`HISTORY_WINDOW_TURNS`), windowed at read time. Sessions expire after two hours via lazy eviction
on each request. There is no database — this is a deliberate MVP choice that keeps the deploy
surface minimal (one process per service on Render). Sessions reset on backend restart/redeploy.

The session UUID is generated on the frontend and persisted to `localStorage`, so the user's
conversation survives page refreshes within the same browser tab.

---

## Tech Stack

| Layer | Technology | Version |
|---|---|---|
| Backend runtime | Python, FastAPI, uvicorn | 3.11 / 0.115.0 / 0.30.6 |
| Agent framework | LangChain (`create_tool_calling_agent`) | 0.3.x |
| LLM | DeepSeek V3 via OpenAI-compatible API | `deepseek-chat` |
| Web search | DuckDuckGo via the `ddgs` client (queries run concurrently) | no API key required |
| Frontend | Next.js (App Router), React, TypeScript | 14.2.15 / 18 / 5 |
| Styling | Tailwind CSS | 3.4.1 |
| Markdown | `react-markdown` + `remark-gfm` | — |
| Diagrams | Hand-coded SVG React component | no library |
| API hardening | `slowapi` rate limiting + shared-secret auth | — |
| Deploy | Render (two public Web Services, `render.yaml` Blueprint) | — |

---

## Local Development

### Prerequisites

- Python 3.12 (pinned via `backend/.python-version`)
- Node.js 20+ (pinned via `frontend/package.json` `engines`)
- A DeepSeek API key (free tier available at platform.deepseek.com)

### Backend

```bash
cd chord-coach/backend

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env — set DEEPSEEK_API_KEY=your_key_here and a local INTERNAL_API_TOKEN
# (generate one: python -c "import secrets;print(secrets.token_urlsafe(32))")

uvicorn main:app --reload --port 8000
```

Verify: `GET http://localhost:8000/api/health` should return `{"status":"ok","version":"1.0.0"}`.

### Frontend

```bash
cd chord-coach/frontend

npm install

cp .env.example .env.local
# Set BACKEND_URL=http://localhost:8000 and INTERNAL_API_TOKEN to the SAME value
# you put in backend/.env (both are server-only — no NEXT_PUBLIC_ prefix).

npm run dev        # http://localhost:3000
```

Verify chord diagrams in isolation (no backend needed): `http://localhost:3000/test-chord`

---

## Testing

Both services have automated test suites that run in CI (GitHub Actions,
`.github/workflows/ci.yml`) on every pull request and push to `main`.

**Backend** — pytest, covering the API routes, theory engine, session memory,
and chord/progression data integrity:

```bash
cd chord-coach/backend
pip install -r requirements-dev.txt   # requirements.txt + pytest
pytest -q
```

**Frontend** — Vitest, covering the structured-output (`AgentAction`) parser,
the NDJSON stream-frame reassembly, and the server→backend header/URL helpers:

```bash
cd chord-coach/frontend
npm install
npm test                 # vitest run (one-shot)
npm run test:watch       # watch mode
npm run test:coverage    # with a coverage report
```

CI runs the two suites as independent jobs gated by path filters (backend
changes don't trigger the frontend job and vice-versa), with a final `ci`
aggregator job suitable for a required branch-protection check.

---

## API Reference

> **Auth:** every endpoint except `/api/health` requires the header
> `X-Internal-Token: <INTERNAL_API_TOKEN>` and returns **401** without it. The
> browser never sends this directly — it calls same-origin Next.js route handlers
> (`/api/chat`, `/api/backend/<backend-path>`) which attach the token server-side
> and forward the real client IP as `X-Forwarded-For` for rate limiting.
> `/api/chat` is rate-limited to **20/min per IP** plus a global **500/day** cap.

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/api/health` | GET | open | Health check (Render health probe) |
| `/api/chat` | POST | token | Send message to the AI agent; returns the full reply as JSON `{response, session_id}` (rate-limited) |
| `/api/chat/stream` | POST | NDJSON | Same body as `/api/chat`; streams the reply as chunked `text/plain` **NDJSON event frames** (`status` / `token` / `error`, one JSON object per line) so progress and answer text render as they're generated. Used by the frontend. Same rate limits. |
| `/api/chord/{name}` | GET | token | Chord fingering data (e.g. `Am`, `G7`, `Bm`) |
| `/api/chords` | GET | token | All chords in the database |
| `/api/progressions` | GET | token | All progressions; filter with `?genre=blues` or `?key=E` |
| `/api/session/{id}` | DELETE | token | Clear a session's conversation memory |
| `/api/session/{id}/practice-log` | GET | token | Retrieve session practice history and skill level |

**Chat request body:**

```json
{
  "message": "Give me a blues progression in E",
  "session_id": "uuid-v4",
  "context": {
    "key": "E",
    "scale": "Major",
    "skill_level": "beginner"
  }
}
```

---

## Extending the Dataset

### Adding a Chord

Edit `backend/data/chords.py`. String order is `[E A D G B e]` (low to high). Use `-1` for
muted strings and `0` for open strings.

```python
"Dm7": {
    "name": "Dm7",
    "full_name": "D minor 7th",
    "positions": [-1, -1, 0, 2, 1, 1],
    "fingers":   [ 0,  0, 0, 3, 1, 2],
    "base_fret": 1,
    "notes": ["D", "A", "C", "F"],
    "type": "minor7",        # major minor dominant7 major7 minor7 power add9 sus4 diminished
    "difficulty": "beginner" # beginner intermediate advanced
}
```

For barre chords, add a `barre` key:

```python
"barre": { "from_string": 0, "to_string": 5, "fret": 2, "finger": 1 }
```

### Adding a Progression

Edit `backend/data/progressions.py`. All fields are required.

```python
{
    "id": "my-progression",
    "name": "My Progression Name",
    "genre": ["rock"],
    "key": "G",
    "chords": ["G", "D", "Em", "C"],
    "roman": ["I", "V", "vi", "IV"],
    "difficulty": "beginner",
    "description": "Where this comes from and why it works.",
    "feel": "uplifting, driving",
    "tempo_bpm": 120,
    "tags": ["rock", "pop"],
}
```

Valid genres: `blues pop rock folk jazz country rnb reggae indie classical`

---

## Issues Encountered During Development

A few problems surfaced once the agent was running against real songs. Each one was traced
from the `AgentExecutor` verbose logs and resolved as follows.

### 1. Wasted tool calls on real-song lookups (latency)

**Symptom.** Asking "how do I play Sailor Song by Gigi Perez" produced a correct answer but
took ~20 s. The trace showed the agent calling `get_chord_info('G#m')` (the chord DB only
holds beginner open shapes, so it returned "not found" and was ignored) and
`get_progressions_by_key_tool('G#m')` (that tool only queries the *internal* generic-progression
dataset, whose keys are `C, G, D, A, E, Am, Em, Gm, Bb` — it can never contain a real song).
Both were dead-end round-trips to the LLM, each costing ~2 s.

**Fix.** Added explicit guidance to the system prompt (`agent/coach_agent.py`) telling the agent
to extract chords straight from `find_song_chords` results and *not* to "confirm" a real song
with the dataset/key/mood tools or look up its chords via `get_chord_info`. This removed two LLM
round-trips per song lookup.

### 2. Sequential web searches dominated response time

**Symptom.** `find_song_chords` ran three search queries one after another, and the underlying
`ddgs` client fans each query out to several backends (Wikipedia, Mojeek, Startpage…). The
three sequential queries accounted for ~7 s of the total.

**Fix.** The three queries are now issued concurrently via a `ThreadPoolExecutor`
(`agent/tools.py`), so total search time is bounded by the slowest single query instead of their
sum, while result ordering is preserved.

### 3. Inferred progressions presented as "the real chords" (grounding)

**Symptom.** When search snippets were fragmentary, the agent would confidently state a full
chord loop — including chords no source actually mentioned — and label it "The Real Chords."
For an app whose whole promise is song accuracy, this overconfidence was the riskiest behavior.

**Fix.** The system prompt now requires the stated progression to be traceable to the search
text and to be hedged ("commonly played as…") when sources are fragmentary, and forbids silently
appending unsupported chords.

### 4. Deprecated `ConversationBufferWindowMemory`

**Symptom.** Every request logged a `LangChainDeprecationWarning` — `ConversationBufferWindowMemory`
is deprecated in LangChain 0.3 and slated for removal.

**Fix.** Migrated session memory to `InMemoryChatMessageHistory` (`agent/memory.py`). The k-turn
window is now applied explicitly at read time in `run_agent` (`HISTORY_WINDOW_TURNS = 10`), and
the `AgentExecutor` no longer takes a `memory=` argument — history is passed in via the
`chat_history` prompt variable and the turn is appended after each response.

### 5. Broken cadence detection in `explain_theory`

**Symptom.** The "Progression patterns detected" block matched the Roman-numeral pattern keys
(`V-I`, `ii-V-I`, …) as substrings against the *chord-name* string (e.g. `Am-F-C-G`), which
almost never matched. A computed `found` flag was discarded, and the section header was emitted
even when empty.

**Fix.** Rewrote detection to work on **root motion**: the progression is converted to scale
degrees relative to its tonic (`_progression_degrees`) and matched against degree sequences
(`TENSION_RESOLUTION_DEGREES`). The header is now only emitted when a pattern actually matches.
`C-G-Am-F` correctly resolves to degrees `[1, 5, 6, 4]` and is identified as the I-V-vi-IV loop.

### 6. Off-tonic progressions mislabelled in `explain_theory`

**Symptom.** Roman-numeral and cadence analysis assumed the **first** chord was the tonic, so a
progression that starts off-tonic was labelled in the wrong key — `Am-F-C-G` came out as A minor
(`i-VI-III-VII`) instead of C major (`vi-IV-I-V`), and the empty key header was emitted regardless.

**Fix.** Added Krumhansl-Schmuckler key finding (`_infer_key`): each chord's tones build a
pitch-class histogram that is correlated against all 24 key profiles (12 keys × major/minor); the
best correlation picks the tonic and mode. Because distribution-only key finding ignores word order
(it reads the ii-V-I `Dm-G-C` as G major), an order-aware authentic-cadence bonus (`_CADENCE_BONUS`)
nudges any tonic that a `V→I` resolves into — this is inert on looping progressions that contain no
linear `V→I`, so it does not disturb cases like `Am-F-C-G`. `explain_theory` now prints the detected
key and a per-chord Roman-numeral line, and cadence detection runs relative to the inferred tonic.

### 7. Truncated `BACKEND_URL` caused 502 on all proxied requests

**Symptom.** The frontend loaded, but every chat message and chord-diagram request returned 502
Bad Gateway. The browser network tab showed `POST /api/chat` and
`GET /api/backend/api/session/.../practice-log` both failing with 502; the server error message
was `"Failed to reach backend"`.

**Root cause.** `BACKEND_URL` in the Render frontend service had been manually typed as
`ttps://chordcoach-backend.onrender.com` — the leading `h` was missing. `resolveBackendUrl()`
in `lib/serverBackend.ts` tests the value against `/^https?:\/\//i`; because the value didn't
match, it prepended `https://` and produced the invalid URL
`https://ttps://chordcoach-backend.onrender.com`. Every `fetch()` call threw a connection error
that was caught and returned as 502.

**Fix.** Corrected `BACKEND_URL` to `https://chordcoach-backend.onrender.com` in the Render
dashboard for `chordcoach-frontend`. No code change was required.

**Prevention.** After any deploy, open the frontend service's **Environment** tab and confirm
`BACKEND_URL` begins with `https://`. The `fromService` Blueprint wiring (which sets it to the
bare hostname `chordcoach-backend.onrender.com`) is handled correctly by the code — it is only
risky if the variable is edited manually in the dashboard.

### 8. Chat reply showed ~20 s of blank typing dots, then burst in (streaming UX)

**Symptom.** After sending a message the typing indicator sat blank for ~20 s, then the whole
answer appeared at once — it looked broken rather than streamed. The streaming chain was already
wired correctly end-to-end, so the mechanics weren't at fault.

**Root cause.** Time-to-first-token. `/api/chat/stream` only yielded the agent's *final-answer*
tokens (`on_chat_model_stream`). Before that answer exists, the `AgentExecutor` runs sequential
DeepSeek planning calls plus tool executions (and, for songs, a slow web search). During that
~15–20 s window there is genuinely no user-facing text to stream, so the bubble stayed blank;
then the short final answer streamed in a couple of seconds and read as a sudden burst.

**Fix.** Upgraded `/api/chat/stream` from a raw token-text stream to **NDJSON event frames**
(`agent/coach_agent.py` `run_agent_stream`): an immediate `status` `"Thinking…"` frame, a
per-tool `status` frame on each `on_tool_start` (mapped via `TOOL_STATUS_LABELS`), and `token`
frames for the answer deltas. `Chat.tsx` parses the stream line-by-line and shows the live status
under the typing indicator until the first token arrives. The trailing action JSON still
reassembles from `token` frames, so the chord-panel contract is unchanged.

---

## Deployment on Render

Both services deploy as **public Web Services** from one repo via the `render.yaml`
Blueprint at the project root. Security comes from the app design, not the hosting
tier — the DeepSeek key stays on the backend, every token-spending route requires a
shared secret, and traffic is rate-limited and CORS-locked.

**See [`RENDER_MIGRATION.md`](./RENDER_MIGRATION.md) for the full step-by-step runbook**
(deploy order, exact env vars / Secret Files, key-rotation procedure, and an incident
checklist). In brief:

1. **Rotate the DeepSeek key first** — treat any key that has been in a local `.env`
   as compromised. Revoke it and generate a fresh one.
2. **New → Blueprint** in Render, pointed at the repo. It reads `render.yaml` and
   proposes `chordcoach-backend` and `chordcoach-frontend`.
3. Enter the fresh `DEEPSEEK_API_KEY` on the backend (`sync: false`, or a Secret
   File). `INTERNAL_API_TOKEN` is auto-generated and shared to the frontend via
   `fromService`; `BACKEND_URL` is wired from the backend's host.
4. Deploy (backend first, then frontend). After the frontend URL exists, set
   `FRONTEND_URL` on the backend to that exact origin and redeploy so CORS is precise.
5. **Verify `BACKEND_URL` after deploy.** Open the frontend service's Environment tab
   and confirm the value is either the bare hostname (`chordcoach-backend.onrender.com`,
   set by `fromService`) or the full URL starting with `https://`. If you have edited
   it manually, a single typo — such as a missing leading `h` — produces an invalid URL
   that silently causes every proxied request to return 502. The `/api/health` endpoint
   will still pass (it is called directly by Render, not through the proxy), so a
   corrupt `BACKEND_URL` is not caught by the health check.

Health check paths (`/api/health` for the backend) are set in `render.yaml` and gate
deploys.
