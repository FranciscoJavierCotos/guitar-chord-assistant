"""
Offline tests for the eval harness — the AgentAction schema mirror, the
deterministic graders, and golden-set integrity.

These run with no network and no LLM (they grade fixture responses), so the
*deterministic* portion of the eval is exercised on every PR via the normal
backend pytest job. The full agent+judge run lives in `python -m eval` and is
gated to workflow_dispatch / main in CI.
"""

import pytest

from eval.cases import EvalCase, Expect, load_cases
from eval.schema import parse_agent_action, extract_action_block
from eval.graders.deterministic import (
    run_deterministic,
    grade_action_valid,
    grade_chords_in_db,
    grade_key_adherence,
    grade_chord_ids,
    grade_chord_count,
    grade_progression_resolves,
    _diatonic_roots,
)


def _block(action_json: str) -> str:
    return f"Here you go.\n```json\n{action_json}\n```"


SHOW_CHORDS = _block('{"action": "show_chords", "chords": ["E7", "A7", "B7"], '
                     '"progression_name": "12-Bar Blues in E", "bpm_suggestion": 75}')
SHOW_CHORD = _block('{"action": "show_chord", "chord": "Am"}')


# ─── schema ───────────────────────────────────────────────────────────────────


class TestSchema:
    def test_parses_show_chords(self):
        action = parse_agent_action(SHOW_CHORDS)
        assert action is not None
        assert action.action == "show_chords"
        assert action.chords == ["E7", "A7", "B7"]
        assert action.referenced_chords() == ["E7", "A7", "B7"]

    def test_parses_show_chord(self):
        action = parse_agent_action(SHOW_CHORD)
        assert action is not None
        assert action.chord == "Am"
        assert action.referenced_chords() == ["Am"]

    def test_no_block_returns_none(self):
        assert parse_agent_action("Just some prose, no block.") is None
        assert extract_action_block("no fence here") is None

    def test_invalid_json_returns_none(self):
        assert parse_agent_action('```json\n{"action": "show_chords", oops}\n```') is None

    def test_unknown_action_returns_none(self):
        assert parse_agent_action(_block('{"action": "explode"}')) is None

    def test_non_string_chords_rejected(self):
        assert parse_agent_action(_block('{"action": "show_chords", "chords": [1, 2]}')) is None


# ─── deterministic graders ──────────────────────────────────────────────────────


class TestActionValid:
    def test_pass_on_matching_action(self):
        case = EvalCase(id="c", prompt="p", expect=Expect(action="show_chords"))
        assert grade_action_valid(case, SHOW_CHORDS).passed

    def test_fail_on_missing_block(self):
        case = EvalCase(id="c", prompt="p", expect=Expect(action="show_chords"))
        assert grade_action_valid(case, "no block").passed is False

    def test_fail_on_wrong_action_type(self):
        case = EvalCase(id="c", prompt="p", expect=Expect(action="show_chord"))
        assert grade_action_valid(case, SHOW_CHORDS).passed is False

    def test_expect_none_passes_when_absent(self):
        case = EvalCase(id="c", prompt="p", expect=Expect(action="none"))
        assert grade_action_valid(case, "pure prose").passed

    def test_expect_none_fails_when_present(self):
        case = EvalCase(id="c", prompt="p", expect=Expect(action="none"))
        assert grade_action_valid(case, SHOW_CHORDS).passed is False

    def test_not_applicable_when_unset(self):
        case = EvalCase(id="c", prompt="p", expect=Expect())
        assert grade_action_valid(case, SHOW_CHORDS) is None


class TestChordsInDb:
    def test_pass_on_real_chords(self):
        case = EvalCase(id="c", prompt="p", expect=Expect())
        assert grade_chords_in_db(case, SHOW_CHORDS).passed

    def test_fail_on_hallucinated_chord(self):
        bad = _block('{"action": "show_chords", "chords": ["E7", "Zz9"]}')
        case = EvalCase(id="c", prompt="p", expect=Expect())
        result = grade_chords_in_db(case, bad)
        assert result.passed is False and "Zz9" in result.detail


class TestKeyAdherence:
    def test_pass_when_diatonic(self):
        case = EvalCase(id="c", prompt="p", expect=Expect(key="E"))
        assert grade_key_adherence(case, SHOW_CHORDS).passed

    def test_fail_when_out_of_key(self):
        off = _block('{"action": "show_chords", "chords": ["E7", "Fm"]}')
        case = EvalCase(id="c", prompt="p", expect=Expect(key="E"))
        assert grade_key_adherence(case, off).passed is False

    def test_minor_key_roots(self):
        # Am minor diatonic roots include A, C, D, E, F, G.
        roots = _diatonic_roots("Am")
        from agent.tools import _note_index
        for note in ("A", "C", "D", "E", "F", "G"):
            assert _note_index(note) in roots


class TestChordConstraints:
    def test_chord_ids_present(self):
        case = EvalCase(id="c", prompt="p", expect=Expect(chord_ids=["E7", "A7"]))
        assert grade_chord_ids(case, SHOW_CHORDS).passed

    def test_chord_ids_missing(self):
        case = EvalCase(id="c", prompt="p", expect=Expect(chord_ids=["Cmaj7"]))
        assert grade_chord_ids(case, SHOW_CHORDS).passed is False

    def test_min_chords(self):
        case = EvalCase(id="c", prompt="p", expect=Expect(min_chords=5))
        assert grade_chord_count(case, SHOW_CHORDS).passed is False

    def test_max_chords(self):
        case = EvalCase(id="c", prompt="p", expect=Expect(max_chords=10))
        assert grade_chord_count(case, SHOW_CHORDS).passed


class TestProgressionResolves:
    def test_resolves_by_name(self):
        case = EvalCase(id="c", prompt="p", expect=Expect(progression_resolves=True))
        assert grade_progression_resolves(case, SHOW_CHORDS).passed

    def test_unresolvable_name(self):
        block = _block('{"action": "show_chords", "chords": ["X", "Y"], '
                       '"progression_name": "Totally Made Up Progression"}')
        case = EvalCase(id="c", prompt="p", expect=Expect(progression_resolves=True))
        assert grade_progression_resolves(case, block).passed is False


# ─── golden-set integrity ───────────────────────────────────────────────────────


class TestInfraErrorHandling:
    """An agent infrastructure failure (bad key, network, provider outage) must be
    reported as an *errored* case, not a 0% content-grading failure. Regression for
    the 401 misdiagnosis where every case showed 'no valid action block found'."""

    def test_detects_agent_error_string(self):
        from eval.runner import _agent_error
        from agent.coach_agent import AGENT_ERROR_PREFIX

        fallback = (
            f"{AGENT_ERROR_PREFIX} Error code: 401 - Authentication Fails\n\n"
            "Please try rephrasing your question or ask me something else!"
        )
        assert _agent_error(fallback) is not None
        # A real answer (even a bad one) is not an infra error.
        assert _agent_error(SHOW_CHORDS) is None
        assert _agent_error("Here are some chords, no action block.") is None

    def test_aggregate_excludes_errored_from_content_metrics(self):
        from eval.runner import _aggregate
        from eval.graders.judge import JudgeConfig

        errored = {
            "id": "boom", "tags": [], "prompt": "p", "response": "x",
            "errored": True, "error": "401",
            "deterministic": [{"name": "action_valid", "passed": False, "detail": "no block"}],
            "deterministic_passed": False,
        }
        ok = {
            "id": "fine", "tags": [], "prompt": "p", "response": SHOW_CHORDS,
            "errored": False, "error": None,
            "deterministic": [{"name": "action_valid", "passed": True, "detail": "ok"}],
            "deterministic_passed": True,
        }
        s = _aggregate([errored, ok], use_judge=False, judge_config=JudgeConfig())["summary"]
        assert s["errored_cases"] == 1
        assert s["scored_cases"] == 1
        # The errored case must not drag the pass rate down — the one scored case passed.
        assert s["deterministic_pass_rate"] == 1.0
        assert s["per_grader_pass_rate"]["action_valid"] == 1.0

    def test_main_aborts_with_exit_2_when_a_case_errors(self, tmp_path, monkeypatch):
        from eval import runner

        errored_report = {
            "summary": {
                "total_cases": 1, "errored_cases": 1, "scored_cases": 0,
                "deterministic_pass_rate": 1.0, "deterministic_cases_passed": 0,
                "per_grader_pass_rate": {}, "use_judge": False,
            },
            "cases": [{
                "id": "boom", "tags": [], "prompt": "p", "response": "x",
                "errored": True, "error": "401",
                "deterministic": [], "deterministic_passed": False,
            }],
        }
        monkeypatch.setattr(runner, "load_cases", lambda *a, **k: [EvalCase(id="boom", prompt="p")])
        monkeypatch.setattr(runner, "_load_env", lambda: None)

        async def _fake_eval(*a, **k):
            return errored_report

        monkeypatch.setattr(runner, "run_eval", _fake_eval)
        out = tmp_path / "report.json"
        # Distinct exit code 2 (infra), never the content-threshold exit 1.
        assert runner.main(["--no-judge", "--out", str(out)]) == 2


class TestDeterminism:
    """The golden set is a regression gate, so the agent must run at a pinned
    temperature — otherwise the production 0.7 makes the same code score
    67%/75%/100% across runs from sampling noise alone."""

    def test_default_eval_temperature_is_zero(self):
        from eval.runner import _agent_temperature

        assert _agent_temperature() == 0.0

    def test_env_overrides_eval_temperature(self, monkeypatch):
        from eval.runner import _agent_temperature

        monkeypatch.setenv("EVAL_AGENT_TEMPERATURE", "0.4")
        assert _agent_temperature() == 0.4
        # Garbage falls back to the deterministic default rather than crashing.
        monkeypatch.setenv("EVAL_AGENT_TEMPERATURE", "not-a-number")
        assert _agent_temperature() == 0.0

    def test_generate_passes_pinned_temperature_to_agent(self, monkeypatch):
        import asyncio
        import agent.coach_agent as coach_agent
        from eval.runner import _generate

        captured = {}

        async def _fake_run_agent(**kwargs):
            captured.update(kwargs)
            return SHOW_CHORD

        monkeypatch.setattr(coach_agent, "run_agent", _fake_run_agent)
        monkeypatch.delenv("EVAL_AGENT_TEMPERATURE", raising=False)

        asyncio.run(_generate(EvalCase(id="t", prompt="How do I play Am?")))
        assert captured["temperature"] == 0.0


class TestGoldenSet:
    def test_loads_enough_cases(self):
        cases = load_cases()
        assert len(cases) >= 15, "golden set should have at least ~15 cases"

    def test_ids_unique(self):
        cases = load_cases()
        ids = [c.id for c in cases]
        assert len(ids) == len(set(ids))

    @pytest.mark.parametrize("case", load_cases(), ids=[c.id for c in load_cases()])
    def test_case_is_well_formed(self, case):
        assert case.id and case.prompt
        if case.expect.action is not None:
            assert case.expect.action in {"show_chords", "show_chord", "none"}
        for turn in case.history:
            assert turn.get("role") in {"user", "human", "assistant", "ai"}
        # A judge rubric should exist so the subjective grader has guidance.
        assert case.judge.dimensions

    @pytest.mark.parametrize("case", load_cases(), ids=[c.id for c in load_cases()])
    def test_expected_chord_ids_exist_in_db(self, case):
        # Cases must not assert chords the dataset can't render.
        from data.chords import get_chord
        for chord in case.expect.chord_ids:
            assert get_chord(chord) is not None, f"{case.id}: {chord} not in dataset"

    def test_scale_chords_case_demands_chords(self):
        """Regression for #18: "what chords are in the key of G major?" must demand a
        show_chords block with the diatonic chords, so an empty/no-chord answer fails a
        deterministic grader (not only the judge). Don't weaken this case."""
        case = next((c for c in load_cases() if c.id == "theory-scale-chords-g"), None)
        assert case is not None, "theory-scale-chords-g regression case was removed"
        assert case.expect.action == "show_chords"
        assert (case.expect.min_chords or 0) >= 6
        # The available diatonic chords must be asserted (F#dim has no diagram, excluded).
        for chord in ("G", "Am", "Bm", "C", "D", "Em"):
            assert chord in case.expect.chord_ids

    def test_mood_only_progression_case_kept(self):
        """Regression for #17: a mood-*only* request ("a sad-sounding progression")
        must stay in the golden set demanding an actual show_chords block, so the
        full eval keeps guarding the prompt-reliability gap where the agent bailed
        with vague prose and no progression. Don't drop or weaken this case."""
        case = next((c for c in load_cases() if c.id == "prog-sad-mood"), None)
        assert case is not None, "prog-sad-mood regression case was removed"
        assert case.expect.action == "show_chords"
        assert (case.expect.min_chords or 0) >= 3

    def test_followup_context_key_demands_min_chords(self):
        """Regression for #19: "give me a progression I can play right now" with
        session context (key E, beginner) must stay in the golden set demanding a
        usable progression of at least 3 chords, so the full eval keeps guarding
        the case where the agent returned a too-thin 2-chord answer. Don't weaken
        this case — the prompt's min-length guidance is what keeps it green."""
        case = next((c for c in load_cases() if c.id == "followup-context-key"), None)
        assert case is not None, "followup-context-key regression case was removed"
        assert case.expect.action == "show_chords"
        assert (case.expect.min_chords or 0) >= 3
