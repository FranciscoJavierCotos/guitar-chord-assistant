# ChordCoach

AI-powered guitar coaching web app. Users ask natural-language questions in a chat; a LangChain
agent answers with chord progressions, music theory, and finger placement. Each chord-display
reply ends with a fenced ` ```json ` `AgentAction` block that the frontend parses to render SVG
chord diagrams. Two independent services: `backend/` (FastAPI) and `frontend/` (Next.js).

## Workflow rules (always follow)

- **Bug fix or feature:** use the `github-flow` skill FIRST to open a GitHub issue before writing
  code. Never push to `main` — branch and open a PR.
- **After** a fix/feature: use the `testing` skill to add tests (a regression test for bugs)
  before opening the PR.
- If no CI runs the tests, use the `ci-cd-pipelines` skill.
- **Document every change** in the Obsidian vault (see *Engineering journal* below): create or
  update the change's page and keep the database index in sync — in the same change, before the PR.
- **Ship it (CI-gated auto-merge — low human review):** once the PR is open, enable GitHub
  auto-merge so it merges and deletes its branch automatically **after all required checks pass**:
  `gh pr merge <#> --auto --squash --delete-branch`. The security + test gates **are** the review —
  GitHub forbids approving your own PR, so never merge before CI is green and never bypass branch
  protection. If a check is red, fix it; don't override. After it merges, flip the Obsidian page +
  `_Database.md` row to `done` and fill in the PR link.

## Keep docs in sync (same change, never a follow-up)

Two living docs, kept consistent with each other:
- `.claude/CLAUDE.md` (this file) — agent-facing source of truth.
- `README.md` — the single human-facing README. Do **not** create per-service READMEs.

Update both **in the same change** when a change touches any of these. New env vars also go in the
relevant `.env.example`; notable diagnosed bugs get an entry in README's *Issues Encountered*.

| Trigger | Update |
| --- | --- |
| Endpoint added/removed/renamed or request/response shape changes | README API Reference + this file's Architecture / Key Files |
| DB / persistence / external session store introduced | Schema + config + migrations in both; revisit *Out of Scope* / *Do-Don't* (MVP assumes no DB) |
| Chord/progression record shape changes | README *Extending the Dataset*, *Code Conventions* here, and `frontend/lib/types.ts` |
| `AgentAction` / `show_chords` JSON contract changes | README *Structured Output Protocol* + *Do-Don't* note here |
| Tool added/removed/repurposed, or agent type/model/iteration cap changes | Tool count + descriptions in both |
| Major dependency / runtime / LLM provider changes | *Tech Stack* in both |
| Commands / ports / env vars / `render.yaml` change | *Build & Run* + *Environment* here, README *Local Development* / *Deployment* |
| New service or top-level directory | *Architecture* tree in both |

Routine bug fixes, internal refactors, and copy tweaks need no doc update. Litmus test: "would a
new contributor reading the docs now be misled?"

## Engineering journal (Obsidian vault)

A running log of **what was built**, separate from the living docs above. Lives in the Obsidian
vault at `C:\Users\franc\Documents\Obsidian\Vault\ChordCoach` (outside the repo — not committed).
Every bug fix, feature, refactor, chore, or docs change gets **its own page**; a master index page
tracks pending issues.

**Structure**
- `ChordCoach/_Database.md` — master index. Two tables (**Pending / in progress** and **Done**) plus
  optional Dataview blocks. This is the page to open to see outstanding work.
- `ChordCoach/Changes/` — one page per change, named `YYYY-MM-DD-<type>-<slug>.md` (e.g.
  `2026-06-22-bug-stream-preamble-leak.md`). `type` ∈ `bug | feature | refactor | chore | docs`.
- `ChordCoach/Templates/Change.md` — the page template (frontmatter: `title`, `type`, `status`,
  `issue`, `pr`, `branch`, `created`, `updated`, `tags`). `status` ∈ `pending | in-progress | done`.

**When (same change, before the PR — like the docs rule above)**
1. **Starting** a fix/feature/refactor: copy `Templates/Change.md` into `Changes/` with a dated
   slug, fill `status: in-progress`, link the GitHub issue, and add a **Pending / in progress** row
   to `_Database.md`.
2. **Finishing** (PR opened/merged): fill in the PR link, flip `status: done`, bump `updated`, and
   move the row from the Pending table to the **Done** table in `_Database.md`.

Keep each change page's frontmatter `status` and the `_Database.md` tables consistent — the
frontmatter is the source of truth; the tables (and Dataview blocks) are the human view. Use
absolute dates (today is resolvable from context). This journal records *narrative* (problem,
decisions, outcome); it does not replace updating `README.md` / this file per the table above.

## Architecture

```
backend/            FastAPI app — entry point: main.py
  agent/
    coach_agent.py  builds + runs the LangChain AgentExecutor (run_agent + run_agent_stream)
    tools.py        14 @tool functions (chord lookup, theory, RAG retrieval, web search, practice log)
    memory.py       in-process session store (dict, auto-expires after 2 h)
  data/
    chords.py       static dict of 40+ chord fingerings
    progressions.py static list of 30+ named progressions
  db.py             Supabase client (service-role + per-user RLS) + connectivity check
  auth.py           Supabase user-JWT verification (asymmetric JWKS) — get_current_user (B1)
  eval/             offline agent eval harness (python -m eval)
  rag/              RAG corpus + ingestion + retrieval (Epic C — python -m rag, C0/C1)
    corpus/         12 hand-authored music-theory markdown notes (source of truth for kb_chunks)
    chunking.py     parse_corpus_file: frontmatter + heading/paragraph chunking
    embeddings.py   embed_texts: Gemini gemini-embedding-001, 768-dim, manual L2 norm
    ingest.py       chunk -> embed -> delete-then-insert per source -> prune orphans
    retrieval.py    search_corpus: embed query -> match_kb_chunks RPC -> top-k chunks (C1)
  observability.py  opt-in OpenTelemetry setup + agent/tool spans & metrics
  main.py           CORS, auth, rate limiting, request logging, all routes
supabase/
  migrations/       versioned SQL schema (Epic B/C): profiles, conversations, messages,
                    practice_events, kb_chunks + pgvector + RLS baseline
observability/      reproducible Grafana dashboard JSON + runbook
frontend/           Next.js 14 App Router app
  app/page.tsx      root layout — splits Chat (55%) and ChordDiagram (45%) panels
  app/api/          same-origin route handlers (chat proxy + catch-all backend proxy)
  app/login,signup,reset-password,update-password,account/  auth pages (B1)
  app/auth/         callback (PKCE code exchange) + signout route handlers (B1)
  components/        Chat, ChordDiagram, ProgressionDisplay, AuthForm, AuthNav, etc.
  lib/supabase/     browser + server + middleware Supabase clients, env, token (B1)
  lib/types.ts      shared TypeScript interfaces (ChordPosition, AgentAction, etc.)
```

**Security (backend is public-facing).** Every `/api/*` route except `/api/health` requires header
`X-Internal-Token == INTERNAL_API_TOKEN` (401 otherwise). `/api/chat` + `/api/chat/stream` are
rate-limited (`20/min` per IP + global `500/day` via `slowapi`). CORS locked to `FRONTEND_URL`;
interactive docs disabled when `ENV=production`; 16 KB request-body ceiling. The DeepSeek key never
leaves the backend.

**Frontend never calls the backend directly.** The browser only hits same-origin Next.js route
handlers (`app/api/chat/route.ts`, catch-all `app/api/backend/[...path]/route.ts`), which attach
the server-only `X-Internal-Token` and forward client IP as `X-Forwarded-For` via
`lib/serverBackend.ts`, then proxy to `BACKEND_URL`. There is no `next.config` rewrite — a rewrite
can't inject the secret header. When a user is signed in, the proxy also reads their Supabase access
token server-side (`lib/supabase/server.ts`, httpOnly cookies) and forwards it as `Authorization:
Bearer …` (`bearerHeader`) so authenticated backend routes act on the real user; anonymous → no header.

**Auth & user identity (Epic B — B1, #26).** Accounts use Supabase Auth (email/password + email
confirmation; password reset). The session lives in **httpOnly cookies** via `@supabase/ssr` (token
never in client JS); `middleware.ts` refreshes it on every request. Identity reaches the backend as a
Bearer token through the proxy, and `backend/auth.py` (`get_current_user`) **cryptographically
verifies** it against the project's **public JWKS** (`<SUPABASE_URL>/auth/v1/.well-known/jwks.json`):
asymmetric algs only (ES256/RS256/EdDSA — **never HS256**, to block alg-confusion), plus `iss`/`aud`/
`exp` checks. No JWT secret is stored backend-side. **Three independent layers** gate a user route:
proxy shared secret **and** verified JWT **and** Postgres RLS. **Chat stays anonymous**; account-scoped
pages (e.g. `/account`, and history/dashboard in later stories) require sign-in (server-side
`getUser()` guard → redirect to `/login`). The `profiles` row is auto-created by the B0
`on_auth_user_created` trigger on first sign-up. Browser→Supabase calls require the project origin in
the CSP `connect-src` (`next.config.mjs`, derived from `NEXT_PUBLIC_SUPABASE_URL`).

**Data layer (Epic B — Supabase).** Durable accounts + practice history live in Supabase (Postgres
+ Auth + RLS); `pgvector` is enabled for Epic C (RAG). Schema is migration-driven under
`supabase/migrations/` (story B0): tables `profiles`, `conversations`, `messages`, `practice_events`,
each with **RLS enabled + owner-only policies** on `auth.uid()` (`messages` derives ownership from
its parent conversation). `backend/db.py` exposes a service-role client (RLS-bypassing, backend-only)
and a per-user client (anon key + user JWT, RLS-enforced). All `SUPABASE_*` env is optional: unset →
`/api/health/db` reports `"unconfigured"` and the app still runs on the in-process paths. **Never**
expose `SUPABASE_SERVICE_ROLE_KEY` to the browser; the anon/publishable key is browser-safe (RLS
gates it). When persisting/reading user data, go through RLS — don't trust the client for ownership.

**RAG corpus (Epic C — story C0, #30).** `public.kb_chunks` (migration
`20260630223312_c0_kb_embeddings.sql`) holds the curated music-theory corpus the retrieval tool (C1)
searches over — `vector(768)` embeddings via `extensions.vector`, an HNSW cosine index, chunk
text, and `source`/`title`/`url` for citation rendering. Unlike every other table here, it is
**shared reference data, not per-user data**, so its RLS shape is deliberately public-read /
service-role-write rather than owner-scoped on `auth.uid()`: RLS is enabled with only a
`select using (true)` policy, and no insert/update/delete policy exists, so only the service-role
key (used exclusively by `python -m rag`) can ever write it. `backend/rag/ingest.py` populates it by
chunking `backend/rag/corpus/*.md`, embedding via Gemini (`backend/rag/embeddings.py`), and
upserting idempotently (delete-and-reinsert per `source`, then orphan pruning). Embedding the full
~25-40-chunk corpus costs well under $0.01 at Gemini's $0.15/1M-token rate — re-running ingestion
after a corpus edit is effectively free.

**RAG retrieval tool (Epic C — story C1, #31).** `search_music_theory` (`agent/tools.py`, backed by
`backend/rag/retrieval.py::search_corpus`) embeds the user's query with the same `embed_texts`
helper C0 ingestion uses — so query and corpus vectors can never drift on model/dimension/
normalization — then calls the `match_kb_chunks` Postgres RPC (migration
`20260701185136_c1_match_kb_chunks.sql`) to rank `kb_chunks` by cosine similarity. A dedicated RPC
exists because PostgREST's table query builder can't express pgvector's `<=>` operator or an
`ORDER BY` on it; the function is `stable`, `search_path`-pinned, and grantable to `anon` /
`authenticated` / `service_role` since it only reads the already-public `kb_chunks` table. The tool
runs through the service-role client (same as ingestion) because retrieval must work for anonymous
chat sessions too. The system prompt (`coach_agent.py`) directs the agent to call this tool for
conceptual theory questions (not for analyzing a specific progression — that's still
`explain_theory`) and ground its answer in the returned passages.

**Endpoints.** `POST /api/chat` returns the full reply as JSON. `POST /api/chat/stream` (used by
the frontend) returns a chunked `text/plain` stream of **NDJSON frames** (one JSON object per line).
`GET /api/health/db` (authenticated) is a Supabase connectivity probe, kept off the public
`/api/health` so a DB outage never fails Render's platform check. `GET /api/me` (B1) returns the
signed-in user's own profile: it requires **both** the proxy token **and** a verified Supabase user
JWT (`get_current_user`), and reads through the RLS-scoped client — the end-to-end proof that user
identity propagates browser → proxy → backend → RLS.
Both chat routes share request body, auth, and rate limits. `run_agent_stream` (via `AgentExecutor.astream_events`)
emits four frame types — changing them requires updating `Chat.tsx`'s line parser:
- `{"type":"status","label":…}` — immediate `"Thinking…"` + a per-tool label per `on_tool_start` (`TOOL_STATUS_LABELS`)
- `{"type":"token","text":…}` — final-answer content deltas (including the trailing `show_chords`/`show_chord` JSON block; client reassembles + parses it on stream end)
- `{"type":"reset"}` — discard text streamed so far (see below)
- `{"type":"error","message":…}` — on failure, emitted by the route

**Only the final answer streams.** Each agent planning iteration is a separate model run, and
DeepSeek emits a conversational preamble *alongside* the tool call. `run_agent_stream` tracks the
run via `run_id`: when a new run starts producing content it drops the previous run's text (a
preamble) and emits `reset` so the client clears it; the last content run is the real answer. This
also keeps history clean (preambles are no longer persisted and replayed).

**Structured output contract.** Every chord-display reply ends with a fenced ` ```json ` block
holding an `AgentAction` object. The frontend strips it from the displayed message and uses it to
fetch chord SVG data. Changing the `AgentAction` schema requires updating `agent/coach_agent.py`
(system prompt) **and** `frontend/lib/types.ts` together. Breaking this breaks the chord panel.

**Observability** (`backend/observability.py`, OpenTelemetry). **Opt-in, no-op** unless
`OTEL_ENABLED=true` *and* an OTLP endpoint are set — manual instrumentation goes through the OTel
*API* (no-ops without an SDK provider), so local dev/CI/tests run unchanged. When enabled,
`setup_observability(app)` (from `main.py`) installs OTLP/HTTP exporters, auto-instruments FastAPI,
and emits an `agent.run` span with child `tool.<name>` spans plus metrics (agent/tool latency,
per-tool call counts, DeepSeek token usage + estimated cost, streaming TTFT, rate-limit 429s) to
Grafana Cloud (Tempo + Mimir). **Never** put secrets, request/response bodies, or auth headers in
span attributes/metric labels; keep labels low-cardinality (no session-id/IP). Dashboards + runbook
in `observability/`.

## Tech Stack

| Layer | Technology |
| --- | --- |
| Backend runtime | Python 3.12 (pinned `.python-version`), FastAPI 0.115.0, uvicorn 0.30.6 |
| Agent | LangChain 0.3.x, `create_tool_calling_agent`, `AgentExecutor` |
| LLM | DeepSeek (`deepseek-chat` via `langchain-openai` → `api.deepseek.com/v1`) |
| Web search tool | DuckDuckGo via `langchain-community` (`DuckDuckGoSearchRun`) |
| Session memory | `ConversationBufferWindowMemory` k=10, in-process Python dict |
| Persistence & auth | Supabase (Postgres + Auth + RLS) + `pgvector`; versioned SQL migrations (Epic B) — `supabase-py` client |
| Auth (frontend) | Supabase Auth via `@supabase/ssr` (httpOnly-cookie sessions) + `@supabase/supabase-js` |
| Auth (backend) | `PyJWT[crypto]` — verifies the Supabase user JWT against the project's public JWKS (asymmetric) |
| Embeddings | Google Gemini (`gemini-embedding-001` via `google-genai`), 768-dim — RAG corpus ingestion (C0) + query embeddings (C1) |
| Frontend | Next.js 14.2.15, React 18 (Node ≥20), TypeScript 5 (strict), Tailwind CSS 3.4.1 |
| Markdown render | `react-markdown` + `remark-gfm` |
| API hardening | `slowapi` rate limiting + shared-secret (`X-Internal-Token`) auth + verified user JWT (B1) |
| Observability | OpenTelemetry (SDK + OTLP/HTTP exporter + FastAPI auto-instr.) → Grafana Cloud (opt-in) |
| Deploy | Render — two public Web Services via `render.yaml` Blueprint at repo root |

## Build & Run

**Backend** (from `backend/`):
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # add DEEPSEEK_API_KEY + INTERNAL_API_TOKEN
uvicorn main:app --reload --port 8000
```
Health: `GET http://localhost:8000/api/health` → `{"status":"ok","version":"1.0.0"}`

**Frontend** (from `frontend/`):
```bash
npm install
cp .env.example .env.local      # BACKEND_URL + INTERNAL_API_TOKEN (must match backend)
npm run dev                      # http://localhost:3000
npm run build && npm start       # production build
npm run lint                     # ESLint
```
Isolated chord-diagram test page (no backend): `http://localhost:3000/test-chord`

## Testing

CI runs both suites on every PR and push to `main` via `.github/workflows/ci.yml` (two
path-filtered functional jobs + two always-on **security gates** + a final `ci` aggregator to
require in branch protection). Security gates (both gate the `ci` aggregator and so block merge):
- **`secrets`** — `gitleaks` secret-leak scan (license-free CLI, full history, `--redact`) using
  repo-specific rules in `.gitleaks.toml` (`DEEPSEEK_API_KEY`, `INTERNAL_API_TOKEN`, OTEL auth
  header; `.env.example` + test fixtures allowlisted).
- **`codeql`** — SAST over `python` + `javascript-typescript` (`security-and-quality` queries).
Auto-merge waits on the `ci` check: the repo allows auto-merge + delete-branch-on-merge and
requires `ci` on `main` (set once via `gh repo edit --enable-auto-merge --delete-branch-on-merge`
and a `branches/main/protection` rule requiring the `ci` context). Dependency auditing
(pip-audit / npm audit) was intentionally left out to avoid blocking PRs on upstream advisories.

- **Backend** — pytest. From `backend/`: `pip install -r requirements-dev.txt` then `pytest -q`.
  Covers API routes, the theory engine, session memory, and chord/progression data integrity.
  `conftest.py` puts `backend/` on `sys.path` so `import agent.…` works from any cwd.
- **Frontend** — Vitest (`npm test` / `test:watch` / `test:coverage` from `frontend/`). Pure logic
  lives in `lib/` so it's testable without React: `lib/agentAction.ts` (the trailing-JSON
  `AgentAction` parser), `lib/streamFrames.ts` (NDJSON frame reassembly), `lib/serverBackend.ts`
  (token/URL helpers incl. `bearerHeader`), `lib/supabase/env.ts` (`supabaseConfigured`). `Chat.tsx`
  imports the first two — keep that split. CI runs `npx tsc --noEmit` + `npm test` (not `next lint`).
- **Backend auth (B1)** — `tests/test_auth.py` covers JWT verification against a generated keypair +
  stubbed JWKS (valid / expired / wrong aud / wrong iss / bad-signature / **HS256-rejected** /
  missing-sub / unconfigured); `tests/test_api.py::TestMe` drives `/api/me` (both auth gates, profile
  read, unconfigured-503) via a `get_current_user` dependency override. No network/DeepSeek key needed.

**Offline agent eval** (`backend/eval/`) — evaluates the agent's actual answer quality.
- `python -m eval` runs a golden set (`eval/cases/*.yaml`, 20 cases) through the real agent at a
  **pinned temperature** (0 default, `EVAL_AGENT_TEMPERATURE`) — not production's 0.7 — so the gate
  is reproducible. `run_agent` / `build_agent_executor` take an optional `temperature`; production
  callers omit it (keep `DEFAULT_AGENT_TEMPERATURE`). Fingering cases pin a `skill_level` so the
  agent answers directly instead of asking the user's level.
- **Deterministic graders** (`eval/graders/deterministic.py`, no LLM/network): valid `AgentAction`,
  no hallucinated chords (cross-checked vs `data/chords.py`), named progressions resolve,
  key/chord-count adherence. `eval/schema.py` mirrors `frontend/lib/types.ts` + `lib/agentAction.ts`
  — keep all three in sync with the `AgentAction` contract.
- **LLM-as-judge** (`eval/graders/judge.py`): subjective dimensions, 1–5 per per-case rubric; judge
  model via `EVAL_JUDGE_MODEL` / `EVAL_JUDGE_BASE_URL` / `EVAL_JUDGE_API_KEY` (defaults to DeepSeek).
- **Report + gate** — writes `eval/reports/report.json` (gitignored); exits non-zero below
  `--threshold` / `--judge-threshold`. Cases the agent never answered (bad key, network, outage —
  `AGENT_ERROR_PREFIX` fallback) are reported as **errored**, excluded from content metrics, and
  abort with **exit code 2** (distinct from content-threshold exit 1).
- **CI gating** — deterministic graders run on **every PR** (offline) via `tests/test_eval.py` in
  the `backend` job; the **full agent+judge eval** runs **only on manual `workflow_dispatch`** (the
  `eval` job; makes real DeepSeek calls, needs `DEEPSEEK_API_KEY`). Add a case by dropping a file in
  `eval/cases/`; `tests/test_eval.py` validates it's well-formed and its `chord_ids` exist.

Manual smoke: `/test-chord` for diagram rendering; chat a progression request to confirm the panel
updates; hit `GET /api/health`, `/api/chords`, `/api/progressions` after `data/` changes.

## Code Conventions

**Backend**
- New tools: `@tool` from `langchain_core.tools`, then register in the `TOOLS` list at the bottom of
  `agent/tools.py` — the agent won't see it otherwise.
- New chords (`data/chords.py`): `positions` = `[E, A, D, G, B, e]`, `-1` = muted, `0` = open.
- New progressions (`data/progressions.py`) require all keys: `id`, `name`, `genre` (list), `key`,
  `chords`, `roman`, `difficulty`, `description`, `feel`, `tempo_bpm`, `tags`.

**Frontend**
- TypeScript strict — no `any`, no unchecked nulls.
- Path alias `@/` → `frontend/` root (`tsconfig.json`).
- Use Tailwind custom tokens (`bg-primary`, `accent-orange`, …) from `tailwind.config.ts`, not raw hex.
- Fonts: `font-display` (Playfair Display), `font-body` (DM Sans), `font-mono` (JetBrains Mono).

## Key Files

| Path | Purpose |
| --- | --- |
| `backend/main.py` | FastAPI app, CORS, auth, rate limiting, all routes |
| `backend/agent/coach_agent.py` | LLM setup, system prompt, `run_agent` / `run_agent_stream` |
| `backend/agent/tools.py` | All 14 LangChain tools + music-theory helpers |
| `backend/agent/memory.py` | In-process session store, TTL eviction |
| `backend/db.py` | Supabase client (service-role + per-user RLS) + `check_connectivity` + `get_own_profile` |
| `backend/auth.py` | Supabase user-JWT verification (asymmetric JWKS) — `get_current_user` dependency (B1) |
| `supabase/migrations/` | Versioned SQL schema: tables, pgvector, RLS policies (Epic B/C) |
| `backend/rag/ingest.py` | `python -m rag` pipeline: chunk -> embed -> delete-then-insert -> prune orphans (C0) |
| `backend/rag/embeddings.py` | `embed_texts()` — Gemini `gemini-embedding-001`, 768-dim, manual L2 normalization (C0) |
| `backend/rag/retrieval.py` | `search_corpus()` — embed query -> `match_kb_chunks` RPC -> top-k chunks with citations (C1) |
| `backend/observability.py` | Opt-in OpenTelemetry: SDK/OTLP setup, spans, RED + domain metrics |
| `backend/data/chords.py` | Chord fingering database |
| `backend/data/progressions.py` | Progression dataset |
| `backend/.env.example` | Canonical list of backend env vars |
| `observability/dashboard.json` | Grafana deep-dive dashboard (runbook in `observability/README.md`) |
| `observability/dashboard-kpi.json` | Grafana KPI-overview dashboard (free-tier stat tiles) |
| `frontend/app/page.tsx` | Root layout — panel split |
| `frontend/components/ChordDiagram.tsx` | SVG chord renderer |
| `frontend/lib/types.ts` | All shared TypeScript interfaces |
| `frontend/lib/serverBackend.ts` | Server-only: injects `X-Internal-Token` + client IP + `bearerHeader`, resolves `BACKEND_URL` |
| `frontend/lib/supabase/` | Supabase clients: `client.ts` (browser), `server.ts` (cookies + `getUserAccessToken`), `middleware.ts` (session refresh), `env.ts` |
| `frontend/components/AuthForm.tsx`, `AuthNav.tsx` | Sign-in/up form + header session control (B1) |
| `frontend/app/auth/callback/route.ts` | PKCE code exchange for email-confirm / password-reset links (B1) |
| `frontend/app/account/page.tsx` | Auth-gated page (server `getUser()` guard) proving backend identity (B1) |
| `frontend/app/api/chat/route.ts` | Proxies `POST` to backend `/api/chat/stream`, pipes the stream back |
| `frontend/app/api/backend/[...path]/route.ts` | Catch-all proxy for other backend GET/DELETE routes |
| `frontend/middleware.ts` | Per-IP edge rate limit for `/api/*` + Supabase session refresh (B1) |
| `frontend/next.config.mjs` | Security headers (CSP, HSTS, …); no rewrite |
| `render.yaml` | Render Blueprint for both services (repo root) |
| `RENDER_MIGRATION.md` | Deploy runbook + key-rotation / incident procedures |

## Environment

**Backend** (`backend/.env`):

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `DEEPSEEK_API_KEY` | Yes | — | Backend 503s without it. Backend-only; never returned/logged. |
| `INTERNAL_API_TOKEN` | Yes | — | Shared secret; authed routes 503 if unset, 401 on mismatch. Render `generateValue: true`. |
| `SUPABASE_URL` | No* | — | Supabase project URL. *Required once persistence/auth (Epic B) is used; unset → `/api/health/db` = `unconfigured`. |
| `SUPABASE_SERVICE_ROLE_KEY` | No* | — | **Secret, RLS-bypassing, backend-only.** Never returned/logged/`NEXT_PUBLIC_`. Powers `db.get_service_client`. |
| `SUPABASE_ANON_KEY` | No* | — | Publishable key (browser-safe; RLS gates it). Per-user RLS-enforced client (`db.get_user_client`). |
| `GEMINI_API_KEY` | No* | — | Google AI Studio key. *Required to run `python -m rag` (ingestion, C0) or the (future) retrieval tool (C1); unconfigured otherwise. Never returned/logged. |

No new backend var for B1 auth: `backend/auth.py` derives the JWKS URL from `SUPABASE_URL` and uses the **public** keys, so there is **no** JWT signing secret to store backend-side.
| `ENV` | No | `development` | `production` disables docs + drops localhost from CORS. |
| `PORT` | No | 8000 | Set automatically by Render. |
| `FRONTEND_URL` | No | `http://localhost:3000` | Allowed CORS origin (localhost added only in development). |
| `OTEL_ENABLED` | No | off | `true` turns on OTel export. Also needs an OTLP endpoint; otherwise a full no-op. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | No | — | Grafana Cloud OTLP/HTTP gateway URL (`.../otlp`). Never logged. |
| `OTEL_EXPORTER_OTLP_HEADERS` | No | — | `Authorization=Basic <base64(instanceID:token)>`. Secret — never logged/returned. |
| `OTEL_SERVICE_NAME` | No | `chordcoach-backend` | Service name on traces/metrics. |
| `DEEPSEEK_INPUT_COST_PER_MTOK` | No | `0.27` | $/1M input tokens for the cost-estimate metric. |
| `DEEPSEEK_OUTPUT_COST_PER_MTOK` | No | `1.10` | $/1M output tokens for the cost-estimate metric. |

**Frontend** (`frontend/.env.local`) — `BACKEND_URL` + `INTERNAL_API_TOKEN` are **server-only** (no
`NEXT_PUBLIC_` prefix); the two `NEXT_PUBLIC_SUPABASE_*` keys are intentionally public (see below):

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `BACKEND_URL` | No | `http://localhost:8000` | Backend base URL for proxy calls. On Render via `fromService` (bare host; `https://` prepended). |
| `INTERNAL_API_TOKEN` | Yes | — | Must match the backend; attached as `X-Internal-Token` by the route handlers. |
| `NEXT_PUBLIC_SUPABASE_URL` | No* | — | Supabase project URL for browser-side Auth (B1). Unset → auth UI hides + middleware session refresh no-ops; chat still works. |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | No* | — | Publishable Supabase key (B1). The **one allowed** `NEXT_PUBLIC_` key — designed to be public and gated by RLS. |

Never commit `.env` / `.env.local`. Never give a secret a `NEXT_PUBLIC_` prefix — those ship to the
browser. The lone exception is the Supabase **anon/publishable** key, which is a public key by design
(RLS is the boundary); the Supabase **service-role** key is a real secret and stays backend-only.

## Do / Don't

- **Do** use `DEEPSEEK_API_KEY`, not `ANTHROPIC_API_KEY` — the code uses DeepSeek via
  `langchain-openai` with `base_url="https://api.deepseek.com/v1"`.
- **Do** keep secrets (`DEEPSEEK_API_KEY`, `INTERNAL_API_TOKEN`) server-side only — never
  `NEXT_PUBLIC_`-prefix, return in a response, or log request bodies/headers.
- **Do** call the backend from the browser only through the same-origin route handlers; new
  server→backend calls go through `lib/serverBackend.ts`.
- **Do** keep `/api/health` unauthenticated (Render health check) and add
  `Depends(require_internal_token)` to any new `/api/*` route.
- **Do** keep the `AgentAction` JSON block format intact (see *Structured output contract*).
- **Do** persist user data through Supabase + RLS (Epic B): go through `backend/db.py`, keep
  `SUPABASE_SERVICE_ROLE_KEY` backend-only, and rely on RLS for ownership — never trust the client.
  Schema changes are versioned migrations under `supabase/migrations/`, applied in order.
- **Do** gate any backend route that acts on a specific user with `Depends(get_current_user)` (B1)
  **in addition to** `require_internal_token`, then read/write via the RLS-scoped client with that
  user's `access_token`. Don't take a user id from the request body/query — derive it from the
  verified JWT. Keep the session in httpOnly cookies and forward it via the proxy (`bearerHeader`),
  never expose the access token to client JS, and never accept HS256 in JWT verification.
- **Don't** add a *different* database or session store — Epic B standardized on Supabase Postgres
  (this reverses the old MVP "no DB" stance). Agent chat memory is still the in-process dict until
  the B2 story migrates it; don't assume conversations persist before then.
- **Don't** expand CORS origins beyond `FRONTEND_URL` (+ localhost in dev) without discussion.
- **Don't** add a tool without registering it in `TOOLS`, or a backend env var without adding it to
  `.env.example` and this file.
- **Don't** change `render.yaml` without confirming live-service impact; keep `RENDER_MIGRATION.md`
  in sync.
- **Don't** change chord/progression schemas (field names, types) without updating both the Python
  data files and `frontend/lib/types.ts` in the same change.
