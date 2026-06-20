"""Pytest configuration for the backend.

Placing this file at the backend root puts `backend/` on sys.path during test
collection, so tests can `import agent.coach_agent` regardless of the directory
pytest is invoked from.
"""
