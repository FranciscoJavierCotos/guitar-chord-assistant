"""
Offline evaluation harness for the ChordCoach agent.

Runs a versioned golden set of prompts through the agent and scores each
response, combining cheap deterministic graders (the objective `AgentAction`
contract, no hallucinated chords, key/constraint adherence) with an
LLM-as-judge for the subjective dimensions (musical correctness, relevance,
explanation quality).

Entry point: ``python -m eval`` (see ``eval/__main__.py`` / ``eval/runner.py``).
"""
