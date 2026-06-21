"""
LLM-as-judge grader for the subjective dimensions of an agent response —
musical correctness, relevance to the prompt, and explanation quality.

The judge model/config is pinned and configurable via env so a judge upgrade is
an explicit, reviewable change rather than silent drift:

  EVAL_JUDGE_MODEL     judge model id        (default: deepseek-chat)
  EVAL_JUDGE_BASE_URL  OpenAI-compatible URL (default: https://api.deepseek.com/v1)
  EVAL_JUDGE_API_KEY   judge API key         (falls back to DEEPSEEK_API_KEY)

Scores are on a 1-5 scale; a case passes the judge when the mean dimension score
meets ``pass_score`` (default 3.5). Output is structured (JSON) with a rationale.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from eval.cases import EvalCase

DEFAULT_JUDGE_MODEL = "deepseek-chat"
DEFAULT_JUDGE_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_PASS_SCORE = 3.5

JUDGE_SYSTEM_PROMPT = """You are a strict, fair evaluator of an AI guitar-coaching \
assistant called ChordCoach. You score a single assistant response to a user prompt.

Score each requested dimension from 1 to 5 (integers):
- 5 = excellent, fully correct and helpful
- 4 = good, minor issues
- 3 = acceptable, noticeable gaps
- 2 = poor, significant problems
- 1 = wrong, misleading, or unhelpful

Dimension definitions:
- musical_correctness: Are the chords, keys, theory, and any song facts accurate? \
Penalize invented chords, wrong keys, and fabricated song progressions.
- relevance: Does the response actually answer THIS prompt (right key/genre/chord/song, \
honoring any constraints) rather than a generic answer?
- explanation_quality: Is the explanation clear, correct, appropriately concise, and \
genuinely instructive for a guitarist?

Judge ONLY the dimensions you are asked for. Ignore the trailing ```json action block \
when scoring prose quality (it is a machine-readable directive, not user-facing text), \
but DO consider whether the chords it names are musically correct.

Respond with ONLY a JSON object, no prose, in exactly this shape:
{"scores": {"<dimension>": <int 1-5>, ...}, "rationale": "<one or two sentences>"}"""


@dataclass
class JudgeResult:
    scores: dict[str, int]
    rationale: str
    mean_score: float
    passed: bool
    error: str | None = None

    @property
    def name(self) -> str:
        return "llm_judge"


@dataclass
class JudgeConfig:
    model: str = field(default_factory=lambda: os.getenv("EVAL_JUDGE_MODEL", DEFAULT_JUDGE_MODEL))
    base_url: str = field(default_factory=lambda: os.getenv("EVAL_JUDGE_BASE_URL", DEFAULT_JUDGE_BASE_URL))
    api_key: str | None = field(
        default_factory=lambda: os.getenv("EVAL_JUDGE_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    )
    temperature: float = 0.0
    pass_score: float = DEFAULT_PASS_SCORE

    def as_metadata(self) -> dict:
        """Config recorded in the report (never the api key)."""
        return {
            "model": self.model,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "pass_score": self.pass_score,
        }


def _build_judge_llm(config: JudgeConfig):
    from langchain_openai import ChatOpenAI

    if not config.api_key:
        raise RuntimeError(
            "No judge API key: set EVAL_JUDGE_API_KEY or DEEPSEEK_API_KEY."
        )
    return ChatOpenAI(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=config.temperature,
        max_tokens=512,
    )


def _build_user_prompt(case: EvalCase, response: str) -> str:
    dims = ", ".join(case.judge.dimensions)
    parts = [f"USER PROMPT:\n{case.prompt}\n"]
    if case.context:
        parts.append(f"SESSION CONTEXT: {json.dumps(case.context)}\n")
    if case.judge.rubric:
        parts.append(f"CASE-SPECIFIC RUBRIC (what a good answer must do):\n{case.judge.rubric}\n")
    parts.append(f"ASSISTANT RESPONSE:\n{response}\n")
    parts.append(f"Score these dimensions only: {dims}.")
    return "\n".join(parts)


def _parse_judge_json(content: str) -> dict:
    """Extract the JSON object from the judge reply (tolerates code fences)."""
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if fenced:
        text = fenced.group(1)
    else:
        brace = re.search(r"\{[\s\S]*\}", text)
        if brace:
            text = brace.group(0)
    return json.loads(text)


def _score_from_payload(case: EvalCase, payload: dict, pass_score: float) -> JudgeResult:
    raw_scores = payload.get("scores", {}) if isinstance(payload, dict) else {}
    scores: dict[str, int] = {}
    for dim in case.judge.dimensions:
        val = raw_scores.get(dim)
        if isinstance(val, (int, float)):
            scores[dim] = max(1, min(5, int(round(val))))
    if not scores:
        return JudgeResult({}, "judge returned no usable scores", 0.0, False, error="no_scores")
    mean = sum(scores.values()) / len(scores)
    return JudgeResult(
        scores=scores,
        rationale=str(payload.get("rationale", "")).strip(),
        mean_score=round(mean, 2),
        passed=mean >= pass_score,
    )


async def judge_response(
    case: EvalCase, response: str, config: JudgeConfig | None = None
) -> JudgeResult:
    """Score one response with the LLM judge. Never raises — a judge/API failure
    is captured as a failed result with an ``error`` so one bad call doesn't abort
    the whole run."""
    config = config or JudgeConfig()
    try:
        llm = _build_judge_llm(config)
        reply = await llm.ainvoke(
            [
                ("system", JUDGE_SYSTEM_PROMPT),
                ("human", _build_user_prompt(case, response)),
            ]
        )
        content = reply.content if isinstance(reply.content, str) else str(reply.content)
        payload = _parse_judge_json(content)
        return _score_from_payload(case, payload, config.pass_score)
    except Exception as exc:  # noqa: BLE001 — judge robustness over strictness
        return JudgeResult({}, f"judge error: {exc}", 0.0, False, error=str(exc))
