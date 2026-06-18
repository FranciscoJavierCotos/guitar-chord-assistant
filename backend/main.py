"""
ChordCoach FastAPI backend.
Run: uvicorn main:app --reload --port 8000

Security model (the backend is deployed on a PUBLIC URL):
- Every token-spending / data route requires the shared-secret header X-Internal-Token,
  which must equal env INTERNAL_API_TOKEN. The Next.js server attaches it; the browser
  never sees it. /api/health stays open so Render's health check works.
- Rate limiting (slowapi) keyed on the real client IP (X-Forwarded-For) protects the
  DeepSeek bill even on an authorized path.
- CORS is locked to FRONTEND_URL (localhost only when ENV=development).
- Interactive docs are disabled in production.
- A request-size ceiling rejects oversized payloads.
"""

import os
import time
import logging
import secrets
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("chordcoach")

ENV = os.getenv("ENV", "development").lower()
IS_PROD = ENV == "production"

# Max request body size (bytes). ChatRequest.message is already capped at 2000 chars;
# this is a cheap outer guard against oversized payloads.
MAX_BODY_BYTES = 16 * 1024  # 16 KB


# ─── Shared-secret auth ────────────────────────────────────────────────────────
def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    """Reject any request whose X-Internal-Token header does not match
    INTERNAL_API_TOKEN. Constant-time compare to avoid timing leaks."""
    expected = os.getenv("INTERNAL_API_TOKEN")
    if not expected:
        # Fail closed: if the server has no token configured, no caller can be authorized.
        logger.error("INTERNAL_API_TOKEN not configured — rejecting authenticated request")
        raise HTTPException(status_code=503, detail="Server auth not configured.")
    if not x_internal_token or not secrets.compare_digest(x_internal_token, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing internal token.")


# ─── Rate limiting ─────────────────────────────────────────────────────────────
def client_ip(request: Request) -> str:
    """Real client IP for rate limiting. The Next.js proxy forwards the browser's
    IP as X-Forwarded-For; Render's edge also sets it. Fall back to the socket peer."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # X-Forwarded-For: client, proxy1, proxy2 — the first entry is the real client.
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=client_ip)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ChordCoach backend starting up (ENV=%s)", ENV)
    if not os.getenv("DEEPSEEK_API_KEY"):
        logger.warning("DEEPSEEK_API_KEY not set — agent calls will fail")
    if not os.getenv("INTERNAL_API_TOKEN"):
        logger.warning("INTERNAL_API_TOKEN not set — authenticated routes will 503")
    yield
    logger.info("ChordCoach backend shutting down")


# Disable interactive docs / schema in production to shrink the attack surface.
_docs_kwargs = {"docs_url": None, "redoc_url": None, "openapi_url": None} if IS_PROD else {}

app = FastAPI(
    title="ChordCoach API",
    description="AI-powered guitar chord progression coach",
    version="1.0.0",
    lifespan=lifespan,
    **_docs_kwargs,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ─── CORS ─────────────────────────────────────────────────────────────────────
# Browser traffic goes through the Next.js server (same-origin), so CORS is a
# defence-in-depth lock rather than the primary control. Only the production
# frontend origin is allowed; localhost is permitted only in development.
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
allowed_origins = [frontend_url]
if not IS_PROD:
    allowed_origins += ["http://localhost:3000", "http://127.0.0.1:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Internal-Token"],
)


# ─── Request-size limit ────────────────────────────────────────────────────────
@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                return JSONResponse(status_code=413, content={"detail": "Request body too large."})
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length."})
    return await call_next(request)


# ─── Request logging middleware ────────────────────────────────────────────────
# Logs only method, path, status and duration — never bodies or headers, so no
# secret (DeepSeek key, internal token) can leak into Render logs.
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
    skill_level: str = ""


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
    from agent.memory import get_history, clear_memory
    from data.chords import CHORDS, get_chord
    from data.progressions import PROGRESSIONS, get_progressions_by_genre, get_progressions_by_key
    return run_agent, get_history, clear_memory, CHORDS, get_chord, PROGRESSIONS, get_progressions_by_genre, get_progressions_by_key


# ─── Routes ───────────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    """Unauthenticated — Render's health check hits this. Returns no secrets."""
    return {"status": "ok", "version": "1.0.0"}


@app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(require_internal_token)])
@limiter.limit("20/minute")  # per real client IP
@limiter.limit("500/day", key_func=lambda: "global")  # global cap to protect the DeepSeek bill
async def chat(request: Request, req: ChatRequest):
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise HTTPException(status_code=503, detail="DEEPSEEK_API_KEY not configured on the server.")

    try:
        run_agent, get_history, _, _, _, _, _, _ = _get_agent_modules()
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Agent modules not available: {e}")

    try:
        history = get_history(req.session_id)
        response_text = await run_agent(
            message=req.message,
            history=history,
            context=req.context.model_dump(),
            session_id=req.session_id,
        )
        return ChatResponse(response=response_text, session_id=req.session_id)
    except Exception as exc:
        logger.error(f"Agent error for session {req.session_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/chat/stream", dependencies=[Depends(require_internal_token)])
@limiter.limit("20/minute")  # per real client IP
@limiter.limit("500/day", key_func=lambda: "global")  # global cap to protect the DeepSeek bill
async def chat_stream(request: Request, req: ChatRequest):
    """Streaming variant of /api/chat. Returns the agent's final answer as a
    chunked text/plain stream so the frontend can render tokens as they arrive
    instead of waiting for the whole response. The trailing ```json action block
    (if any) streams inline at the end; the client parses it once complete."""
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise HTTPException(status_code=503, detail="DEEPSEEK_API_KEY not configured on the server.")

    try:
        from agent.coach_agent import run_agent_stream
        from agent.memory import get_history
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Agent modules not available: {e}")

    history = get_history(req.session_id)

    async def token_stream():
        try:
            async for chunk in run_agent_stream(
                message=req.message,
                history=history,
                context=req.context.model_dump(),
                session_id=req.session_id,
            ):
                yield chunk
        except Exception as exc:
            logger.error(f"Agent stream error for session {req.session_id}: {exc}", exc_info=True)
            yield "\n\nI ran into a technical issue generating that response. Please try again."

    return StreamingResponse(
        token_stream(),
        media_type="text/plain; charset=utf-8",
        headers={
            # Defeat proxy/browser buffering so chunks reach the client immediately.
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/chord/{chord_name}", dependencies=[Depends(require_internal_token)])
async def get_chord_endpoint(chord_name: str):
    try:
        _, _, _, _, get_chord, _, _, _ = _get_agent_modules()
    except ImportError as e:
        raise HTTPException(status_code=503, detail=str(e))

    chord = get_chord(chord_name)
    if not chord:
        raise HTTPException(status_code=404, detail=f"Chord '{chord_name}' not found")
    return chord


@app.get("/api/chords", dependencies=[Depends(require_internal_token)])
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


@app.get("/api/progressions", dependencies=[Depends(require_internal_token)])
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


@app.delete("/api/session/{session_id}", dependencies=[Depends(require_internal_token)])
async def clear_session(session_id: str):
    try:
        _, _, clear_memory, _, _, _, _, _ = _get_agent_modules()
    except ImportError as e:
        raise HTTPException(status_code=503, detail=str(e))

    cleared = clear_memory(session_id)
    return {"cleared": cleared}


@app.get("/api/session/{session_id}/practice-log", dependencies=[Depends(require_internal_token)])
async def get_practice_log_endpoint(session_id: str):
    from agent.memory import get_session_data
    data = get_session_data(session_id)
    return {
        "session_id": session_id,
        "practice_log": data["practice_log"],
        "skill_level": data["skill_level"],
    }


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
