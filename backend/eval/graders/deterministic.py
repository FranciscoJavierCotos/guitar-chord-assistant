"""
Deterministic graders — fast, free, no LLM, no network.

These check the *objective* contract the frontend depends on: a valid
``AgentAction`` block, no hallucinated chords or fingerings (cross-checked
against ``data/chords.py``), named progressions that resolve against
``data/progressions.py``, and adherence to a requested key / chord-count.

Every grader is a pure function of ``(case, response_text)`` so it can be unit
tested offline against fixture responses — which is how the deterministic
portion runs on every PR without spending an LLM call. Each returns a
``GraderResult`` or ``None`` when the case has nothing for it to check.
"""

from __future__ import annotations

from dataclasses import dataclass

from data.chords import CHORDS, get_chord
from data.progressions import PROGRESSIONS

from eval.cases import EvalCase
from eval.schema import AgentAction, parse_agent_action

# Reuse the agent's own theory engine so "is this chord in the key" agrees with
# what the agent was told to produce, rather than a second, divergent definition.
from agent.tools import _build_diatonic_chords, _chord_root_index, _note_index


@dataclass
class GraderResult:
    name: str
    passed: bool
    detail: str


# ─── Helpers ────────────────────────────────────────────────────────────────


def _chord_exists(name: str) -> bool:
    return get_chord(name.strip()) is not None


def _key_root_and_mode(key: str) -> tuple[str, str]:
    """Split a key like 'Am' / 'C' / 'F#m' into (root, scale)."""
    key = key.strip()
    if key.endswith("m") and not key.endswith("dim"):
        return key[:-1], "minor"
    return key, "major"


def _diatonic_roots(key: str) -> set[int]:
    """Pitch-class set of the diatonic chord roots for a key (major or minor)."""
    root, scale = _key_root_and_mode(key)
    roots: set[int] = set()
    for c in _build_diatonic_chords(root, scale):
        idx = _chord_root_index(c["chord"])
        if idx is not None:
            roots.add(idx)
    # Always allow the tonic itself.
    tonic = _note_index(root)
    roots.add(tonic)
    return roots


def _resolves_progression(name: str | None, chords: list[str]) -> bool:
    """True if a named progression resolves in the dataset by name or chords."""
    if name:
        target = name.strip().lower()
        for p in PROGRESSIONS:
            if p["name"].strip().lower() == target:
                return True
    if chords:
        wanted = [c.strip() for c in chords]
        for p in PROGRESSIONS:
            if [c.strip() for c in p["chords"]] == wanted:
                return True
    return False


# ─── Graders ────────────────────────────────────────────────────────────────


def grade_action_valid(case: EvalCase, response: str) -> GraderResult | None:
    """The trailing ``AgentAction`` block parses, validates, and matches the
    expected action type. ``expect.action == "none"`` asserts there is no block."""
    expected = case.expect.action
    if expected is None:
        return None
    action = parse_agent_action(response)
    if expected == "none":
        passed = action is None
        return GraderResult(
            "action_valid",
            passed,
            "no action block (as expected)" if passed
            else f"unexpected action block: {action.action if action else None}",
        )
    if action is None:
        return GraderResult(
            "action_valid", False,
            "no valid action block found (expected " + expected + ")",
        )
    if action.action != expected:
        return GraderResult(
            "action_valid", False,
            f"action was '{action.action}', expected '{expected}'",
        )
    # show_chords needs a non-empty chords list; show_chord needs a single chord.
    if action.action == "show_chords" and not action.chords:
        return GraderResult("action_valid", False, "show_chords with empty chords")
    if action.action == "show_chord" and not action.chord:
        return GraderResult("action_valid", False, "show_chord with no chord")
    return GraderResult("action_valid", True, f"valid {action.action} block")


def grade_chords_in_db(case: EvalCase, response: str) -> GraderResult | None:
    """No hallucinated chords: every chord the action references exists in
    ``data/chords.py`` with a real fingering."""
    if not case.expect.chords_in_db:
        return None
    action = parse_agent_action(response)
    if action is None:
        return None  # action_valid already covers the missing-block case
    referenced = action.referenced_chords()
    if not referenced:
        return None
    missing = [c for c in referenced if not _chord_exists(c)]
    if missing:
        return GraderResult(
            "chords_in_db", False,
            f"chords not in database (hallucinated): {', '.join(missing)}",
        )
    return GraderResult(
        "chords_in_db", True, f"all {len(referenced)} chord(s) exist in the dataset",
    )


def grade_progression_resolves(case: EvalCase, response: str) -> GraderResult | None:
    """A named progression resolves against ``data/progressions.py`` (by name or
    by exact chord sequence)."""
    if not case.expect.progression_resolves:
        return None
    action = parse_agent_action(response)
    if action is None:
        return GraderResult("progression_resolves", False, "no action block to resolve")
    ok = _resolves_progression(action.progression_name, action.chords or [])
    return GraderResult(
        "progression_resolves", ok,
        f"resolved '{action.progression_name}'" if ok
        else f"progression '{action.progression_name}' did not resolve in the dataset",
    )


def grade_key_adherence(case: EvalCase, response: str) -> GraderResult | None:
    """Action chords are diatonic to the requested key (root membership, so 7th
    and sus variants of an in-key root still count)."""
    if not case.expect.key:
        return None
    action = parse_agent_action(response)
    if action is None:
        return None
    referenced = action.referenced_chords()
    if not referenced:
        return None
    allowed = _diatonic_roots(case.expect.key)
    out_of_key = []
    for c in referenced:
        idx = _chord_root_index(c)
        if idx is None or idx not in allowed:
            out_of_key.append(c)
    if out_of_key:
        return GraderResult(
            "key_adherence", False,
            f"chords outside key {case.expect.key}: {', '.join(out_of_key)}",
        )
    return GraderResult(
        "key_adherence", True, f"all chords are diatonic to {case.expect.key}",
    )


def grade_chord_ids(case: EvalCase, response: str) -> GraderResult | None:
    """Specific expected chords all appear in the action."""
    if not case.expect.chord_ids:
        return None
    action = parse_agent_action(response)
    referenced = {c.strip() for c in (action.referenced_chords() if action else [])}
    missing = [c for c in case.expect.chord_ids if c.strip() not in referenced]
    if missing:
        return GraderResult(
            "chord_ids", False, f"missing expected chords: {', '.join(missing)}",
        )
    return GraderResult("chord_ids", True, "all expected chords present")


def grade_chord_count(case: EvalCase, response: str) -> GraderResult | None:
    """Min/max chord-count constraints are honored."""
    if case.expect.min_chords is None and case.expect.max_chords is None:
        return None
    action = parse_agent_action(response)
    n = len(action.referenced_chords()) if action else 0
    if case.expect.min_chords is not None and n < case.expect.min_chords:
        return GraderResult(
            "chord_count", False, f"{n} chords, expected >= {case.expect.min_chords}",
        )
    if case.expect.max_chords is not None and n > case.expect.max_chords:
        return GraderResult(
            "chord_count", False, f"{n} chords, expected <= {case.expect.max_chords}",
        )
    return GraderResult("chord_count", True, f"{n} chords within bounds")


# Ordered so the report reads top-down from "did the contract hold" outward.
DETERMINISTIC_GRADERS = [
    grade_action_valid,
    grade_chords_in_db,
    grade_progression_resolves,
    grade_key_adherence,
    grade_chord_ids,
    grade_chord_count,
]


def run_deterministic(case: EvalCase, response: str) -> list[GraderResult]:
    """Run every applicable deterministic grader for a case/response."""
    results: list[GraderResult] = []
    for grader in DETERMINISTIC_GRADERS:
        result = grader(case, response)
        if result is not None:
            results.append(result)
    return results
