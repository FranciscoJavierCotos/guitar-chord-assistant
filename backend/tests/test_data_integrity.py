"""
Data-integrity guards for the chord and progression datasets.

These are the source of truth the agent is told never to invent around, and they
must stay in sync with frontend/lib/types.ts (ChordPosition / Progression). The
parametrized checks make a malformed edit — a 5-string chord, a progression
missing 'roman', a stringified tempo — fail loudly in CI instead of surfacing as
a broken diagram or a 500 in production.
"""

import pytest

from data.chords import CHORDS, get_chord
from data.progressions import PROGRESSIONS

# Keys the frontend ChordPosition interface treats as required.
REQUIRED_CHORD_KEYS = {"name", "full_name", "positions", "fingers", "base_fret"}
# Keys CLAUDE.md / types.ts require on every progression record.
REQUIRED_PROG_KEYS = {
    "id", "name", "genre", "key", "chords", "roman",
    "difficulty", "description", "feel", "tempo_bpm", "tags",
}


@pytest.mark.parametrize("name", list(CHORDS.keys()))
class TestChordSchema:
    def test_required_keys_present(self, name):
        assert REQUIRED_CHORD_KEYS <= set(CHORDS[name].keys())

    def test_key_matches_inner_name(self, name):
        assert CHORDS[name]["name"] == name

    def test_positions_are_six_strings(self, name):
        positions = CHORDS[name]["positions"]
        assert isinstance(positions, list) and len(positions) == 6

    def test_fingers_are_six_strings(self, name):
        fingers = CHORDS[name]["fingers"]
        assert isinstance(fingers, list) and len(fingers) == 6

    def test_positions_in_valid_range(self, name):
        # -1 = muted, 0 = open, positive = fret.
        assert all(isinstance(p, int) and p >= -1 for p in CHORDS[name]["positions"])

    def test_fingers_in_valid_range(self, name):
        # 0 = open/muted, 1-4 = fingers.
        assert all(isinstance(f, int) and 0 <= f <= 4 for f in CHORDS[name]["fingers"])

    def test_barre_shape_is_well_formed(self, name):
        barre = CHORDS[name].get("barre")
        if barre is not None:
            assert {"from_string", "to_string", "fret", "finger"} <= set(barre.keys())
            assert 0 <= barre["from_string"] <= 5
            assert 0 <= barre["to_string"] <= 5


def test_chord_ids_are_unique():
    # Dict keys are unique by construction, but guard the inner 'name' fields too.
    names = [c["name"] for c in CHORDS.values()]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("prog", PROGRESSIONS, ids=[p["id"] for p in PROGRESSIONS])
class TestProgressionSchema:
    def test_required_keys_present(self, prog):
        assert REQUIRED_PROG_KEYS <= set(prog.keys())

    def test_list_fields_are_lists(self, prog):
        for field in ("genre", "chords", "roman", "tags"):
            assert isinstance(prog[field], list), f"{field} must be a list"

    def test_chords_and_roman_align(self, prog):
        # Each chord should have a Roman-numeral label.
        assert len(prog["chords"]) == len(prog["roman"])

    def test_tempo_is_a_positive_int(self, prog):
        assert isinstance(prog["tempo_bpm"], int) and prog["tempo_bpm"] > 0

    def test_has_at_least_one_chord(self, prog):
        assert len(prog["chords"]) > 0


def test_progression_ids_are_unique():
    ids = [p["id"] for p in PROGRESSIONS]
    assert len(ids) == len(set(ids)), "duplicate progression id"


def test_get_chord_exact_match_and_enharmonic_alias():
    # get_chord does an exact lookup plus a few enharmonic aliases. Whitespace
    # trimming is the caller's responsibility (every @tool strips before calling),
    # so a padded name is expected to miss.
    assert get_chord("Am") is not None
    assert get_chord("Gb") is not None  # enharmonic alias → F#m
    assert get_chord(" Am ") is None    # not stripped here by design
    assert get_chord("NotAChord") is None
