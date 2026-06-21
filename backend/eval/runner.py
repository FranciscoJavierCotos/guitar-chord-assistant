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


async def _run_case(case: EvalCase, use_judge: bool, judge_config: JudgeConfig) -> dict:
    response = await _generate(case)
    deterministic = run_deterministic(case, response)
    record: dict = {
        "id": case.id,
        "tags": case.tags,
        "prompt": case.prompt,
        "response": response,
        "deterministic": [asdict(r) for r in deterministic],
        "deterministic_passed": all(r.passed for r in deterministic),
    }
    if use_judge:
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
    # Per-grader pass rate across every case the grader applied to.
    per_grader: dict[str, dict[str, int]] = {}
    for rec in case_records:
        for g in rec["deterministic"]:
            stats = per_grader.setdefault(g["name"], {"passed": 0, "total": 0})
            stats["total"] += 1
            stats["passed"] += 1 if g["passed"] else 0

    grader_rates = {
        name: round(s["passed"] / s["total"], 4) if s["total"] else 1.0
        for name, s in per_grader.items()
    }
    det_pass = sum(1 for r in case_records if r["deterministic_passed"])
    total = len(case_records)
    summary: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_cases": total,
        "deterministic_pass_rate": round(det_pass / total, 4) if total else 1.0,
        "deterministic_cases_passed": det_pass,
        "per_grader_pass_rate": grader_rates,
        "use_judge": use_judge,
    }
    if use_judge:
        judged = [r for r in case_records if r.get("judge")]
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
    print(
        f"deterministic: {s['deterministic_cases_passed']}/{s['total_cases']} "
        f"cases passed ({s['deterministic_pass_rate']:.0%})"
    )
    for name, rate in sorted(s["per_grader_pass_rate"].items()):
        print(f"  - {name:<22} {rate:.0%}")
    if s.get("use_judge"):
        print(
            f"judge ({s['judge_config']['model']}): "
            f"{s['judge_cases_passed']}/{s['total_cases']} cases passed "
            f"({s['judge_pass_rate']:.0%}), mean score {s['judge_mean_score']}/5"
        )
    # Surface failing cases for quick triage.
    for rec in report["cases"]:
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
