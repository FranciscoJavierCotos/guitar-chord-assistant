"""
Tests for the in-process session store (agent/memory.py).

The MVP deliberately has no database, so this dict-with-TTL *is* the persistence
layer. The behaviours that matter: TTL eviction, the practice-log cap, skill-level
validation, and session lifecycle. Time is faked so eviction is deterministic.
"""

import pytest

from agent import memory


@pytest.fixture(autouse=True)
def clean_sessions():
    """Each test starts from an empty store (the dict is module-global state)."""
    memory._sessions.clear()
    yield
    memory._sessions.clear()


@pytest.fixture
def frozen_time(monkeypatch):
    """Controllable clock for memory.time.time()."""
    clock = {"now": 1_000_000.0}
    monkeypatch.setattr(memory.time, "time", lambda: clock["now"])
    return clock


class TestSessionLifecycle:
    def test_get_history_creates_then_reuses_same_object(self):
        h1 = memory.get_history("s1")
        h2 = memory.get_history("s1")
        assert h1 is h2
        assert memory.session_count() == 1

    def test_distinct_sessions_are_isolated(self):
        memory.get_history("a")
        memory.get_history("b")
        assert memory.session_count() == 2

    def test_clear_memory_removes_existing_session(self):
        memory.get_history("s1")
        assert memory.clear_memory("s1") is True
        assert memory.session_count() == 0

    def test_clear_memory_on_unknown_session_returns_false(self):
        assert memory.clear_memory("ghost") is False


class TestTTLEviction:
    def test_session_older_than_ttl_is_evicted(self, frozen_time):
        memory.get_history("old")
        # Jump past the TTL, then touch the store via a fresh session.
        frozen_time["now"] += memory.SESSION_TTL_SECONDS + 1
        memory.get_history("new")
        assert "old" not in memory._sessions
        assert "new" in memory._sessions

    def test_recently_used_session_survives(self, frozen_time):
        memory.get_history("keep")
        frozen_time["now"] += memory.SESSION_TTL_SECONDS - 1
        memory.get_history("other")
        assert "keep" in memory._sessions

    def test_get_history_refreshes_last_used(self, frozen_time):
        memory.get_history("s1")
        # Advance almost to expiry, then touch s1 to refresh its timestamp.
        frozen_time["now"] += memory.SESSION_TTL_SECONDS - 1
        memory.get_history("s1")
        # Advance again by the same amount; s1 should still be alive because it
        # was refreshed, not stuck at its creation time.
        frozen_time["now"] += memory.SESSION_TTL_SECONDS - 1
        memory.get_history("trigger")
        assert "s1" in memory._sessions


class TestPracticeLog:
    def test_log_item_is_appended_with_timestamp(self, frozen_time):
        memory.get_history("s1")
        memory.log_practice_item("s1", {"type": "chord", "name": "F", "chords": ["F"]})
        log = memory.get_session_data("s1")["practice_log"]
        assert len(log) == 1
        assert log[0]["name"] == "F"
        assert log[0]["timestamp"] == frozen_time["now"]

    def test_log_is_capped_keeping_newest(self):
        memory.get_history("s1")
        for i in range(memory._PRACTICE_LOG_MAX + 10):
            memory.log_practice_item("s1", {"type": "chord", "name": str(i), "chords": []})
        log = memory.get_session_data("s1")["practice_log"]
        assert len(log) == memory._PRACTICE_LOG_MAX
        # Oldest entries dropped; the most recent one is retained.
        assert log[-1]["name"] == str(memory._PRACTICE_LOG_MAX + 10 - 1)

    def test_logging_to_unknown_session_is_a_noop(self):
        memory.log_practice_item("ghost", {"type": "chord", "name": "F", "chords": []})
        assert memory.session_count() == 0

    def test_get_session_data_defaults_for_unknown_session(self):
        data = memory.get_session_data("ghost")
        assert data == {"practice_log": [], "skill_level": "beginner"}


class TestSkillLevel:
    def test_new_session_defaults_to_beginner(self):
        memory.get_history("s1")
        assert memory.get_session_data("s1")["skill_level"] == "beginner"

    def test_set_valid_level(self):
        memory.get_history("s1")
        memory.set_skill_level("s1", "advanced")
        assert memory.get_session_data("s1")["skill_level"] == "advanced"

    def test_set_level_is_case_insensitive(self):
        memory.get_history("s1")
        memory.set_skill_level("s1", "Intermediate")
        assert memory.get_session_data("s1")["skill_level"] == "intermediate"

    def test_invalid_level_is_ignored(self):
        memory.get_history("s1")
        memory.set_skill_level("s1", "wizard")
        assert memory.get_session_data("s1")["skill_level"] == "beginner"
