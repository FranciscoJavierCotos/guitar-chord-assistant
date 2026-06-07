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
  |── POST /api/chat ──> FastAPI (port 8000)
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
surface minimal (one stateless process per service on Railway).

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
| Deploy | Railway (two independent services) | — |

---

## Local Development

### Prerequisites

- Python 3.11+
- Node.js 18+
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
# Edit .env — set DEEPSEEK_API_KEY=your_key_here

uvicorn main:app --reload --port 8000
```

Verify: `GET http://localhost:8000/api/health` should return `{"status":"ok","version":"1.0.0"}`.

### Frontend

```bash
cd chord-coach/frontend

npm install

cp .env.example .env.local
# Default NEXT_PUBLIC_BACKEND_URL=http://localhost:8000 works for local dev

npm run dev        # http://localhost:3000
```

Verify chord diagrams in isolation (no backend needed): `http://localhost:3000/test-chord`

---

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Health check |
| `/api/chat` | POST | Send message to the AI agent |
| `/api/chord/{name}` | GET | Chord fingering data (e.g. `Am`, `G7`, `Bm`) |
| `/api/chords` | GET | All chords in the database |
| `/api/progressions` | GET | All progressions; filter with `?genre=blues` or `?key=E` |
| `/api/session/{id}` | DELETE | Clear a session's conversation memory |
| `/api/session/{id}/practice-log` | GET | Retrieve session practice history and skill level |

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

---

## Deployment on Railway

Both services use `railway.toml` for zero-config detection. The backend auto-detects Python via
Nixpacks; the frontend builds with `npm run build` and serves with `npm start`.

1. Create a Railway project and connect the GitHub repo.
2. **Backend service** — set Root Directory to `/chord-coach/backend`, add `DEEPSEEK_API_KEY`.
3. **Frontend service** — set Root Directory to `/chord-coach/frontend`, add
   `NEXT_PUBLIC_BACKEND_URL` pointing at the backend Railway URL.

Health check paths (`/api/health` for backend, `/` for frontend) are already set in
`railway.toml` and will gate deploys.
