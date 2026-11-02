"""Shared helpers for the held-out RCAEval evaluation: case selection, cached
LLM runs, and live (in-progress) scoring for the UI."""
import json
import threading
from pathlib import Path

from app.llm import default_deployment
from app.ranker import load_oof
from app.rca_metrics import rank_of, summarize_ranks
from app.telemetry import CaseTelemetry, available_cases, baro_ranking

BACKEND_DIR = Path(__file__).resolve().parent.parent
RUN_DIR = BACKEND_DIR / "results" / "rcaeval_runs"
DEV_CASES = BACKEND_DIR / "results" / "dev_cases.json"
LLM_METHODS = ("agent", "hybrid")
PER_DATASET = 30

def dev_cases():
    return set(json.loads(DEV_CASES.read_text())) if DEV_CASES.exists() else set()

def select_cases(per_dataset = PER_DATASET, include_dev = False):
    """Held-out evaluation cases: prompt-development cases removed, then a
    seeded shuffle and the first N per dataset."""
    cases = available_cases()
    excluded = set() if include_dev else dev_cases()
    cases = cases.loc[[c for c in cases.index if c not in excluded]]
    if per_dataset:
        cases = cases.groupby("dataset", group_keys = False).sample(frac = 1.0, random_state = 42)
        cases = cases.groupby("dataset").head(per_dataset)
    return cases, excluded

def run_path(method, deployment):
    return RUN_DIR / f"{method}_{deployment}.jsonl"

def load_runs(method, deployment):
    runs = {}
    path = run_path(method, deployment)
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                record = json.loads(line)
                runs[record["case_id"]] = record
    return runs

def live_progress(deployment = None):
    """Progress and interim scores of the running evaluation, per method.

    Each LLM method is scored on the cases it has finished so far, next to the
    baseline and ML ranker on those same cases.
    """
    deployment = deployment or default_deployment()
    cases, _ = select_cases()
    truth = cases["root_cause_service"]
    oof = load_oof()
    methods = {}
    for method in LLM_METHODS:
        runs = {c: r for c, r in load_runs(method, deployment).items() if c in truth.index}
        done = list(runs)
        entry = {"done" : len(done), "target" : len(cases)}
        if done:
            entry["scores"] = {
                method : summarize_ranks([rank_of(runs[c]["final_ranking"], truth[c]) for c in done]),
                "baro" : summarize_ranks([rank_of(baro_ranking(CaseTelemetry(c)), truth[c]) for c in done]),
            }
            if oof:
                entry["scores"]["ranker"] = summarize_ranks(
                    [rank_of([r["service"] for r in oof[c]], truth[c]) for c in done]
                )
            entry["grounded_rate"] = round(
                sum(bool(r["verification"].get("grounded")) for r in runs.values()) / len(done), 4
            )
            entry["cost_usd"] = round(sum(r["usage"]["cost_usd"] for r in runs.values()), 2)
        methods[method] = entry
    return {"deployment" : deployment, "methods" : methods}

_synced_mtimes = {}
_sync_lock = threading.Lock()

def sync_runs_to_db(db):
    # Requests run in a thread pool; one sync at a time avoids double imports.
    with _sync_lock:
        return _sync_runs(db)

def _sync_runs(db):
    """Copy finished evaluation runs into the investigations table, so the app
    shows them like analyses started from the UI. Skips files that have not
    changed since the last sync and runs that were already imported."""
    from app.models import Incident, Investigation, Runbook, User

    files = sorted(RUN_DIR.glob("*.jsonl")) if RUN_DIR.exists() else []
    changed = [f for f in files if _synced_mtimes.get(f) != f.stat().st_mtime]
    if not changed:
        return 0
    owner = db.query(User).filter(User.role == "admin").order_by(User.id).first()
    if owner is None:
        return 0

    incidents = {i.case_id: i for i in db.query(Incident).filter(Incident.case_id.isnot(None))}
    imported = {
        (inv.incident_id, inv.usage.get("run_key"))
        for inv in db.query(Investigation).all() if inv.usage.get("origin") == "evaluation"
    }
    runbooks = {rb.code: rb for rb in db.query(Runbook).all()}
    added = 0
    for path in changed:
        method, deployment = path.stem.split("_", 1)
        for case_id, run in load_runs(method, deployment).items():
            incident = incidents.get(case_id)
            key = f"{method}:{deployment}"
            if incident is None or (incident.id, key) in imported:
                continue
            db.add(investigation_from_run(incident, run, method, owner.id, runbooks, {
                "origin" : "evaluation", "run_key" : key,
            }))
            imported.add((incident.id, key))
            added += 1
        _synced_mtimes[path] = path.stat().st_mtime
    if added:
        db.commit()
    return added

def investigation_from_run(incident, run, method, user_id, runbooks, extra_usage = None):
    """Build an Investigation row from an agent run (UI or offline evaluation)."""
    from app.models import Investigation

    report = run["report"]
    ranked = report.get("ranked_services", [])
    return Investigation(
        incident_id = incident.id,
        user_id = user_id,
        method = method,
        predicted_cause = run["final_ranking"][0] if run["final_ranking"] else "UNKNOWN",
        confidence = float(ranked[0]["likelihood"]) if ranked else 0.0,
        explanation = report.get("summary", ""),
        evidence = [
            {"id" : code, "type" : "runbook", "title" : runbooks[code].title,
             "snippet" : runbooks[code].body[:280], "score" : 1.0}
            for code in report.get("runbook_ids", []) if code in runbooks
        ],
        report = {**report, "final_ranking" : run["final_ranking"]},
        verification = run["verification"],
        trace = run["trace"],
        usage = {**run["usage"], "deployment" : run["deployment"], **(extra_usage or {})},
    )
