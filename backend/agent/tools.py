"""
LangChain tools for the ChordCoach agent.
All tools use the local chord/progression dataset — no external API calls.
"""

from langchain_core.tools import tool

from data.chords import CHORDS, get_chord
from data.progressions import (
    PROGRESSIONS,
    get_progressions_by_genre,
    get_progressions_by_key,
    get_progressions_by_mood,
)

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


def _note_index(note: str) -> int:
    note = ENHARMONICS.get(note, note)
    return NOTE_NAMES.index(note) if note in NOTE_NAMES else 0


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
    results = get_progressions_by_genre(genre)
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
    results = get_progressions_by_key(key)
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
    results = get_progressions_by_mood(mood)
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
    Pass chord names separated by dashes like 'Am-F-C-G'"""
    chord_list = [c.strip() for c in chords.replace(",", "-").split("-") if c.strip()]
    if not chord_list:
        return "Please provide chords separated by dashes, e.g. 'Am-F-C-G'"

    lines = [f"## Theory breakdown: {' → '.join(chord_list)}\n"]

    # Describe each chord's character
    lines.append("### Chord characters:")
    for chord_name in chord_list:
        chord = get_chord(chord_name)
        if chord:
            theory = THEORY_RULES.get(chord.get("type", "major"), "")
            lines.append(f"- **{chord_name}** ({chord.get('type', 'major')}): {theory}")
        else:
            lines.append(f"- **{chord_name}**: Unknown chord type")

    # Identify common patterns
    lines.append("\n### Progression patterns detected:")
    chord_str = "-".join(chord_list)
    patterns_found = []
    for pattern, explanation in TENSION_RESOLUTION.items():
        parts = pattern.split("-")
        if len(parts) <= len(chord_list):
            found = any(
                all(chord_list[i + j] in (parts[j], chord_list[i + j])
                    for j in range(len(parts)))
                for i in range(len(chord_list) - len(parts) + 1)
            )
        if "I-V-vi-IV" in chord_str or pattern in chord_str:
            patterns_found.append(f"- {explanation}")

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

    if patterns_found:
        lines.extend(patterns_found)

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


# Export the tool list for the agent
TOOLS = [
    get_chord_info,
    get_progressions_by_genre_tool,
    get_progressions_by_key_tool,
    get_progressions_by_mood_tool,
    explain_theory,
    get_scale_chords,
    suggest_next_chord,
]
