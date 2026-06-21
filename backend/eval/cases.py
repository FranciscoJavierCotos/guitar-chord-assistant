"""
Golden-set case model and loader.

Cases are plain YAML files under ``eval/cases/`` (version-controlled, no DB) so a
new contributor can add coverage by dropping in a file. Each file may hold a
single case (a mapping) or a list of cases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

CASES_DIR = Path(__file__).parent / "cases"


@dataclass
class Expect:
    """Objective expectations checked by the deterministic graders.

    Every field is optional; a grader simply skips a case it has nothing to
    check. ``action`` of ``"none"`` asserts the response carries NO action block
    (e.g. a pure theory question), distinct from leaving it unset (don't care).
    """

    action: str | None = None             # "show_chords" | "show_chord" | "none"
    chords_in_db: bool = True             # action chords must exist in data/chords.py
    key: str | None = None                # requested key the chords must fit
    chord_ids: list[str] = field(default_factory=list)  # chords that must appear
    min_chords: int | None = None
    max_chords: int | None = None
    progression_resolves: bool = False    # progression_name must resolve in dataset


@dataclass
class JudgeSpec:
    """Configuration for the LLM-as-judge on a case."""

    rubric: str = ""
    dimensions: list[str] = field(
        default_factory=lambda: [
            "musical_correctness",
            "relevance",
            "explanation_quality",
        ]
    )


@dataclass
class EvalCase:
    id: str
    prompt: str
    context: dict | None = None
    history: list[dict] = field(default_factory=list)  # [{role, content}, ...]
    expect: Expect = field(default_factory=Expect)
    judge: JudgeSpec = field(default_factory=JudgeSpec)
    tags: list[str] = field(default_factory=list)


def _build_case(raw: dict) -> EvalCase:
    if "id" not in raw or "prompt" not in raw:
        raise ValueError(f"case missing required 'id'/'prompt': {raw!r}")
    expect = Expect(**(raw.get("expect") or {}))
    judge_raw = raw.get("judge") or {}
    judge = JudgeSpec(**judge_raw) if judge_raw else JudgeSpec()
    return EvalCase(
        id=raw["id"],
        prompt=raw["prompt"],
        context=raw.get("context"),
        history=raw.get("history") or [],
        expect=expect,
        judge=judge,
        tags=raw.get("tags") or [],
    )


def load_cases(cases_dir: Path | str = CASES_DIR) -> list[EvalCase]:
    """Load and validate every case under ``cases_dir`` (sorted by id)."""
    cases_dir = Path(cases_dir)
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for path in sorted(cases_dir.glob("*.y*ml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if doc is None:
            continue
        records = doc if isinstance(doc, list) else [doc]
        for raw in records:
            case = _build_case(raw)
            if case.id in seen:
                raise ValueError(f"duplicate case id '{case.id}' ({path.name})")
            seen.add(case.id)
            cases.append(case)
    cases.sort(key=lambda c: c.id)
    return cases
