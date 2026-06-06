"""
ChordCoach FastAPI backend.
Run: uvicorn main:app --reload --port 8000
"""

import os
import time
import logging
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("chordcoach")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ChordCoach backend starting up")
    if not os.getenv("DEEPSEEK_API_KEY"):
        logger.warning("DEEPSEEK_API_KEY not set — agent calls will fail")
    yield
    logger.info("ChordCoach backend shutting down")


app = FastAPI(
    title="ChordCoach API",
    description="AI-powered guitar chord progression coach",
    version="1.0.0",
    lifespan=lifespan,
)

# ─── CORS ─────────────────────────────────────────────────────────────────────
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url, "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Request logging middleware ────────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = round((time.time() - start) * 1000, 1)
    logger.info(f"{request.method} {request.url.path} → {response.status_code} ({duration}ms)")
    return response


# ─── Pydantic schemas ─────────────────────────────────────────────────────────
class ChatContext(BaseModel):
    key: str = ""
    scale: str = ""


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    context: ChatContext = Field(default_factory=ChatContext)


class ChatResponse(BaseModel):
    response: str
    session_id: str


# ─── Lazy imports (avoid import errors if packages missing at startup) ────────
def _get_agent_modules():
    from agent.coach_agent import run_agent
    from agent.memory import get_memory, clear_memory
    from data.chords import CHORDS, get_chord
    from data.progressions import PROGRESSIONS, get_progressions_by_genre, get_progressions_by_key
    return run_agent, get_memory, clear_memory, CHORDS, get_chord, PROGRESSIONS, get_progressions_by_genre, get_progressions_by_key


# ─── Routes ───────────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise HTTPException(status_code=503, detail="DEEPSEEK_API_KEY not configured on the server.")

    try:
        run_agent, get_memory, _, _, _, _, _, _ = _get_agent_modules()
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Agent modules not available: {e}")

    try:
        memory = get_memory(req.session_id)
        response_text = await run_agent(
            message=req.message,
            memory=memory,
            context=req.context.model_dump(),
        )
        return ChatResponse(response=response_text, session_id=req.session_id)
    except Exception as exc:
        logger.error(f"Agent error for session {req.session_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/chord/{chord_name}")
async def get_chord_endpoint(chord_name: str):
    try:
        _, _, _, _, get_chord, _, _, _ = _get_agent_modules()
    except ImportError as e:
        raise HTTPException(status_code=503, detail=str(e))

    chord = get_chord(chord_name)
    if not chord:
        raise HTTPException(status_code=404, detail=f"Chord '{chord_name}' not found")
    return chord


@app.get("/api/chords")
async def list_chords():
    try:
        _, _, _, CHORDS, _, _, _, _ = _get_agent_modules()
    except ImportError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {
        name: {
            "name": c["name"],
            "full_name": c["full_name"],
            "type": c.get("type", ""),
            "difficulty": c.get("difficulty", ""),
        }
        for name, c in CHORDS.items()
    }


@app.get("/api/progressions")
async def list_progressions(genre: str = "", key: str = ""):
    try:
        _, _, _, _, _, PROGRESSIONS, get_progressions_by_genre, get_progressions_by_key = _get_agent_modules()
    except ImportError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if genre:
        return get_progressions_by_genre(genre)
    if key:
        return get_progressions_by_key(key)
    return PROGRESSIONS


@app.delete("/api/session/{session_id}")
async def clear_session(session_id: str):
    try:
        _, _, clear_memory, _, _, _, _, _ = _get_agent_modules()
    except ImportError as e:
        raise HTTPException(status_code=503, detail=str(e))

    cleared = clear_memory(session_id)
    return {"cleared": cleared}


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
