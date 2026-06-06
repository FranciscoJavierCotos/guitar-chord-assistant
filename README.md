# ChordCoach — AI Guitar Progression Coach

> "Learn the language of music, one chord at a time."

An AI-powered web app that teaches guitar chord progressions through a conversational agent. Ask ChordCoach for progression recommendations, see interactive SVG chord diagrams, and get music theory explanations — all in one warm, studio-dark UI.

---

## Screenshot

```
┌─────────────────────────────────────────────────────┐
│  🎸 ChordCoach          Key: [C ▾]  Scale: [Major ▾]│
├──────────────────────┬──────────────────────────────┤
│  Chat Panel          │  Chord Diagrams               │
│                      │                              │
│  > Give me a blues   │  12-Bar Blues in E           │
│    progression in E  │  ┌────┐ ┌────┐ ┌────┐        │
│                      │  │ E7 │ │ A7 │ │ B7 │        │
│  < Here's a classic  │  └────┘ └────┘ └────┘        │
│    12-bar blues...   │                              │
│                      │  Sequence: E7 → A7 → B7      │
│  [Ask me anything…]  │                              │
└──────────────────────┴──────────────────────────────┘
```

---

## Tech Stack

| Layer     | Technology |
|-----------|------------|
| Backend   | Python 3.11, FastAPI, uvicorn |
| Agent     | LangChain ReAct, Claude claude-sonnet-4-20250514 (via langchain-anthropic) |
| Memory    | ConversationBufferWindowMemory (in-process, k=10) |
| Frontend  | Next.js 14 (App Router), TypeScript, Tailwind CSS |
| Diagrams  | Hand-coded SVG React component |
| Deploy    | Railway (two services) |

---

## Local Development

### Prerequisites
- Python 3.11+
- Node.js 18+
- An [Anthropic API key](https://console.anthropic.com/)

### 1. Clone and enter the project
```bash
git clone <your-repo-url>
cd chord-coach
```

### 2. Set up the backend
```bash
cd backend

# Create and activate a virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Start the backend
uvicorn main:app --reload --port 8000
```

Backend will be live at `http://localhost:8000`. Test it:
```
GET http://localhost:8000/api/health   → {"status":"ok","version":"1.0.0"}
```

### 3. Set up the frontend (new terminal)
```bash
cd frontend

# Install dependencies
npm install

# Configure environment
cp .env.example .env.local
# The default NEXT_PUBLIC_BACKEND_URL=http://localhost:8000 works for local dev

# Start the dev server
npm run dev
```

Frontend will be live at `http://localhost:3000`.

### 4. Test chord diagrams in isolation
Visit `http://localhost:3000/test-chord` to see all chord diagram sizes and types rendered without needing the AI agent.

---

## Architecture

```
Browser
  │
  ├── GET/POST → Next.js frontend (port 3000)
  │     ├── app/page.tsx          — main split layout
  │     ├── components/Chat.tsx   — conversational interface
  │     ├── components/ChordDiagram.tsx  — SVG chord renderer
  │     └── components/ProgressionDisplay.tsx
  │
  └── POST /api/chat → FastAPI backend (port 8000)
        ├── agent/coach_agent.py  — LangChain ReAct agent
        ├── agent/tools.py        — custom tools (chord lookup, theory, etc.)
        ├── agent/memory.py       — session-based ConversationBufferWindowMemory
        ├── data/chords.py        — chord fingering database (40+ chords)
        └── data/progressions.py  — named progressions dataset (30+ entries)
```

**Data flow:**
1. User types a message in the chat UI
2. Frontend sends `POST /api/chat` with `{ message, session_id, context }`
3. FastAPI routes to the LangChain ReAct agent
4. Agent uses tools to look up real chord/progression data
5. Agent responds with markdown + a trailing `\`\`\`json` action block
6. Frontend parses the action block, fetches chord SVG data, and renders diagrams
7. JSON block is stripped from the displayed message text

---

## Deployment on Railway

### One-time setup

1. Create a free account at [railway.app](https://railway.app)
2. Create a **New Project** → **Deploy from GitHub repo**

### Backend service
1. Add a new service, set **Root Directory** to `/chord-coach/backend`
2. Railway auto-detects Python via `railway.toml`
3. Add environment variable: `ANTHROPIC_API_KEY=sk-ant-...`
4. Note the generated Railway URL (e.g. `https://chordcoach-backend.up.railway.app`)

### Frontend service
1. Add another service, set **Root Directory** to `/chord-coach/frontend`
2. Add environment variable: `NEXT_PUBLIC_BACKEND_URL=https://chordcoach-backend.up.railway.app`
3. Railway builds with `npm run build` and serves with `npm start`

Both services use `railway.toml` for build/deploy config — no additional setup needed.

---

## Adding New Chords

Edit `backend/data/chords.py` and add an entry following this pattern:

```python
"Dm7": {
    "name": "Dm7",
    "full_name": "D minor 7th",
    "positions": [-1, -1, 0, 2, 1, 1],  # [E, A, D, G, B, e] — -1=muted, 0=open
    "fingers":   [0,   0, 0, 3, 1, 2],  # 0=open/muted, 1–4=finger
    "base_fret": 1,
    "notes": ["D", "A", "C", "F"],
    "type": "minor7",          # major, minor, dominant7, major7, minor7, power, etc.
    "difficulty": "beginner",  # beginner, intermediate, advanced
}
```

**Finding finger positions:** Use standard guitar TAB notation where string order is `[E A D G B e]` (low to high) and values are fret numbers.

---

## Adding New Progressions

Edit `backend/data/progressions.py` and append to the `PROGRESSIONS` list:

```python
{
    "id": "my-progression-unique-id",
    "name": "My Progression Name",
    "genre": ["rock"],           # list — can appear in multiple genres
    "key": "G",
    "chords": ["G", "D", "Em", "C"],
    "roman": ["I", "V", "vi", "IV"],
    "difficulty": "beginner",
    "description": "A description of where this progression comes from and why it works.",
    "feel": "uplifting, driving",
    "tempo_bpm": 120,
    "tags": ["rock", "pop", "beginner-friendly"],
}
```

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/chat` | POST | Send a message to the AI agent |
| `/api/chord/{name}` | GET | Get chord data by name (e.g. `Am`, `G7`) |
| `/api/chords` | GET | List all chords in the database |
| `/api/progressions` | GET | List progressions (filter with `?genre=blues` or `?key=E`) |
| `/api/session/{id}` | DELETE | Clear a session's conversation memory |
