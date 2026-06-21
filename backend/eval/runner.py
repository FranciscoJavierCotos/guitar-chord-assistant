"""
Eval runner: execute the golden set through the agent, grade each response with
the deterministic graders (and, unless disabled, the LLM judge), aggregate
per-grader pass rates, write a JSON report, and print a human summary.

Run it with ``python -m eval`` (see ``eval/__main__.py`` for the CLI). The
process exits non-zero when the aggregate deterministic pass rate falls below
``--threshold`` (or, with the judge enabled, the judge pass rate below
``--judge-threshold``) so a regression blocks a merge / surfaces loudly in CI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage

from eval.cases import EvalCase, load_cases
from eval.graders.deterministic import run_deterministic
from eval.graders.judge import JudgeConfig, judge_response

DEFAULT_THRESHOLD = 0.85
DEFAULT_JUDGE_THRESHOLD = 0.80
REPORTS_DIR = Path(__file__).parent / "reports"
# backend/.env — the agent (and, by default, the judge) read DEEPSEEK_API_KEY from
# the environment; load it from the backend .env so a local run doesn't need the
# key exported by hand. Real env vars (e.g. the CI secret) always take precedence.
ENV_PATH = Path(__file__).parent.parent / ".env"


def _load_env() -> None:
    """Best-effort load of backend/.env without overriding real env vars.

    No-op if python-dotenv isn't installed or the file is absent — in CI the key
    comes from the job's env, not a committed file."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(dotenv_path=ENV_PATH, override=False)


def _seed_history(case: EvalCase) -> InMemoryChatMessageHistory:
    history = InMemoryChatMessageHistory()
    for turn in case.history:
        role = (turn.get("role") or "").lower()
        content = turn.get("content", "")
        if role in ("user", "human"):
            history.add_message(HumanMessage(content=content))
        elif role in ("assistant", "ai"):
            history.add_message(AIMessage(content=content))
    return history


async def _generate(case: EvalCase) -> str:
    # Imported lazily so deterministic-only / offline tooling doesn't require the
    # agent stack or a configured API key at import time.
    from agent.coach_agent import run_agent

    history = _seed_history(case)
    return await run_agent(
        message=case.prompt,
        history=history,
        context=case.context,
        session_id=f"eval-{case.id}-{uuid.uuid4().hex[:8]}",
    )


def _agent_error(response: str) -> str | None:
    """Return the agent's error text if ``response`` is run_agent's infrastructure
    fallback (bad API key, network, provider outage…), else ``None``.

    This distinguishes "the agent never answered" from "the agent answered badly":
    the former is an environment/credential problem, not a content regression, and
    must not be scored as a 0% content failure. Anchored on the same constant the
    agent builds its fallback from, so wording changes can't silently desync."""
    from agent.coach_agent import AGENT_ERROR_PREFIX

    return response.strip() if response.lstrip().startswith(AGENT_ERROR_PREFIX) else None


async def _run_case(case: EvalCase, use_judge: bool, judge_config: JudgeConfig) -> dict:
    response = await _generate(case)
    error = _agent_error(response)
    deterministic = run_deterministic(case, response)
    record: dict = {
        "id": case.id,
        "tags": case.tags,
        "prompt": case.prompt,
        "response": response,
        "errored": error is not None,
        "error": error,
        "deterministic": [asdict(r) for r in deterministic],
        "deterministic_passed": all(r.passed for r in deterministic),
    }
    # An errored case carries no content signal — skip the judge (it would only
    # spend an LLM call grading an error string) and let _aggregate exclude it.
    if use_judge and error is None:
        judged = await judge_response(case, response, judge_config)
        record["judge"] = {
            "scores": judged.scores,
            "mean_score": judged.mean_score,
            "passed": judged.passed,
            "rationale": judged.rationale,
            "error": judged.error,
        }
    return record


async def run_eval(
    cases: list[EvalCase],
    use_judge: bool = True,
    judge_config: JudgeConfig | None = None,
    concurrency: int = 4,
) -> dict:
    judge_config = judge_config or JudgeConfig()
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _guarded(case: EvalCase) -> dict:
        async with semaphore:
            return await _run_case(case, use_judge, judge_config)

    case_records = await asyncio.gather(*(_guarded(c) for c in cases))
    return _aggregate(case_records, use_judge, judge_config)


def _aggregate(case_records: list[dict], use_judge: bool, judge_config: JudgeConfig) -> dict:
    # Errored cases (agent never answered — bad key, network, provider outage)
    # carry no content signal, so they're excluded from the content metrics and
    # reported on their own. Scoring them as content failures is what masks the
    # real root cause.
    errored = [r for r in case_records if r.get("errored")]
    scored = [r for r in case_records if not r.get("errored")]

    # Per-grader pass rate across every (non-errored) case the grader applied to.
    per_grader: dict[str, dict[str, int]] = {}
    for rec in scored:
        for g in rec["deterministic"]:
            stats = per_grader.setdefault(g["name"], {"passed": 0, "total": 0})
            stats["total"] += 1
            stats["passed"] += 1 if g["passed"] else 0

    grader_rates = {
        name: round(s["passed"] / s["total"], 4) if s["total"] else 1.0
        for name, s in per_grader.items()
    }
    det_pass = sum(1 for r in scored if r["deterministic_passed"])
    total = len(case_records)
    scored_total = len(scored)
    summary: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_cases": total,
        "errored_cases": len(errored),
        "scored_cases": scored_total,
        # Pass rate is over cases that actually produced an answer; an all-errored
        # run reports 0 scored cases rather than a misleading 0% pass rate.
        "deterministic_pass_rate": round(det_pass / scored_total, 4) if scored_total else 1.0,
        "deterministic_cases_passed": det_pass,
        "per_grader_pass_rate": grader_rates,
        "use_judge": use_judge,
    }
    if use_judge:
        judged = [r for r in scored if r.get("judge")]
        judge_passed = sum(1 for r in judged if r["judge"]["passed"])
        scored = [r["judge"]["mean_score"] for r in judged if r["judge"]["scores"]]
        summary["judge_config"] = judge_config.as_metadata()
        summary["judge_pass_rate"] = round(judge_passed / len(judged), 4) if judged else 1.0
        summary["judge_cases_passed"] = judge_passed
        summary["judge_mean_score"] = round(sum(scored) / len(scored), 2) if scored else 0.0
    return {"summary": summary, "cases": case_records}


def print_summary(report: dict) -> None:
    s = report["summary"]
    print("\n=== ChordCoach eval summary ===")
    print(f"cases: {s['total_cases']}")
    errored = s.get("errored_cases", 0)
    if errored:
        # Loud banner: the agent didn't answer these — an environment problem,
        # not a content regression. Don't let it hide under the content metrics.
        print(
            f"\n  !! {errored}/{s['total_cases']} case(s) ERRORED before producing an "
            "answer (agent unreachable / auth / network — check DEEPSEEK_API_KEY)."
        )
    print(
        f"deterministic: {s['deterministic_cases_passed']}/{s['scored_cases']} "
        f"scored cases passed ({s['deterministic_pass_rate']:.0%})"
    )
    for name, rate in sorted(s["per_grader_pass_rate"].items()):
        print(f"  - {name:<22} {rate:.0%}")
    if s.get("use_judge"):
        print(
            f"judge ({s['judge_config']['model']}): "
            f"{s['judge_cases_passed']}/{s['scored_cases']} cases passed "
            f"({s['judge_pass_rate']:.0%}), mean score {s['judge_mean_score']}/5"
        )
    # Surface failing cases for quick triage.
    for rec in report["cases"]:
        if rec.get("errored"):
            # Show the underlying error, not the cascade of grader failures it
            # caused — those graders never had a real answer to grade.
            print(f"\n  ERROR {rec['id']}")
            print(f"    ! agent error: {rec.get('error')}")
            continue
        problems = [g for g in rec["deterministic"] if not g["passed"]]
        judge_fail = rec.get("judge") and not rec["judge"]["passed"]
        if problems or judge_fail:
            print(f"\n  FAIL {rec['id']}")
            for g in problems:
                print(f"    x {g['name']}: {g['detail']}")
            if judge_fail:
                j = rec["judge"]
                print(f"    x llm_judge: {j['scores']} - {j['rationale'] or j['error']}")


def write_report(report: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval", description="ChordCoach offline eval")
    parser.add_argument("--cases-dir", default=None, help="directory of YAML case files")
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM judge (deterministic only)")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help="min deterministic case pass rate (0-1)")
    parser.add_argument("--judge-threshold", type=float, default=DEFAULT_JUDGE_THRESHOLD,
                        help="min judge case pass rate (0-1)")
    parser.add_argument("--limit", type=int, default=None, help="run only the first N cases")
    parser.add_argument("--concurrency", type=int, default=4, help="cases run in parallel")
    parser.add_argument("--out", default=None, help="report JSON path (default eval/reports/report.json)")
    args = parser.parse_args(argv)

    _load_env()

    cases = load_cases(args.cases_dir) if args.cases_dir else load_cases()
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print("No cases found.", file=sys.stderr)
        return 2

    use_judge = not args.no_judge
    judge_config = JudgeConfig(pass_score=JudgeConfig().pass_score)
    report = asyncio.run(run_eval(cases, use_judge=use_judge, judge_config=judge_config))

    out_path = Path(args.out) if args.out else REPORTS_DIR / "report.json"
    write_report(report, out_path)
    print_summary(report)
    print(f"\nreport written to {out_path}")

    s = report["summary"]

    # Infrastructure failure short-circuits the content gate: if the agent never
    # answered, the content metrics are meaningless. Abort loudly with a distinct
    # exit code (2) pointing at the credential/connectivity problem instead of the
    # misleading "deterministic pass rate 0% < threshold".
    if s.get("errored_cases"):
        print(
            f"\nABORT: {s['errored_cases']}/{s['total_cases']} case(s) errored before "
            "answering — the agent couldn't be reached (most likely an invalid or "
            "expired DEEPSEEK_API_KEY, or a network/provider outage). Fix the "
            "credential/connectivity issue and re-run; content metrics are not "
            "meaningful until the agent answers.",
            file=sys.stderr,
        )
        return 2

    failed = False
    if s["deterministic_pass_rate"] < args.threshold:
        print(
            f"\nFAIL: deterministic pass rate {s['deterministic_pass_rate']:.0%} "
            f"< threshold {args.threshold:.0%}",
            file=sys.stderr,
        )
        failed = True
    if use_judge and s.get("judge_pass_rate", 1.0) < args.judge_threshold:
        print(
            f"FAIL: judge pass rate {s['judge_pass_rate']:.0%} "
            f"< threshold {args.judge_threshold:.0%}",
            file=sys.stderr,
        )
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
