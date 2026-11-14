"""Evaluate root-cause methods on the RCAEval benchmark.

Usage (from backend/):
    python -m scripts.evaluate_rcaeval                       # LLM methods on 30 cases per dataset
    python -m scripts.evaluate_rcaeval --per-dataset 6       # quick pilot
    python -m scripts.evaluate_rcaeval --per-dataset 0       # every case
    python -m scripts.evaluate_rcaeval --methods hybrid --deployment gpt-5-mini

Methods:
    baro     BARO-style statistical baseline (max robust z-score)
    ranker   LightGBM ranker, out-of-fold (root-cause service held out)
    agent    LLM agent with telemetry tools only
    hybrid   LLM agent that can also call the ML ranker

LLM runs are cached in results/rcaeval_runs/<method>_<deployment>.jsonl, so an
interrupted evaluation resumes without paying for completed cases again.
Requires: download_rcaeval and train_ranker to have been run first.
"""
import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from app.agent import investigate_case, runbook_retriever
from app.evaluation import LLM_METHODS, PER_DATASET, RUN_DIR, load_runs, run_path, select_cases, write_target
from app.llm import default_deployment
from app.ranker import load_oof
from app.rca_metrics import rank_of, summarize_by
from app.telemetry import CaseTelemetry, available_cases, baro_ranking

OUTPUT = Path("rcaeval_evaluation.json")

def expected_fault(row):
    return "code" if row["suite"] == "RE3" else row["fault"]

def run_llm_method(method, case_ids, deployment, workers):
    RUN_DIR.mkdir(parents = True, exist_ok = True)
    path = run_path(method, deployment)
    runs = load_runs(method, deployment)
    todo = [c for c in case_ids if c not in runs]
    print(f"{method}: {len(case_ids) - len(todo)} cached, {len(todo)} to run")
    lock = threading.Lock()
    runbook_retriever()  # build the index once, before worker threads start

    def work(case_id):
        return investigate_case(case_id, use_ml = method == "hybrid", deployment = deployment)

    with ThreadPoolExecutor(workers) as pool, path.open("a") as sink:
        futures = {pool.submit(work, c): c for c in todo}
        for done, future in enumerate(as_completed(futures), 1):
            case_id = futures[future]
            try:
                record = future.result()
            except Exception as error:
                print(f"  {case_id} failed: {error}")
                continue
            with lock:
                sink.write(json.dumps(record) + "\n")
                sink.flush()
                runs[case_id] = record
            if done % 10 == 0 or done == len(todo):
                spent = sum(r["usage"]["cost_usd"] for r in runs.values())
                print(f"  {done}/{len(todo)} done, ${spent:.2f} spent on {method} so far")
    return {c: runs[c] for c in case_ids if c in runs}

def llm_summary(runs, cases):
    records = list(runs.values())
    if not records:
        return {}
    usage = pd.DataFrame([r["usage"] for r in records])
    verification = [r["verification"] for r in records]
    cited = sum(v.get("cited", 0) for v in verification)
    invalid = sum(v.get("invalid", 0) for v in verification)
    first_pass = [v for v in verification if v.get("retries", 0) == 0 and v.get("grounded")]
    fault_correct = [
        r["report"].get("fault_type") == expected_fault(cases.loc[r["case_id"]])
        for r in records
    ]
    return {
        "fault_type_accuracy" : round(float(np.mean(fault_correct)), 4),
        "citation_validity" : round(1 - invalid / max(1, cited), 4),
        "grounded_reports" : round(float(np.mean([v.get("grounded", False) for v in verification])), 4),
        "grounded_first_attempt" : round(len(first_pass) / len(records), 4),
        "self_corrected_reports" : int(sum(1 for v in verification if v.get("retries", 0) > 0 and v.get("grounded"))),
        "mean_tool_calls" : round(float(usage["tool_calls"].mean()), 2),
        "mean_llm_calls" : round(float(usage["llm_calls"].mean()), 2),
        "mean_prompt_tokens" : int(usage["prompt_tokens"].mean()),
        "mean_completion_tokens" : int(usage["completion_tokens"].mean()),
        "cost_per_case_usd" : round(float(usage["cost_usd"].mean()), 4),
        "total_cost_usd" : round(float(usage["cost_usd"].sum()), 2),
        "latency_p50_s" : round(float(usage["latency_s"].median()), 2),
        "latency_p95_s" : round(float(usage["latency_s"].quantile(0.95)), 2),
    }

def full_benchmark(cases):
    """Non-LLM methods on every downloaded case."""
    truth = cases["root_cause_service"]
    frame = cases[["dataset"]].copy()
    frame["baro"] = [rank_of(baro_ranking(CaseTelemetry(c)), truth[c]) for c in cases.index]
    oof = load_oof()
    if oof:
        frame["ranker"] = [rank_of([r["service"] for r in oof[c]], truth[c]) for c in cases.index]
    return {m: summarize_by(frame, m) for m in ("baro", "ranker") if m in frame}

def main():
    parser = argparse.ArgumentParser(description = __doc__, formatter_class = argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--methods", nargs = "+", default = ["baro", "ranker", "agent", "hybrid"])
    parser.add_argument("--deployment", default = default_deployment())
    parser.add_argument("--per-dataset", type = int, default = PER_DATASET,
                        help = "stratified sample of N cases per dataset (0 = all cases)")
    parser.add_argument("--workers", type = int, default = 2)
    parser.add_argument("--include-dev", action = "store_true",
                        help = "also evaluate cases used during prompt development")
    args = parser.parse_args()

    all_cases = available_cases()
    # Cases used while developing the prompts are excluded from evaluation.
    cases, dev_cases = select_cases(args.per_dataset, args.include_dev)
    write_target(cases.index, args.deployment)
    truth = cases["root_cause_service"]
    frame = cases[["dataset", "fault"]].copy()
    report = {
        "cases_sampled" : len(cases),
        "dev_cases_excluded" : len(dev_cases),
        "deployment" : args.deployment,
        "full_benchmark" : full_benchmark(all_cases),
        "methods" : {},
        "llm" : {},
    }

    if "baro" in args.methods:
        frame["baro"] = [rank_of(baro_ranking(CaseTelemetry(c)), truth[c]) for c in cases.index]
    if "ranker" in args.methods:
        oof = load_oof()
        if not oof:
            raise SystemExit("No out-of-fold rankings. Run: python -m scripts.train_ranker")
        frame["ranker"] = [rank_of([r["service"] for r in oof[c]], truth[c]) for c in cases.index]

    runs_by_method = {}
    for method in LLM_METHODS:
        if method not in args.methods:
            continue
        runs = run_llm_method(method, list(cases.index), args.deployment, args.workers)
        runs_by_method[method] = runs
        frame[method] = [
            rank_of(runs[c]["final_ranking"], truth[c])
            if c in runs else None
            for c in cases.index
        ]

    # Score every method on the same cases: those every LLM method completed.
    llm_columns = [m for m in LLM_METHODS if m in frame]
    if llm_columns:
        completed_ids = [c for c in frame.index if all(c in runs_by_method[m] for m in llm_columns)]
        missing = len(frame) - len(completed_ids)
        if missing:
            print(f"Warning: {missing} cases have no completed LLM run; they are excluded from scoring.")
        frame = frame.loc[completed_ids]
    report["cases_scored"] = len(frame)
    for method, runs in runs_by_method.items():
        report["llm"][method] = llm_summary({c: runs[c] for c in frame.index}, cases)
    methods = [m for m in ("baro", "ranker", "agent", "hybrid") if m in frame]
    for method in methods:
        report["methods"][method] = summarize_by(frame, method)

    output = OUTPUT if args.per_dataset in (0, 30) and not args.include_dev else OUTPUT.with_name("rcaeval_pilot.json")
    output.write_text(json.dumps(report, indent = 2))

    for metric in ("AC@1", "AC@3", "Avg@5"):
        print(f"\n{metric}")
        print(pd.DataFrame({
            m : {ds: v[metric] for ds, v in report["methods"][m].items()} for m in methods
        }).round(3).to_string())
    if report["llm"]:
        print("\nLLM agent quality and cost")
        print(pd.DataFrame(report["llm"]).to_string())
    print(f"\nWrote {output.resolve()}")

if __name__ == "__main__":
    main()
