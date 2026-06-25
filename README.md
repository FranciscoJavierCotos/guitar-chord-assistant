# ChordCoach — AI Guitar Progression Coach

> A conversational AI agent that teaches guitar chord progressions through music-theory
> reasoning and interactive chord diagrams — built with a LangChain function-calling agent,
> FastAPI, and Next.js 14, and shipped with the production scaffolding that keeps an LLM
> honest: an offline answer-quality eval gate, OpenTelemetry tracing, and a hardened public API.

**[Architecture](#architecture) · [How the agent works](#how-the-agent-works) ·
[Evaluation](#evaluation-keeping-the-agent-honest) · [Observability](#observability)**

---

## At a glance — for the busy reader

This is a small product wrapped in the engineering an AI feature actually needs in production:

| | |
|---|---|
| 🤖 **Agentic, not a chatbot** | LangChain native function-calling agent with **13 tools** (chord lookup, runtime music-theory engine, web search, practice log) and a capped reasoning loop. |
| 🎯 **Grounded output** | The LLM drives the UI through a **structured JSON action block**, but every chord it renders is re-fetched from an authoritative database — the model never hallucinates a fingering onto the screen. |
| 📊 **Quality is tested, not vibes** | An offline **eval harness** runs a version-controlled golden set through the real agent with **deterministic graders + an LLM-as-judge**, at a pinned temperature so the gate is reproducible and runs in CI. |
| 🔭 **Observable** | Opt-in **OpenTelemetry** traces every request → agent → tool → LLM call, with metrics for latency, **token cost**, and time-to-first-token, exported to Grafana Cloud. |
| 🔒 **Hardened public API** | Shared-secret auth, per-IP + global rate limits, locked CORS, a request-body ceiling, and the provider key kept strictly server-side. |
| ✅ **CI-gated** | pytest + Vitest suites and the deterministic eval run on every PR via GitHub Actions. |

The interesting work here is not the guitar app — it's everything around the LLM that makes it
trustworthy, measurable, and safe to expose on a public URL.

---

## The Problem

Most people learning guitar stall at the same place: they can play a few open chords but have no
mental model of *why* chords sound good together. Static resources tell you *what* to play, not
*why it works* or *what comes next*, and you have to juggle several tools just to see the shapes
under your fingers.

ChordCoach collapses that loop into one conversation: ask in plain English, get a music-theory
explanation, and see interactive chord diagrams render instantly in the same view.

**What it does** — progression recommendations by genre/key/mood/song; theory explanations
(key detection, Roman-numeral analysis, diatonic sets, tension/resolution) computed from first
principles; finger-placement and transition guides; song-inspired progressions built from a web
search without reproducing copyrighted chord sheets; skill-level adaptation; and a per-session
practice log.

---

## How the agent works

The product is a thin shell over four agent-design decisions that are the actual substance of the
project.

### 1. Native function calling, not ReAct

The agent uses LangChain's `create_tool_calling_agent` rather than text-based ReAct. Tool calls
are structured JSON through the API, so the model never has to parse its own
`Action:`/`Observation:` scratchpad (fragile), and tool results resolve in fewer round-trips
(lower latency). `max_iterations=5` is deliberate: a song lookup can legitimately need three or
four tool calls, but an uncapped loop would run up API cost on edge cases.

### 2. Structured output that the LLM can't poison

This is the most important decision. Every chord-bearing response ends with a fenced JSON action
block:

```json
{ "action": "show_chords", "chords": ["Am", "F", "C", "G"],
  "progression_name": "Indie Pop Staple", "bpm_suggestion": 110 }
```

The frontend strips this block from the displayed text, then fetches **real fingering data for
each chord name from the backend database** and renders the diagrams from that verified data — not
from anything the LLM drew. The model can describe chords in any prose style while the visual layer
stays grounded in the authoritative dataset. Breaking this contract breaks the chord panel, so the
schema is mirrored in the system prompt, `frontend/lib/types.ts`, and the eval graders.

### 3. Music theory computed at runtime, not looked up

`get_scale_chords` doesn't read diatonic sets from a table — it builds them by stacking intervals
over scale patterns:

```python
SCALE_PATTERNS = { "major": [0,2,4,5,7,9,11], "dorian": [0,2,3,5,7,9,10], ... }
```

So the agent answers *"what chords are in F# Dorian?"* correctly even though that key appears in no
dataset. Key detection is order-aware Krumhansl-Schmuckler with an authentic-cadence bonus, so an
off-tonic loop like `Am-F-C-G` is correctly read as C major (`vi-IV-I-V`), not A minor.

### 4. Streaming that shows only the *final* answer

`/api/chat/stream` returns the reply as **NDJSON event frames** (one JSON object per line) —
`status`, `token`, `reset`, `error` — so progress and text render as they're generated. Two
problems made this non-trivial:

- **Blank typing dots for ~20 s.** Before the final answer exists, the agent runs sequential
  planning calls, tool executions, and (for songs) a web search — genuinely no user-facing text to
  stream. Fix: emit an immediate `"Thinking…"` `status` frame and a friendly per-tool `status` on
  each `on_tool_start`, so the bubble shows live activity within ~1–2 s.
- **Planning preambles leaking into the answer.** A function-calling agent runs several model calls,
  and DeepSeek emits a conversational preamble ("Let me look up the chords…") *alongside* each tool
  call. `run_agent_stream` tracks the model run by `run_id`; when a later run starts producing
  content it emits a `reset` frame and the client discards the flashed preamble — only the last
  content run, the real answer, survives. This also keeps session history clean.

### Session memory — in-process today, Supabase from here on

Each session is an `InMemoryChatMessageHistory` plus a practice log and skill level in a plain dict
keyed by UUID, with the last 10 turns windowed at read time and a 2-hour TTL. This was an
intentional MVP choice that kept the deploy surface to one process per service; sessions reset on
redeploy, and the session UUID in `localStorage` lets conversations survive a page refresh.

**Epic B (in progress) reverses that** for durable, multi-user data: a Supabase Postgres database
with Auth and Row-Level Security now backs accounts, persistent conversations, and practice history.
Story **B0** lays the foundation — the versioned schema, `pgvector`, and the RLS baseline (see
[Data layer](#data-layer-supabase-epic-b)); later stories migrate the in-process store onto it.

---

## Evaluation — keeping the agent honest

Unit tests can't tell you whether the **agent's answers are any good**. A tweak to the system
prompt, model, or a tool's docstring can silently regress answer quality — wrong chords,
hallucinated fingerings, an invalid action block — while every unit test stays green. The offline
**eval harness** (`backend/eval/`) closes that gap by running a curated **golden set** of 20
version-controlled prompts (`eval/cases/*.yaml`: single chords, progressions by key/genre/mood,
theory, context follow-ups) through the real agent and scoring each response.

**Two grader families:**

- **Deterministic** (`eval/graders/deterministic.py`) — fast, free, no LLM. The action block
  parses and validates; **no hallucinated chords** (every referenced chord exists in
  `data/chords.py`); named progressions resolve; requested key and chord-count constraints hold.
- **LLM-as-judge** (`eval/graders/judge.py`) — scores musical correctness, relevance, and
  explanation quality 1–5 against a per-case rubric. The judge model is pinned and configurable.

**Reproducible by design.** The gate must return the same verdict on the same code, so the eval
runs the agent at a **pinned temperature** (0, vs production's 0.7) — a score change means a
code/prompt change, not sampling noise. Infrastructure failures (bad key, network, provider outage)
are reported as **errored** and abort with a distinct exit code, so an outage is never misread as a
0% quality regression.

```bash
cd chord-coach/backend && pip install -r requirements-dev.txt
python -m eval                 # full: agent + deterministic + judge
python -m eval --no-judge      # deterministic only (still calls the agent)
```

**CI gating** — the deterministic graders run **offline on every PR** (`tests/test_eval.py`, graded
against fixture responses), while the **full agent + judge eval** runs **only on manual
`workflow_dispatch`** (it makes real DeepSeek calls, so it is not run automatically) using the
`DEEPSEEK_API_KEY` secret, failing under configurable pass-rate thresholds and uploading the JSON
report as an artifact.

---

## Testing & CI

Both services have automated suites that run in GitHub Actions on every PR and push to `main`, as
independent path-filtered jobs plus two always-on **security gates**, all folded into a final `ci`
aggregator suitable for a required branch-protection check.

- **Backend** — pytest: API routes, the theory engine, session memory, and chord/progression data
  integrity. `cd backend && pip install -r requirements-dev.txt && pytest -q`
- **Frontend** — Vitest on the pure-logic units extracted out of React so they're testable in
  isolation: the `AgentAction` parser, the NDJSON stream-frame reassembly, and the server→backend
  header/URL helpers. `cd frontend && npm test`
- **Secret-leak scan** — [`gitleaks`](https://github.com/gitleaks/gitleaks) scans every PR (full
  history, redacted logs) for leaked credentials, with repo-specific rules in `.gitleaks.toml`
  (DeepSeek key, internal token, OTEL auth header; `.env.example` and test fixtures allowlisted).
- **SAST** — GitHub **CodeQL** analyzes Python and JS/TS for code vulnerabilities.

### Auto-merge policy

To keep human review light, PRs use **CI-gated auto-merge**: once a PR is open, auto-merge is
enabled (`gh pr merge <#> --auto --squash --delete-branch`) and GitHub merges it **only after the
`ci` check passes** (tests + secret scan + CodeQL), then deletes the branch. There is no
self-approval (GitHub forbids it) — the green-CI gate is the review. This requires the repo to allow
auto-merge and to require the `ci` status check on `main` (set once with
`gh repo edit --enable-auto-merge --delete-branch-on-merge` plus a branch-protection rule). Branch
protection is the safety net; the repo admin keeps a manual override for emergencies.

> Dependency-vulnerability auditing (pip-audit / npm audit) was deliberately left out to avoid
> blocking unrelated PRs on upstream advisories.

---

## Observability

The backend is instrumented with **OpenTelemetry** and can export **traces and metrics** to the
**Grafana Cloud free tier** (Tempo + Mimir) over one OTLP/HTTP endpoint. It answers the questions a
public LLM agent otherwise can't: *how slow is `/api/chat/stream` at p95? how many DeepSeek tokens
/ how much cost per request? which tool is the latency hotspot? are we near the 500/day cap?*

Instrumentation is **opt-in and a no-op when unconfigured** — local dev, CI, and tests run
unchanged without Grafana credentials. The manual instrumentation always goes through the OTel
*API*, which resolves to cheap no-ops until the SDK exporter is installed at startup.

**When enabled you get:**

- **Traces** — a request becomes one end-to-end trace: FastAPI server span → manual `agent.run`
  span → one child `tool.<name>` span per LangChain tool call → DeepSeek LLM call.
- **Metrics** — RED HTTP metrics per route plus domain metrics: agent + per-tool latency and call
  counts, DeepSeek token usage and **estimated cost**, streaming **time-to-first-token**, and
  rate-limit 429s. Labels are low-cardinality (no session ids or IPs; no secrets or bodies in spans).
- **Dashboards** — reproducible Grafana JSON in [`observability/`](observability/) (a deep-dive
  board and a free-tier KPI overview), with a runbook in
  [`observability/README.md`](observability/README.md) including *how to find a slow request via
  its trace*.

---

## Architecture

```
Browser
  │  (same-origin only — never calls the backend directly; the secret stays server-side)
  ├─ GET/POST ─────────────▶ Next.js (3000)
  │                            app/page.tsx              chat 55% / diagrams 45% split
  │                            components/Chat.tsx        session loop, stream parsing
  │                            components/ChordDiagram    hand-coded SVG renderer (no library)
  │                            app/api/*/route.ts         proxy: injects X-Internal-Token + client IP
  │
  └─ POST /api/chat/stream ─▶ FastAPI (8000)              NDJSON event-frame stream
                               main.py                    routes, CORS, auth, rate limiting
                               agent/coach_agent.py        AgentExecutor + system prompt + streaming
                               agent/tools.py              13 @tool functions
                               agent/memory.py             in-process session store, 2-hour TTL
                               db.py                       Supabase client (service-role + per-user RLS)
                               data/{chords,progressions}  40+ chords, 30+ named progressions
                               eval/                       offline answer-quality eval (python -m eval)
                               observability.py            opt-in OpenTelemetry (spans + metrics)

supabase/migrations/          versioned SQL schema (profiles, conversations, messages,
                               practice_events) + pgvector + RLS — the Epic B data layer
```

The backend is deployed on a **public URL**, so it's hardened: every `/api/*` route except
`/api/health` requires the `X-Internal-Token` shared secret (401 otherwise), `/api/chat` and
`/api/chat/stream` are rate-limited (**20/min per IP + 500/day** global via `slowapi`), CORS is
locked to `FRONTEND_URL`, interactive docs are off in production, and a 16 KB body ceiling applies.
The DeepSeek key never leaves the backend. The browser only ever hits same-origin Next.js route
handlers, which attach the secret server-side and forward the real client IP for rate limiting.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI 0.115, uvicorn |
| Agent | LangChain 0.3.x (`create_tool_calling_agent`, `AgentExecutor`) |
| LLM | DeepSeek V3 (`deepseek-chat`) via the OpenAI-compatible API |
| Web search | DuckDuckGo (`ddgs`, queries fanned out concurrently — no API key) |
| Frontend | Next.js 14.2 (App Router), React 18, TypeScript 5 (strict), Tailwind 3.4 |
| Diagrams | Hand-coded SVG React component (no charting library) |
| API hardening | `slowapi` rate limiting + shared-secret (`X-Internal-Token`) auth |
| Observability | OpenTelemetry (SDK + OTLP/HTTP + FastAPI auto-instr.) → Grafana Cloud (opt-in) |
| Persistence & auth | Supabase (Postgres + Auth + Row-Level Security), `pgvector` for RAG — versioned SQL migrations (Epic B) |
| Eval | Golden-set harness: deterministic graders + LLM-as-judge, CI-gated |
| Deploy | Render — two public Web Services via a `render.yaml` Blueprint |

---

## Local Development

**Prerequisites:** Python 3.12 (pinned via `backend/.python-version`), Node 20+, and a DeepSeek API
key (free tier at platform.deepseek.com).

```bash
# Backend
cd chord-coach/backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # set DEEPSEEK_API_KEY + a local INTERNAL_API_TOKEN
uvicorn main:app --reload --port 8000               # GET /api/health → {"status":"ok",...}

# Frontend (separate terminal)
cd chord-coach/frontend
npm install
cp .env.example .env.local  # BACKEND_URL=http://localhost:8000 + the SAME INTERNAL_API_TOKEN
npm run dev                 # http://localhost:3000  (diagrams in isolation: /test-chord)
```

Both `INTERNAL_API_TOKEN` values must match, and both frontend env vars are **server-only** (no
`NEXT_PUBLIC_` prefix — that would ship a secret to the browser).

---

## Data layer (Supabase, Epic B)

Durable accounts and practice history live in a **Supabase** Postgres database (Postgres + Auth +
Row-Level Security), with `pgvector` enabled for the RAG work in Epic C. The schema is **migration-
driven** — versioned SQL under [`supabase/migrations/`](supabase/migrations/), checked into the repo
and runnable locally or in CI.

**Schema (story B0).** Four user-scoped tables, every one with **RLS enabled and owner-only
policies** keyed on `auth.uid()`:

| Table | Purpose | Owner check |
|---|---|---|
| `profiles` | 1:1 with `auth.users`; auto-created on signup via trigger | `id = auth.uid()` |
| `conversations` | A user's chat threads | `user_id = auth.uid()` |
| `messages` | Turns within a conversation (`role`, `content`, structured `agent_action` JSON) | via parent `conversations` |
| `practice_events` | Append-only practice activity log | `user_id = auth.uid()` |

The backend never trusts the client for ownership: RLS is the multi-tenant boundary. The
service-role key (backend-only) bypasses RLS for admin tasks; all per-user access goes through the
anon/publishable key plus the signed-in user's JWT, so PostgREST enforces the policies.

**Config.** Backend (`backend/.env`): `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (secret,
backend-only), `SUPABASE_ANON_KEY`. Frontend (from B1): `NEXT_PUBLIC_SUPABASE_URL`,
`NEXT_PUBLIC_SUPABASE_ANON_KEY` — the anon key is a *publishable* key, safe in the browser because
RLS gates it; the service-role key must **never** be exposed. All are optional for the data-less
MVP paths: with none set, `/api/health/db` reports `"unconfigured"` and the app still runs.

**Applying migrations.** With the [Supabase CLI](https://supabase.com/docs/guides/local-development):
`supabase db push` (linked project) or `supabase migration up` (local stack). The connectivity
probe `GET /api/health/db` (authenticated) confirms the backend can reach the database.

---

## API Reference

> **Auth:** every endpoint except `/api/health` requires `X-Internal-Token: <INTERNAL_API_TOKEN>`
> and returns **401** without it. The browser never sends this directly — it calls same-origin
> Next.js route handlers that attach the token server-side and forward the client IP as
> `X-Forwarded-For` for rate limiting. `/api/chat*` is limited to **20/min per IP + 500/day**.

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Health check (open — Render probe) |
| `/api/health/db` | GET | Supabase connectivity probe → `{"db":"ok"\|"unconfigured"\|"error"}` (authenticated; not on the public health route) |
| `/api/chat` | POST | Send a message; returns the full reply as JSON `{response, session_id}` |
| `/api/chat/stream` | POST | Same body; streams the reply as NDJSON event frames (`status`/`token`/`reset`/`error`). Used by the frontend. |
| `/api/chord/{name}` | GET | Chord fingering data (e.g. `Am`, `G7`) |
| `/api/chords` | GET | All chords |
| `/api/progressions` | GET | All progressions; filter `?genre=blues` or `?key=E` |
| `/api/session/{id}` | DELETE | Clear a session's memory |
| `/api/session/{id}/practice-log` | GET | Session practice history + skill level |

**Chat request body:**

```json
{ "message": "Give me a blues progression in E",
  "session_id": "uuid-v4",
  "context": { "key": "E", "scale": "Major", "skill_level": "beginner" } }
```

---

## Extending the Dataset

**Add a chord** — edit `backend/data/chords.py`. String order is `[E A D G B e]` (low→high), `-1`
muted, `0` open; barre chords add a `barre` key.

```python
"Dm7": { "name": "Dm7", "full_name": "D minor 7th",
         "positions": [-1,-1,0,2,1,1], "fingers": [0,0,0,3,1,2], "base_fret": 1,
         "notes": ["D","A","C","F"], "type": "minor7", "difficulty": "beginner" }
```

**Add a progression** — edit `backend/data/progressions.py`; all keys required.

```python
{ "id": "my-progression", "name": "My Progression Name", "genre": ["rock"], "key": "G",
  "chords": ["G","D","Em","C"], "roman": ["I","V","vi","IV"], "difficulty": "beginner",
  "description": "Where this comes from and why it works.", "feel": "uplifting, driving",
  "tempo_bpm": 120, "tags": ["rock","pop"] }
```

Valid genres: `blues pop rock folk jazz country rnb reggae indie classical`.

---

## Engineering Notes — bugs traced & fixed

Real songs surfaced problems that show how the agent was debugged from `AgentExecutor` traces.
Condensed (each was diagnosed from verbose logs):

1. **Wasted tool calls on song lookups (latency).** The agent "confirmed" real-song chords against
   the internal beginner-only DB and generic-key tool — always dead ends, ~2 s each. Fixed with
   explicit system-prompt guidance to extract chords straight from `find_song_chords`.
2. **Sequential web searches.** `find_song_chords` ran three queries serially (~7 s). Now issued
   concurrently via a `ThreadPoolExecutor`, bounded by the slowest query.
3. **Inferred progressions presented as "the real chords" (grounding).** On fragmentary snippets the
   agent stated unsupported chords confidently. The prompt now requires traceability to the search
   text, hedging when sources are thin, and forbids appending unsupported chords.
4. **Deprecated `ConversationBufferWindowMemory`.** Migrated to `InMemoryChatMessageHistory` with an
   explicit read-time window; history is passed via the `chat_history` prompt variable.
5. **Broken cadence detection.** Roman-numeral patterns were matched as substrings against the
   chord-name string. Rewritten to match on **root motion** (scale degrees relative to the tonic).
6. **Off-tonic progressions mislabelled.** Analysis assumed the first chord was the tonic. Added
   Krumhansl-Schmuckler key finding with an order-aware authentic-cadence bonus.
7. **Truncated `BACKEND_URL` → 502 on every proxied request.** A manually typed `ttps://…` (missing
   `h`) failed the `^https?://` test and got `https://` prepended, yielding an invalid URL. Health
   check still passed (it bypasses the proxy), so it wasn't caught — corrected in the dashboard.
8. **~20 s of blank typing dots, then a burst.** Time-to-first-token: nothing to stream during the
   planning/tool window. Fixed with NDJSON `status` frames (see [streaming](#how-the-agent-works)).
9. **Eval gate flapped on unchanged code.** The runner used production's `temperature=0.7` and an
   unset skill level triggered a clarifying question instead of a chord block. Fixed by pinning
   temperature and the cases' `skill_level`; the gate is now reproducible at 100% on the golden set.

---

## Deployment on Render

Both services deploy as **public Web Services** from one repo via the root `render.yaml` Blueprint.
Security comes from the app design, not the hosting tier: the DeepSeek key stays on the backend,
every token-spending route requires the shared secret, and traffic is rate-limited and CORS-locked.

See **[`RENDER_MIGRATION.md`](./RENDER_MIGRATION.md)** for the full runbook (deploy order, env vars
/ Secret Files, key rotation, incident checklist). Key gotcha: after deploy, verify the frontend's
`BACKEND_URL` is the bare host (set by `fromService`) or starts with `https://` — a manual typo
silently 502s every proxied request while `/api/health` still passes. Observability is optional —
set `OTEL_ENABLED=true` plus the OTLP endpoint/headers (placeholders are in `render.yaml`); leave
them unset and instrumentation stays a no-op.
