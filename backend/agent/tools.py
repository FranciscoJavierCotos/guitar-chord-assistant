"""
LangChain tools for the ChordCoach agent.
"""

import contextvars
import time as _time

from langchain_core.tools import tool

from data.chords import CHORDS, get_chord
from data.progressions import (
    PROGRESSIONS,
    get_progressions_by_genre,
    get_progressions_by_key,
    get_progressions_by_mood,
)

# ─── Session context (set by run_agent, read by tools) ────────────────────────
_current_session_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_session_id", default=""
)

def _web_search(query: str, max_results: int = 5) -> str:
    """Run a web search and return formatted 'title — snippet' lines.

    Uses the maintained `ddgs` package directly, which returns structured results
    (title + body + url). This is far more reliable than the langchain
    DuckDuckGoSearchRun wrapper, which silently returned 'No good result' for the
    chord-lookup queries this app depends on.
    """
    from ddgs import DDGS

    lines: list[str] = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            title = (r.get("title") or "").strip()
            body = (r.get("body") or "").strip()
            if title or body:
                lines.append(f"- {title}\n  {body}")
    return "\n".join(lines)

# ─── Difficulty filter ────────────────────────────────────────────────────────

def _filter_by_skill(progressions: list[dict]) -> list[dict]:
    sid = _current_session_id.get("")
    if not sid:
        return progressions
    from agent.memory import get_session_data
    level = get_session_data(sid).get("skill_level", "beginner")
    if level == "advanced":
        return progressions
    return [p for p in progressions if p.get("difficulty") != "advanced"]

# ─── Music theory helpers ──────────────────────────────────────────────────────

SCALE_PATTERNS: dict[str, list[int]] = {
    "major":      [0, 2, 4, 5, 7, 9, 11],
    "minor":      [0, 2, 3, 5, 7, 8, 10],
    "pentatonic": [0, 2, 4, 7, 9],
    "blues":      [0, 3, 5, 6, 7, 10],
    "dorian":     [0, 2, 3, 5, 7, 9, 10],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "phrygian":   [0, 1, 3, 5, 7, 8, 10],
    "lydian":     [0, 2, 4, 6, 7, 9, 11],
}

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
ENHARMONICS = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}

DIATONIC_CHORD_TYPES = {
    "major": ["major", "minor", "minor", "major", "major", "minor", "diminished"],
    "minor": ["minor", "diminished", "major", "minor", "minor", "major", "major"],
    "dorian": ["minor", "minor", "major", "major", "minor", "diminished", "major"],
    "mixolydian": ["major", "minor", "diminished", "major", "minor", "minor", "major"],
}

CHORD_TYPE_SUFFIXES = {"major": "", "minor": "m", "diminished": "dim"}

THEORY_RULES = {
    "major": "Major chords have a bright, happy, resolved sound — three notes stacked in a major third then a minor third.",
    "minor": "Minor chords carry a sadder, more introspective emotional color — a minor third stacked below a major third.",
    "dominant7": "Dominant 7th chords (V7) contain both a major triad and a minor 7th, creating strong tension that wants to resolve to the I chord.",
    "major7": "Major 7th chords have a dreamy, sophisticated quality — the added 7th softens the brightness of the major triad.",
    "minor7": "Minor 7th chords are warmer and more complex than basic minor chords — widely used in jazz, R&B, and neo-soul.",
    "diminished": "Diminished chords are inherently tense and unstable — they typically resolve upward by a half-step.",
    "power": "Power chords (root + 5th) are ambiguous — neither major nor minor — making them sound equally at home with major or minor melodies.",
    "add9": "Add9 chords layer the 2nd/9th note of the scale over a basic triad for richness without the complexity of a full 9th chord.",
    "sus4": "Suspended 4th chords replace the 3rd with the 4th, creating an unresolved, open sound that typically resolves back to the major chord.",
}

ROMAN_TO_DEGREE = {"I": 0, "II": 1, "III": 2, "IV": 3, "V": 4, "VI": 5, "VII": 6}

TENSION_RESOLUTION = {
    "V-I": "V→I is the strongest resolution in Western harmony — the leading tone in the V chord resolves up to the tonic.",
    "IV-I": "IV→I (plagal cadence) has an 'Amen' quality — softer and more final-sounding than V→I.",
    "ii-V-I": "ii→V→I is the cornerstone of jazz — each chord prepares the next through shared tones and voice leading.",
    "VI-II-V-I": "Moving around the circle of fifths creates satisfying sequential resolution.",
    "I-V-vi-IV": "This loop works because each chord shares two notes with its neighbors, creating smooth voice leading across all four chords.",
}

# Scale-degree sequences for the patterns above, used to detect a cadence by ROOT
# MOTION regardless of the actual chord names/key. Matching on names directly was the
# old bug — chord_list holds names like 'Am-F-C-G', never roman numerals.
TENSION_RESOLUTION_DEGREES = {
    "V-I": [5, 1],
    "IV-I": [4, 1],
    "ii-V-I": [2, 5, 1],
    "VI-II-V-I": [6, 2, 5, 1],
    "I-V-vi-IV": [1, 5, 6, 4],
}

# Semitone offset from the tonic → major-scale degree (1-7). Chromatic offsets map to
# the nearest diatonic degree so non-diatonic chords still slot into the analysis.
_SEMITONE_TO_DEGREE = {0: 1, 1: 2, 2: 2, 3: 3, 4: 3, 5: 4, 6: 4, 7: 5, 8: 6, 9: 6, 10: 7, 11: 7}

# ─── Key inference (Krumhansl-Schmuckler) ──────────────────────────────────────
# Chord-tone pitch-class intervals above the root, used to build a pitch-class
# histogram for key finding. Keyed by the `type` field from data/chords.py.
QUALITY_INTERVALS: dict[str, tuple[int, ...]] = {
    "major": (0, 4, 7),
    "minor": (0, 3, 7),
    "diminished": (0, 3, 6),
    "augmented": (0, 4, 8),
    "dominant7": (0, 4, 7, 10),
    "major7": (0, 4, 7, 11),
    "major9": (0, 4, 7, 11, 2),
    "minor7": (0, 3, 7, 10),
    "minor9": (0, 3, 7, 10, 2),
    "add9": (0, 4, 7, 2),
    "sus4": (0, 5, 7),
    "sus2": (0, 2, 7),
    "power": (0, 7),
}

# Qualities that take a lowercase Roman numeral.
_MINOR_QUALITIES = {"minor", "minor7", "minor9", "diminished"}

# Krumhansl-Kessler tonal hierarchy profiles (major / natural-minor), tonic at index 0.
# The progression's pitch-class histogram is correlated against all 24 rotations
# (12 keys × 2 modes); the best correlation wins. This naturally handles off-tonic
# progressions (e.g. Am-F-C-G scores highest as C major, not A minor) because the
# histogram, not the first chord, decides the tonic.
_KS_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_KS_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

# Semitone-above-tonic → Roman numeral base (uppercase, with accidental prefix).
# Diatonic degrees carry no accidental; chromatic roots get the conventional one.
_ROMAN_MAJOR = {0: "I", 1: "bII", 2: "II", 3: "bIII", 4: "III", 5: "IV",
                6: "#IV", 7: "V", 8: "bVI", 9: "VI", 10: "bVII", 11: "VII"}
_ROMAN_MINOR = {0: "I", 1: "bII", 2: "II", 3: "III", 4: "#III", 5: "IV",
                6: "#IV", 7: "V", 8: "VI", 9: "#VI", 10: "VII", 11: "#VII"}


def _parse_chord_quality(chord: str) -> tuple[int | None, str]:
    """Return (root pitch-class 0-11, quality) for a chord name.

    Prefers the `type` from the chord database; falls back to parsing the name
    suffix so progressions using chords outside the dataset still analyse."""
    root = _chord_root_index(chord)
    if root is None:
        return None, "major"
    db = get_chord(chord.strip())
    if db and db.get("type") in QUALITY_INTERVALS:
        return root, db["type"]
    # Suffix-based fallback: strip the root (1-2 chars) and inspect what's left.
    rest = chord.strip()[1:]
    if rest[:1] in ("#", "b"):
        rest = rest[1:]
    rest = rest.lower()
    if rest in ("dim", "°", "o"):
        quality = "diminished"
    elif rest in ("aug", "+"):
        quality = "augmented"
    elif rest.startswith("maj"):
        quality = "major7" if "7" in rest or "9" in rest else "major"
    elif rest.startswith("m"):
        quality = "minor7" if "7" in rest or "9" in rest else "minor"
    elif rest.startswith("sus2"):
        quality = "sus2"
    elif rest.startswith("sus"):
        quality = "sus4"
    elif rest in ("5",):
        quality = "power"
    elif rest.startswith("add9"):
        quality = "add9"
    elif rest.startswith("7") or rest.startswith("9") or rest.startswith("13"):
        quality = "dominant7"
    else:
        quality = "major"
    return root, quality


def _pearson(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation of two equal-length vectors (0.0 if degenerate)."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return 0.0
    return cov / (vx * vy) ** 0.5


# A real authentic cadence is the strongest possible tonic signal, and unlike the
# pitch-class histogram it is order-aware. This bonus lets a cadential phrase such as
# Dm-G-C (ii-V-I in C) be read as C major rather than G major, which the raw
# histogram prefers. It is large because it encodes hard tonal evidence, yet inert on
# looping progressions (e.g. Am-F-C-G) that contain no linear V→I.
_CADENCE_BONUS = 0.3
# Qualities that can act as a dominant (V) — i.e. carry a major third / leading tone.
_DOMINANT_QUALITIES = {"major", "major7", "dominant7"}


def _infer_key(chord_list: list[str]) -> tuple[int, str] | None:
    """Infer (tonic pitch-class, mode) for a progression via K-S key finding.

    Correlates the progression's pitch-class histogram against all 24 key profiles,
    then nudges candidates that contain an authentic (V→I) cadence to that tonic.
    Returns None if no chord roots are parseable. `mode` is "major" or "minor"."""
    parsed = [(_parse_chord_quality(c)) for c in chord_list]
    parsed = [(r, q) for r, q in parsed if r is not None]
    if not parsed:
        return None
    histogram = [0.0] * 12
    for root, quality in parsed:
        for interval in QUALITY_INTERVALS.get(quality, (0, 4, 7)):
            histogram[(root + interval) % 12] += 1.0
    # Tonics that are the target of an authentic cadence: a dominant-quality chord a
    # perfect fifth (7 semitones) above, immediately resolving down to that root.
    cadence_tonics = {
        rb for (ra, qa), (rb, _) in zip(parsed, parsed[1:])
        if qa in _DOMINANT_QUALITIES and (ra - rb) % 12 == 7
    }
    best: tuple[float, int, str] | None = None
    for tonic in range(12):
        bonus = _CADENCE_BONUS if tonic in cadence_tonics else 0.0
        for mode, profile in (("major", _KS_MAJOR), ("minor", _KS_MINOR)):
            rotated = [profile[(i - tonic) % 12] for i in range(12)]
            score = _pearson(histogram, rotated) + bonus
            if best is None or score > best[0]:
                best = (score, tonic, mode)
    return (best[1], best[2]) if best else None


def _roman_numeral(root: int, quality: str, tonic: int, mode: str) -> str:
    """Roman numeral for a chord root relative to an inferred tonic and mode."""
    interval = (root - tonic) % 12
    base = (_ROMAN_MAJOR if mode == "major" else _ROMAN_MINOR)[interval]
    accidental = ""
    while base and base[0] in "#b":
        accidental += base[0]
        base = base[1:]
    numeral = base.lower() if quality in _MINOR_QUALITIES else base
    symbol = {"diminished": "°", "augmented": "+", "dominant7": "7"}.get(quality, "")
    return accidental + numeral + symbol


def _note_index(note: str) -> int:
    note = ENHARMONICS.get(note, note)
    return NOTE_NAMES.index(note) if note in NOTE_NAMES else 0


def _transpose_chord_name(chord: str, semitones: int) -> str:
    """Shift a single chord name by `semitones`, preserving its quality/suffix.
    Handles slash chords (e.g. 'D/F#') by transposing both parts."""
    chord = chord.strip()
    if not chord:
        return chord
    if "/" in chord:
        base, bass = chord.split("/", 1)
        return f"{_transpose_chord_name(base, semitones)}/{_transpose_chord_name(bass, semitones)}"
    # Root is one letter optionally followed by # or b; the rest is the quality suffix.
    root = chord[0].upper()
    rest = chord[1:]
    if rest[:1] in ("#", "b"):
        root += rest[0]
        suffix = rest[1:]
    else:
        suffix = rest
    idx = _note_index(root)
    if root not in NOTE_NAMES and root not in ENHARMONICS:
        return chord  # not a recognizable chord, leave untouched
    new_root = NOTE_NAMES[(idx + semitones) % 12]
    return new_root + suffix


def _chord_root_index(chord: str) -> int | None:
    """Return the 0-11 pitch-class index of a chord's root, or None if unparseable."""
    chord = chord.strip()
    if not chord:
        return None
    root = chord[0].upper()
    if chord[1:2] in ("#", "b"):
        root += chord[1]
    root = ENHARMONICS.get(root, root)
    return NOTE_NAMES.index(root) if root in NOTE_NAMES else None


def _progression_degrees(chord_list: list[str], tonic: int | None = None) -> list[int]:
    """Map a progression to scale degrees (1-7) relative to a tonic.

    Root-motion based, so it works without knowing the key explicitly. If `tonic`
    is None the first parseable chord is assumed to be the tonic; pass an inferred
    tonic to label off-tonic progressions correctly. Unparseable chords are skipped."""
    roots = [(_chord_root_index(c)) for c in chord_list]
    if tonic is None:
        tonic = next((r for r in roots if r is not None), None)
    if tonic is None:
        return []
    return [_SEMITONE_TO_DEGREE[(r - tonic) % 12] for r in roots if r is not None]


def _contains_subsequence(seq: list[int], sub: list[int]) -> bool:
    """True if `sub` appears as a contiguous run inside `seq`."""
    if not sub or len(sub) > len(seq):
        return False
    return any(seq[i:i + len(sub)] == sub for i in range(len(seq) - len(sub) + 1))


def _build_diatonic_chords(key: str, scale: str = "major") -> list[dict]:
    """Return the diatonic chord names for a given key and scale."""
    root_idx = _note_index(key.replace("m", ""))
    pattern = SCALE_PATTERNS.get(scale, SCALE_PATTERNS["major"])
    chord_types = DIATONIC_CHORD_TYPES.get(scale, DIATONIC_CHORD_TYPES["major"])
    chords = []
    for i, interval in enumerate(pattern[:7]):
        chord_note = NOTE_NAMES[(root_idx + interval) % 12]
        chord_type = chord_types[i] if i < len(chord_types) else "major"
        suffix = CHORD_TYPE_SUFFIXES.get(chord_type, "")
        chords.append({
            "degree": i + 1,
            "roman": ["I", "II", "III", "IV", "V", "VI", "VII"][i],
            "chord": chord_note + suffix,
            "type": chord_type,
        })
    return chords


# ─── LangChain Tools ───────────────────────────────────────────────────────────

@tool
def get_chord_info(chord_name: str) -> str:
    """Get detailed information about a specific guitar chord including fingering positions,
    notes, and difficulty level."""
    chord = get_chord(chord_name.strip())
    if not chord:
        return (
            f"Chord '{chord_name}' not found in the database. "
            "Try common variations like 'Am', 'Cmaj7', 'G7', 'Bm', 'F', etc."
        )
    positions_str = ", ".join(
        ("muted" if p == -1 else ("open" if p == 0 else f"fret {p}"))
        for p in chord["positions"]
    )
    notes_str = ", ".join(chord.get("notes", []))
    theory = THEORY_RULES.get(chord.get("type", "major"), "")
    return (
        f"**{chord['full_name']} ({chord['name']})**\n"
        f"- String positions (E A D G B e): {positions_str}\n"
        f"- Finger numbers: {chord['fingers']}\n"
        f"- Starting fret: {chord.get('base_fret', 1)}\n"
        f"- Notes: {notes_str}\n"
        f"- Difficulty: {chord.get('difficulty', 'unknown')}\n"
        f"- Type: {chord.get('type', 'unknown')}\n"
        f"- Theory: {theory}\n"
    )


@tool
def get_progressions_by_genre_tool(genre: str) -> str:
    """Get chord progressions filtered by musical genre.
    Valid genres: blues, pop, rock, folk, jazz, country, rnb, reggae, indie, classical"""
    results = _filter_by_skill(get_progressions_by_genre(genre))
    if not results:
        return f"No progressions found for genre '{genre}'. Try: blues, pop, rock, folk, jazz, country, rnb"
    lines = [f"Found {len(results)} progressions for genre '{genre}':\n"]
    for p in results[:6]:
        chords_str = " → ".join(p["chords"])
        lines.append(
            f"**{p['name']}** (Key of {p['key']}, {p['difficulty']})\n"
            f"  Chords: {chords_str}\n"
            f"  Roman: {' '.join(p['roman'])}\n"
            f"  Feel: {p['feel']} | ~{p['tempo_bpm']} BPM\n"
            f"  {p['description']}\n"
        )
    return "\n".join(lines)


@tool
def get_progressions_by_key_tool(key: str) -> str:
    """Get chord progressions in a specific musical key.
    Key should be like 'C', 'Am', 'G', 'F#m', 'E', 'A' etc."""
    results = _filter_by_skill(get_progressions_by_key(key))
    if not results:
        return f"No progressions found for key '{key}'. Available keys in the dataset: C, G, D, A, E, Am, Em, Gm, Bb"
    lines = [f"Found {len(results)} progressions in the key of {key}:\n"]
    for p in results[:6]:
        chords_str = " → ".join(p["chords"])
        lines.append(
            f"**{p['name']}** ({', '.join(p['genre'])})\n"
            f"  Chords: {chords_str}\n"
            f"  Feel: {p['feel']}\n"
            f"  {p['description']}\n"
        )
    return "\n".join(lines)


@tool
def get_progressions_by_mood_tool(mood: str) -> str:
    """Get chord progressions that match a musical mood or feel.
    Valid moods: happy, sad, energetic, melancholic, romantic, tense, uplifting, dark"""
    results = _filter_by_skill(get_progressions_by_mood(mood))
    if not results:
        return (
            f"No progressions found for mood '{mood}'. "
            "Try: happy, sad, energetic, melancholic, romantic, tense, uplifting, dark"
        )
    lines = [f"Found {len(results)} {mood} progressions:\n"]
    for p in results[:5]:
        chords_str = " → ".join(p["chords"])
        lines.append(
            f"**{p['name']}** (Key: {p['key']}, {p['difficulty']})\n"
            f"  Chords: {chords_str}\n"
            f"  Feel: {p['feel']}\n"
            f"  {p['description']}\n"
        )
    return "\n".join(lines)


@tool
def explain_theory(chords: str) -> str:
    """Explain the music theory behind a chord progression.
    Pass chord names separated by dashes like 'Am-F-C-G'. Infers the key from the
    whole progression (so off-tonic progressions like Am-F-C-G are correctly read as
    C major, vi-IV-I-V), labels each chord with a Roman numeral, and flags cadences."""
    chord_list = [c.strip() for c in chords.replace(",", "-").split("-") if c.strip()]
    if not chord_list:
        return "Please provide chords separated by dashes, e.g. 'Am-F-C-G'"

    lines = [f"## Theory breakdown: {' → '.join(chord_list)}\n"]

    # Infer the key from the whole progression (not just the first chord) so that
    # off-tonic progressions are labelled correctly — e.g. Am-F-C-G is read as
    # C major (vi-IV-I-V), not A minor.
    key = _infer_key(chord_list)
    tonic = key[0] if key else None
    if key:
        tonic, mode = key
        romans = []
        for chord_name in chord_list:
            root, quality = _parse_chord_quality(chord_name)
            romans.append(_roman_numeral(root, quality, tonic, mode) if root is not None else "?")
        lines.append(f"**Detected key:** {NOTE_NAMES[tonic]} {mode}")
        lines.append(f"**Roman numerals:** {' → '.join(romans)}\n")

    # Describe each chord's character
    lines.append("### Chord characters:")
    for chord_name in chord_list:
        chord = get_chord(chord_name)
        if chord:
            theory = THEORY_RULES.get(chord.get("type", "major"), "")
            lines.append(f"- **{chord_name}** ({chord.get('type', 'major')}): {theory}")
        else:
            lines.append(f"- **{chord_name}**: Unknown chord type")

    # Identify common patterns by root motion (degree sequence relative to the
    # inferred tonic, falling back to the first chord when inference fails).
    degrees = _progression_degrees(chord_list, tonic)
    patterns_found = []
    for pattern, degree_seq in TENSION_RESOLUTION_DEGREES.items():
        if _contains_subsequence(degrees, degree_seq):
            patterns_found.append(f"- {TENSION_RESOLUTION[pattern]}")
    if patterns_found:
        lines.append("\n### Progression patterns detected:")
        lines.extend(patterns_found)

    # Minor vs major analysis
    minor_count = sum(1 for c in chord_list if get_chord(c) and get_chord(c).get("type") in ("minor", "minor7", "minor9"))
    major_count = sum(1 for c in chord_list if get_chord(c) and get_chord(c).get("type") in ("major", "major7", "major9", "add9"))
    total = len(chord_list)

    if minor_count > major_count:
        lines.append(
            f"\n### Overall character: **Minor-heavy** ({minor_count}/{total} minor chords)\n"
            "This progression will feel melancholic, introspective, and emotionally complex."
        )
    elif major_count > minor_count:
        lines.append(
            f"\n### Overall character: **Major-heavy** ({major_count}/{total} major chords)\n"
            "This progression will feel bright, uplifting, and resolved."
        )
    else:
        lines.append("\n### Overall character: **Balanced** — mix of major and minor gives it emotional nuance.")

    # V→I resolution detection
    for i in range(len(chord_list) - 1):
        c1, c2 = get_chord(chord_list[i]), get_chord(chord_list[i + 1])
        if c1 and c2 and c1.get("type") in ("dominant7",) and c2.get("type") in ("major", "minor"):
            lines.append(f"\n- **{chord_list[i]}→{chord_list[i+1]}**: Strong dominant resolution (V7→I) — creates a powerful sense of arrival.")

    lines.append("\n### Practice tip:")
    lines.append(
        "Focus on smooth voice leading between chords — identify which fingers can stay in place "
        "or move minimally between each chord change."
    )

    return "\n".join(lines)


@tool
def get_scale_chords(scale: str, key: str = "") -> str:
    """Get all diatonic chords that belong to a given scale in a given key.
    Provide scale and key as separate arguments: scale='major', key='G'.
    Returns the diatonic chord set, e.g. G, Am, Bm, C, D, Em, F#dim."""
    # Model sometimes combines both into the scale param, e.g. "major, G" or "major G"
    scale = scale.strip()
    if not key and ("," in scale or " " in scale):
        parts = scale.replace(",", " ").split()
        if len(parts) >= 2:
            scale, key = parts[0], parts[1]
    scale = scale.lower()
    key = key.strip()
    if not key:
        return "Please provide a key, e.g. scale='major', key='G'"
    if scale not in SCALE_PATTERNS:
        return f"Unknown scale '{scale}'. Try: major, minor, pentatonic, blues, dorian, mixolydian"

    diatonic = _build_diatonic_chords(key, scale)
    if not diatonic:
        return f"Could not build scale for key '{key}'"

    lines = [f"## Diatonic chords in {key} {scale}:\n"]
    for chord_info in diatonic:
        roman = chord_info["roman"]
        if chord_info["type"] == "minor":
            roman = roman.lower()
        elif chord_info["type"] == "diminished":
            roman = roman.lower() + "°"
        avail = chord_info["chord"] in CHORDS
        avail_note = " ✓ (diagram available)" if avail else ""
        lines.append(
            f"- **{roman}** — {chord_info['chord']} ({chord_info['type']}){avail_note}"
        )

    lines.append(
        f"\nThese {len(diatonic)} chords are all 'in key' — they naturally sound good together "
        f"because they share notes from the {key} {scale} scale."
    )
    return "\n".join(lines)


@tool
def suggest_next_chord(current_chords: str, style: str = "general") -> str:
    """Suggest what chord could come next in a progression based on music theory.
    Pass current chords as comma-separated or dash-separated string."""
    chord_list = [c.strip() for c in current_chords.replace("-", ",").split(",") if c.strip()]
    if not chord_list:
        return "Please provide at least one chord, e.g. 'Am, F' or 'Am-F-C'"

    last = chord_list[-1]
    last_data = get_chord(last)
    suggestions = []

    # Simple music-theory–based suggestions
    if last_data:
        chord_type = last_data.get("type", "major")
        if chord_type == "dominant7":
            suggestions.append({"chord": "resolution to the tonic", "reason": "V7 chords strongly want to resolve to the I (tonic) chord."})
        elif chord_type in ("major",):
            suggestions.extend([
                {"chord": "IV chord (subdominant)", "reason": "Moving from I to IV is one of the most natural chord movements in music."},
                {"chord": "V chord (dominant)", "reason": "I→V creates forward momentum that wants to resolve back to I."},
                {"chord": "vi chord (relative minor)", "reason": "I→vi is a very common move in pop music — adds emotional depth."},
            ])
        elif chord_type in ("minor", "minor7"):
            suggestions.extend([
                {"chord": "bVII chord", "reason": "Moving from i to bVII (borrowed from parallel major) creates a rock/folk sound."},
                {"chord": "bVI chord", "reason": "i→bVI is melancholic and lyrical — common in minor-key ballads."},
                {"chord": "V chord (major dominant)", "reason": "The V chord (major even in minor keys) creates tension that resolves back to i."},
            ])

    # Find progressions that contain the last chord and see what follows
    follow_up_chords: dict[str, int] = {}
    for prog in PROGRESSIONS:
        prog_chords = prog["chords"]
        for i, c in enumerate(prog_chords[:-1]):
            if c == last and i + 1 < len(prog_chords):
                next_c = prog_chords[i + 1]
                follow_up_chords[next_c] = follow_up_chords.get(next_c, 0) + 1

    lines = [f"## After **{last}**, consider:\n"]
    lines.append("### Theory-based suggestions:")
    for s in suggestions[:3]:
        lines.append(f"- {s['chord']}: {s['reason']}")

    if follow_up_chords:
        sorted_chords = sorted(follow_up_chords.items(), key=lambda x: -x[1])[:4]
        lines.append("\n### Most common in real progressions:")
        for chord_name, count in sorted_chords:
            lines.append(f"- **{chord_name}** (appears {count} time(s) after {last} in our dataset)")

    lines.append(
        f"\n*Tip: Try playing {last} and each suggestion back-to-back to hear what resonates with the feel you're going for.*"
    )
    return "\n".join(lines)


# ─── New tools ────────────────────────────────────────────────────────────────

_FINGER_NAMES = {1: "index finger", 2: "middle finger", 3: "ring finger", 4: "pinky"}
_STRING_NAMES = ["low E (6th)", "A (5th)", "D (4th)", "G (3rd)", "B (2nd)", "high e (1st)"]


@tool
def find_song_chords(song_title: str, artist: str) -> str:
    """Look up the ACTUAL chord progression a specific real song uses.

    Use this whenever a user asks to play, learn, or get the chords for a named
    song (e.g. "how do I play Sailor Song by Gigi Perez", "chords for Wonderwall").
    Chord progressions are NOT protected by copyright, so it is fine to report the
    real chords, key, and capo position a song uses — just do not paste full
    tablature or copyrighted lyrics. Works for recent songs too (live web search).

    Args:
        song_title: The name of the song (e.g. 'Sailor Song')
        artist: The artist name (e.g. 'Gigi Perez')
    """
    # Query the pages that actually publish chord data (Ultimate Guitar, Chordify,
    # etc.). The previous version excluded these with "-tabs -chords", which is why
    # recommendations were generic instead of the song's real progression.
    queries = [
        f"{song_title} {artist} chords progression",
        f"{song_title} {artist} guitar chords capo key",
        f"what key is {song_title} by {artist} in",
    ]

    # Run the queries concurrently — each _web_search fans out to several DDGS
    # backends, so doing them sequentially was the dominant source of latency.
    def _run(q: str) -> str:
        try:
            return _web_search(q, max_results=5)
        except Exception:
            return ""

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        results = list(pool.map(_run, queries))

    chunks = [
        f"### Results for: {q}\n{result}"
        for q, result in zip(queries, results)
        if result
    ]
    if not chunks:
        return (
            "Live web search is unavailable right now, so I can't confirm this "
            f"song's exact chords. If you know the key of '{song_title}', tell me and "
            "I'll lay out the progression; otherwise I can suggest a progression with "
            "a similar feel (clearly labelled as an approximation, not the real song)."
        )

    raw = "\n\n".join(chunks)[:3000]
    return (
        f"## Chord-progression search results for '{song_title}' by {artist}\n\n"
        f"{raw}\n\n"
        "--- HOW TO USE THIS ---\n"
        "1. Extract the song's ACTUAL chords and original key from the results above "
        "(look for agreement across multiple sources; chord progressions are not "
        "copyrighted, so report the real ones).\n"
        "2. If the original key uses barre chords and the user is a beginner, call "
        "transpose_chords to provide a capo version that uses open shapes, and state "
        "the capo fret.\n"
        "3. If the results genuinely don't reveal the chords, say so honestly and only "
        "THEN offer a similar-feel progression — but label it clearly as an "
        "approximation, never as the song's real chords.\n"
        "4. Do not paste full tablature or lyrics — the chord sequence and key are enough."
    )


@tool
def transpose_chords(chords: str, semitones: int = 0, capo_fret: int = 0) -> str:
    """Transpose a chord progression, or compute the shapes to play with a capo.

    Use this to turn a song's real-key progression (which may need barre chords)
    into beginner-friendly open chords. A capo on fret N means you finger shapes
    that are N semitones LOWER than the sounding chords.

    Examples:
      - transpose_chords('E,G#m,B', capo_fret=4)  -> shapes 'C, Em, G' (sounds like E,G#m,B)
      - transpose_chords('C,Am,F,G', semitones=2) -> 'D, Bm, G, A'

    Args:
        chords: Comma- or dash-separated chord names (e.g. 'E,G#m,B').
        semitones: Direct transposition amount (positive = up, negative = down).
        capo_fret: If > 0, returns the shapes to FINGER with a capo at this fret
                   (overrides semitones by transposing the progression down capo_fret).
    """
    chord_list = [c.strip() for c in chords.replace("-", ",").split(",") if c.strip()]
    if not chord_list:
        return "Please provide chords, e.g. 'E,G#m,B'"

    shift = -capo_fret if capo_fret > 0 else semitones
    transposed = [_transpose_chord_name(c, shift) for c in chord_list]

    if capo_fret > 0:
        beginner_friendly = [t for t in transposed if t in CHORDS]
        note = ""
        if len(beginner_friendly) == len(transposed):
            note = " — all of these are available as open-chord shapes ✓"
        return (
            f"## Capo on fret {capo_fret}\n"
            f"Sounding chords: **{' → '.join(chord_list)}**\n"
            f"Shapes to finger (with capo at fret {capo_fret}): **{' → '.join(transposed)}**{note}\n\n"
            f"With the capo clamped at fret {capo_fret}, playing these easier shapes "
            f"produces the original chords — same song, same key, simpler fingering."
        )

    direction = f"up {semitones}" if semitones > 0 else f"down {abs(semitones)}"
    return (
        f"## Transposed {direction} semitone(s)\n"
        f"Original: **{' → '.join(chord_list)}**\n"
        f"Transposed: **{' → '.join(transposed)}**"
    )


@tool
def get_finger_placement_guide(chord_name: str, from_chord: str = "", to_chord: str = "") -> str:
    """Generate a natural-language step-by-step finger placement tutorial for a chord.
    Optionally include transition tips by providing from_chord or to_chord.

    Args:
        chord_name: The chord to explain (e.g. 'F', 'Bm', 'Cmaj7')
        from_chord: Optional chord the player is transitioning FROM (e.g. 'C')
        to_chord: Optional chord the player is transitioning TO (e.g. 'G')
    """
    chord = get_chord(chord_name.strip())
    if not chord:
        return f"Chord '{chord_name}' not found. Try 'Am', 'F', 'Bm', 'Cmaj7', etc."

    positions = chord["positions"]
    fingers = chord["fingers"]
    base_fret = chord.get("base_fret", 1)
    barre = chord.get("barre")

    lines = [f"## How to play {chord['full_name']} ({chord_name})\n"]
    lines.append("**Finger numbers:** Index=1, Middle=2, Ring=3, Pinky=4  |  0 = open string  |  X = mute\n")

    if base_fret > 1:
        lines.append(f"Position your hand starting at fret {base_fret}.\n")

    step = 1
    if barre:
        fname = _FINGER_NAMES.get(barre["finger"], f"finger {barre['finger']}")
        from_s = _STRING_NAMES[barre["from_string"]]
        to_s = _STRING_NAMES[barre["to_string"]]
        lines.append(f"### Step {step} — Barre")
        lines.append(
            f"Lay your {fname} flat across strings {from_s} through {to_s} at fret {barre['fret']}. "
            "Press firmly — rotate the finger slightly toward the nut for a cleaner barre."
        )
        step += 1

    lines.append(f"\n### Step {step} — Individual fingers")
    for i, (pos, fing) in enumerate(zip(positions, fingers)):
        sname = _STRING_NAMES[i]
        if pos == -1:
            lines.append(f"- **{sname}**: Mute (lightly touch with thumb or adjacent finger)")
        elif pos == 0:
            lines.append(f"- **{sname}**: Open — no finger needed")
        else:
            fname = _FINGER_NAMES.get(fing, f"finger {fing}")
            lines.append(f"- **{sname}**: Place your {fname} at fret {pos}")

    lines.append("\n### Common mistakes")
    if barre:
        lines.append("- Barre not ringing — rotate index toward the nut and check thumb position (centered on back of neck)")
    lines.append("- Fingers muting adjacent strings — curve each finger more at the middle knuckle")
    lines.append("- Pressing too far from the fret wire — aim for just behind it")
    lines.append("\n### Check your chord")
    lines.append("Pluck each string individually. Any buzzing = adjust pressure or finger position.")

    if from_chord:
        fc = get_chord(from_chord.strip())
        if fc:
            shared = [i for i, (p1, p2) in enumerate(zip(fc["positions"], positions)) if p1 == p2 and p1 > 0]
            lines.append(f"\n### Transitioning FROM {from_chord}")
            if shared:
                lines.append(f"Keep these fingers anchored (they don't move): **{', '.join(_STRING_NAMES[i] for i in shared)}**")
            else:
                lines.append("No shared finger positions — lift all fingers together and set the new shape as a unit.")

    if to_chord:
        tc = get_chord(to_chord.strip())
        if tc:
            shared = [i for i, (p1, p2) in enumerate(zip(positions, tc["positions"])) if p1 == p2 and p1 > 0]
            lines.append(f"\n### Transitioning TO {to_chord}")
            if shared:
                lines.append(f"Anchor fingers: **{', '.join(_STRING_NAMES[i] for i in shared)}**")

    return "\n".join(lines)


@tool
def log_practice_session(name: str, chords: str, item_type: str = "progression") -> str:
    """Record that the user just practiced a progression, looked up a song, or studied a chord.
    Call this once per response whenever you recommend a progression the user engages with.

    Args:
        name: Human-readable label (e.g. 'Am-F-C-G', 'Wonderwall feel', 'F chord tutorial')
        chords: Comma-separated chord names (e.g. 'Am,F,C,G')
        item_type: One of 'progression', 'song_search', 'chord'
    """
    sid = _current_session_id.get("")
    if not sid:
        return "Practice log unavailable."
    from agent.memory import log_practice_item
    chord_list = [c.strip() for c in chords.split(",") if c.strip()]
    log_practice_item(sid, {"type": item_type, "name": name, "chords": chord_list})
    return f"Logged '{name}' to your practice session."


@tool
def get_practice_log() -> str:
    """Retrieve the user's practice history for this session.
    Use when the user asks 'what have I been practicing?' or 'show my history'.
    """
    sid = _current_session_id.get("")
    if not sid:
        return "No practice history available."
    from agent.memory import get_session_data
    log = get_session_data(sid).get("practice_log", [])
    if not log:
        return "You haven't practiced anything yet this session. Ask me for a progression to get started!"
    lines = ["## Your practice log this session:\n"]
    for i, item in enumerate(reversed(log[-10:]), 1):
        age_min = round((_time.time() - item.get("timestamp", _time.time())) / 60)
        age_str = "just now" if age_min < 1 else f"{age_min}m ago"
        chords_str = " → ".join(item["chords"]) if item.get("chords") else "–"
        lines.append(f"{i}. **{item['name']}** ({item.get('type', 'progression')}) — {chords_str} [{age_str}]")
    return "\n".join(lines)


@tool
def search_music_theory(query: str) -> str:
    """Search the curated music-theory knowledge base for passages relevant to a
    conceptual theory question (scales, modes, harmonic function, voice leading,
    capo/transposition, strumming/fingerpicking technique, etc.).

    Use this to ground conceptual explanations in the corpus instead of answering
    purely from your own knowledge. Not for analyzing a SPECIFIC chord progression
    the user gave you — use explain_theory for that — and not for chord fingerings
    or the progression dataset — use get_chord_info / get_progressions_* for those.

    Args:
        query: The theory question or concept to search for, e.g. 'circle of fifths'.
    """
    from rag.retrieval import search_corpus

    try:
        results = search_corpus(query)
    except RuntimeError as exc:
        return f"Knowledge-base search is unavailable right now: {exc}"

    if not results:
        return "No relevant passages found in the knowledge base for this query."

    lines = ["## Relevant knowledge-base passages:\n"]
    for r in results:
        citation = f" ({r['url']})" if r.get("url") else ""
        lines.append(f"### {r['title']}{citation}\n{r['content']}\n")
    return "\n".join(lines)


@tool
def set_user_skill_level(level: str) -> str:
    """Set the user's guitar skill level so chord suggestions can be adapted to their ability.
    Call this when the user mentions their experience level or when context implies it.

    Args:
        level: One of 'beginner', 'intermediate', 'advanced'
    """
    sid = _current_session_id.get("")
    level = level.lower().strip()
    valid = {"beginner", "intermediate", "advanced"}
    if level not in valid:
        return f"Invalid level '{level}'. Must be beginner, intermediate, or advanced."
    if sid:
        from agent.memory import set_skill_level
        set_skill_level(sid, level)
    tips = {
        "beginner": "I'll stick to open chords (Em, Am, G, C, D, A) — no barre chords.",
        "intermediate": "I'll include barre chords (F, Bm) and 7th chords in my suggestions.",
        "advanced": "Full range: jazz voicings, extended chords, and modal progressions are all fair game.",
    }
    return f"Got it! Tailoring suggestions for a **{level}** player. {tips[level]}"


# Export the tool list for the agent
TOOLS = [
    get_chord_info,
    get_progressions_by_genre_tool,
    get_progressions_by_key_tool,
    get_progressions_by_mood_tool,
    explain_theory,
    get_scale_chords,
    suggest_next_chord,
    find_song_chords,
    transpose_chords,
    get_finger_placement_guide,
    log_practice_session,
    get_practice_log,
    set_user_skill_level,
    search_music_theory,
]
