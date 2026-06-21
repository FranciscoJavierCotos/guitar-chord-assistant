"""
The structured-output (`AgentAction`) contract, mirrored on the backend so the
eval harness can verify it without a browser.

This must stay in sync with ``frontend/lib/types.ts`` (the ``AgentAction``
interface) and ``frontend/lib/agentAction.ts`` (the trailing ```json block
parser). The agent's system prompt in ``agent/coach_agent.py`` is the other half
of the contract. Breaking any of the three breaks the chord diagram panel.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

# The set of valid `action` values. `show_practice_log` exists in types.ts but
# the agent never emits it via the trailing block, so all three are accepted.
VALID_ACTIONS = {"show_chords", "show_chord", "show_practice_log"}

# Mirror of frontend/lib/agentAction.ts: grab the trailing fenced json block that
# contains an "action" key. Kept deliberately identical so the harness fails on
# exactly the blocks the browser would fail on.
_ACTION_BLOCK = re.compile(r'```json\s*(\{[\s\S]*?"action"\s*:[\s\S]*?\})\s*```')


@dataclass
class AgentAction:
    action: str
    chords: list[str] | None = None
    chord: str | None = None
    progression_name: str | None = None
    bpm_suggestion: int | None = None
    message: str | None = None

    def referenced_chords(self) -> list[str]:
        """Every chord name the action asks the frontend to render."""
        names: list[str] = []
        if self.chord:
            names.append(self.chord)
        if self.chords:
            names.extend(self.chords)
        return [c.strip() for c in names if isinstance(c, str) and c.strip()]


def extract_action_block(text: str) -> str | None:
    """Return the raw JSON string of the trailing action block, or None."""
    match = _ACTION_BLOCK.search(text or "")
    return match.group(1) if match else None


def parse_agent_action(text: str) -> AgentAction | None:
    """Parse the trailing ```json action block out of an agent response.

    Returns None when there is no well-formed block (no fence, no `"action"`
    key, invalid JSON, or an unknown action value) — exactly the cases where the
    frontend would render the message text unchanged with no chord panel update.
    """
    raw = extract_action_block(text)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    action = data.get("action")
    if action not in VALID_ACTIONS:
        return None
    chords = data.get("chords")
    if chords is not None and not (
        isinstance(chords, list) and all(isinstance(c, str) for c in chords)
    ):
        return None
    bpm = data.get("bpm_suggestion")
    if bpm is not None and not isinstance(bpm, (int, float)):
        return None
    return AgentAction(
        action=action,
        chords=chords,
        chord=data.get("chord") if isinstance(data.get("chord"), str) else None,
        progression_name=data.get("progression_name")
        if isinstance(data.get("progression_name"), str)
        else None,
        bpm_suggestion=int(bpm) if isinstance(bpm, (int, float)) else None,
        message=data.get("message") if isinstance(data.get("message"), str) else None,
    )
