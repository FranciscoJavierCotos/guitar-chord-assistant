"""
Unit tests for the deterministic music-theory engine in agent/tools.py.

These functions are the brain of ChordCoach: key inference, Roman-numeral
labelling, transposition, and progression analysis. They are pure (no LLM, no
network), so they are both the highest-value and the easiest things to pin down
against regression. The interesting, documented behaviours — e.g. that an
off-tonic loop like Am-F-C-G is read as C major, not A minor — are encoded here.
"""

import pytest

from agent.tools import (
    NOTE_NAMES,
    _chord_root_index,
    _contains_subsequence,
    _infer_key,
    _parse_chord_quality,
    _progression_degrees,
    _roman_numeral,
    _transpose_chord_name,
    explain_theory,
)


def _key_name(chords: list[str]) -> str:
    """Helper: run key inference and render it as 'C major' / 'A minor'."""
    result = _infer_key(chords)
    assert result is not None, f"expected a key for {chords}"
    tonic, mode = result
    return f"{NOTE_NAMES[tonic]} {mode}"


# ─── _infer_key ────────────────────────────────────────────────────────────────
class TestInferKey:
    def test_off_tonic_loop_is_read_as_relative_major(self):
        # The headline case: vi-IV-I-V. The histogram, not the first chord,
        # decides the tonic, so this must be C major and NOT A minor.
        assert _key_name(["Am", "F", "C", "G"]) == "C major"

    def test_ii_v_i_cadence_picks_the_resolution_tonic(self):
        # Dm-G-C is ii-V-I in C. The raw histogram leans toward G; the authentic
        # cadence bonus must pull it back to C major.
        assert _key_name(["Dm", "G", "C"]) == "C major"

    def test_plain_major_progression(self):
        assert _key_name(["C", "G", "Am", "F"]) == "C major"

    def test_minor_progression_detected_as_minor(self):
        # i-iv-v in A minor — no relative-major pull, no authentic cadence.
        assert _key_name(["Am", "Dm", "Em"]) == "A minor"

    def test_returns_none_when_no_chord_is_parseable(self):
        assert _infer_key(["???", "xyz", ""]) is None

    def test_empty_list_returns_none(self):
        assert _infer_key([]) is None


# ─── explain_theory (the @tool wrapping the engine) ─────────────────────────────
class TestExplainTheory:
    def _run(self, chords: str) -> str:
        # .func unwraps the LangChain @tool back to the plain callable.
        return explain_theory.func(chords)

    def test_reports_relative_major_key_and_roman_numerals(self):
        out = self._run("Am-F-C-G")
        assert "C major" in out
        # vi-IV-I-V relative to C.
        assert "vi → IV → I → V" in out

    def test_detects_the_i_v_vi_iv_pattern(self):
        out = self._run("C-G-Am-F")
        # The canonical four-chord-song loop blurb should fire.
        assert "voice leading" in out.lower()

    def test_minor_heavy_progression_is_classified_minor(self):
        out = self._run("Am-Dm-Em")
        assert "Minor-heavy" in out

    def test_major_heavy_progression_is_classified_major(self):
        out = self._run("C-G-D")
        assert "Major-heavy" in out

    def test_accepts_comma_separated_input(self):
        out = self._run("Am, F, C, G")
        assert "C major" in out

    def test_empty_input_returns_guidance_without_raising(self):
        out = self._run("")
        assert "provide chords" in out.lower()

    def test_garbage_input_does_not_raise(self):
        # Unparseable chords must degrade gracefully, never throw.
        out = self._run("zzz-qqq")
        assert isinstance(out, str) and out


# ─── _transpose_chord_name ──────────────────────────────────────────────────────
class TestTranspose:
    def test_transposes_up_preserving_quality(self):
        assert _transpose_chord_name("C", 2) == "D"
        assert _transpose_chord_name("Am", 2) == "Bm"
        assert _transpose_chord_name("Cmaj7", 2) == "Dmaj7"

    def test_wraps_around_the_octave(self):
        assert _transpose_chord_name("B", 1) == "C"

    def test_transposes_down(self):
        assert _transpose_chord_name("D", -2) == "C"

    def test_handles_flat_root_via_enharmonic(self):
        # Bb is enharmonic to A#; shifting up 2 lands on C.
        assert _transpose_chord_name("Bb", 2) == "C"

    def test_slash_chord_transposes_both_parts(self):
        assert _transpose_chord_name("D/F#", 2) == "E/G#"

    def test_unrecognized_token_passes_through_untouched(self):
        assert _transpose_chord_name("xyz", 2) == "xyz"

    def test_empty_string_passes_through(self):
        assert _transpose_chord_name("", 3) == ""

    def test_capo_shape_math(self):
        # Capo 4 means fingering shapes 4 semitones below the sounding chords.
        assert _transpose_chord_name("E", -4) == "C"
        assert _transpose_chord_name("G#m", -4) == "Em"
        assert _transpose_chord_name("B", -4) == "G"


# ─── _roman_numeral ─────────────────────────────────────────────────────────────
class TestRomanNumeral:
    def test_tonic_major(self):
        # C in C major.
        assert _roman_numeral(0, "major", tonic=0, mode="major") == "I"

    def test_minor_quality_is_lowercase(self):
        # A minor (vi) relative to C major.
        assert _roman_numeral(9, "minor", tonic=0, mode="major") == "vi"

    def test_dominant_seventh_carries_a_seven(self):
        # G7 (V7) relative to C major.
        assert _roman_numeral(7, "dominant7", tonic=0, mode="major") == "V7"

    def test_diminished_symbol(self):
        # B diminished (vii°) relative to C major.
        assert _roman_numeral(11, "diminished", tonic=0, mode="major") == "vii°"

    def test_chromatic_root_keeps_its_accidental(self):
        # Bb (bVII) relative to C major.
        assert _roman_numeral(10, "major", tonic=0, mode="major") == "bVII"


# ─── _parse_chord_quality / _chord_root_index ───────────────────────────────────
class TestChordParsing:
    @pytest.mark.parametrize(
        "chord, expected_root",
        [("C", 0), ("C#", 1), ("Db", 1), ("A", 9), ("Bb", 10), ("G#m7", 8)],
    )
    def test_root_index(self, chord, expected_root):
        assert _chord_root_index(chord) == expected_root

    def test_root_index_returns_none_for_junk(self):
        assert _chord_root_index("xyz") is None
        assert _chord_root_index("") is None

    @pytest.mark.parametrize(
        "chord, expected_quality",
        [
            ("Cdim", "diminished"),
            ("Caug", "augmented"),
            ("Cmaj7", "major7"),
            ("Cm7", "minor7"),
            ("Cm", "minor"),
            ("Csus4", "sus4"),
            ("Csus2", "sus2"),
            ("C5", "power"),
            ("Cadd9", "add9"),
            ("C7", "dominant7"),
            ("C", "major"),
        ],
    )
    def test_quality_suffix_fallback(self, chord, expected_quality):
        # Use a root unlikely to collide with the chord DB so the suffix parser runs.
        root, quality = _parse_chord_quality(chord)
        assert quality == expected_quality

    def test_unparseable_chord_yields_none_root(self):
        root, _ = _parse_chord_quality("xyz")
        assert root is None


# ─── _progression_degrees ───────────────────────────────────────────────────────
class TestProgressionDegrees:
    def test_degrees_relative_to_explicit_tonic(self):
        # C major: C=1, G=5, Am=6, F=4.
        assert _progression_degrees(["C", "G", "Am", "F"], tonic=0) == [1, 5, 6, 4]

    def test_first_chord_is_tonic_when_unspecified(self):
        assert _progression_degrees(["G", "C", "D"]) == [1, 4, 5]

    def test_unparseable_chords_are_skipped(self):
        assert _progression_degrees(["C", "xyz", "G"], tonic=0) == [1, 5]


# ─── _contains_subsequence ──────────────────────────────────────────────────────
class TestContainsSubsequence:
    def test_contiguous_match(self):
        assert _contains_subsequence([1, 5, 6, 4], [5, 6]) is True

    def test_non_contiguous_is_not_a_match(self):
        assert _contains_subsequence([1, 5, 6, 4], [1, 6]) is False

    def test_sub_longer_than_seq(self):
        assert _contains_subsequence([1, 2], [1, 2, 3]) is False

    def test_empty_sub_is_false(self):
        assert _contains_subsequence([1, 2, 3], []) is False
