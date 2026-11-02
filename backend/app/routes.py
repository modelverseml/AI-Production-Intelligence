import json
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Service ,Incident, Investigation, Runbook
from app.schemas import (
    RegisterRequest, LoginRequest, RoleUpdate, UserOut, ServiceOut,
    IncidentSummary, IncidentOut, InvestigationOut,
)
from app.security import hash_password, verify_password, create_token, current_user, require_roles
from app.llm import llm_configured
from app.evaluation import investigation_from_run, live_progress, sync_runs_to_db

REPORTS = {
    "rcaeval" : "rcaeval_evaluation.json",
    "ranker" : "ranker_evaluation.json",
}
BACKEND_DIR = Path(__file__).resolve().parent.parent


router =APIRouter()

@router.post("/auth/register",response_model = UserOut)
def register(
    request: RegisterRequest,
    db : Session = Depends(get_db),
):
    email = request.email.lower()
    existing = db.query(User).filter(
        User.email == email
    ).first()

    if existing:
        raise HTTPException(
            409,
            "Email is already registered"
        )
    # Public registration always receives the least-privileged role.
    user = User(
        email = email,
        password_hash = hash_password(request.password),
        role = "viewer"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@router.post("/auth/login")
def login(
    request: LoginRequest,
    db : Session = Depends(get_db)
):
    user = db.query(User).filter(
        User.email == request.email.lower()
    ).first()

    valid = (
        user is not None and verify_password(request.password, user.password_hash)
    )

    if not valid:
        raise HTTPException(
            401,
            "Invalid email or password"
        )
    return {
        "access_token" : create_token(user),
        "token_type" : "bearer",
        "user":UserOut.model_validate(user)
    }

@router.get("/auth/me", response_model = UserOut)
def me(user:User = Depends(current_user)):
    return user

@router.get("/users", response_model = list[UserOut])
def list_users(
    db : Session = Depends(get_db),
    user : User = Depends(require_roles('admin'))
):
    return db.query(User).order_by(User.id).all()

@router.patch("/users/{user_id}/role", response_model = UserOut)
def update_role(
    user_id : int,
    request : RoleUpdate,
    db : Session = Depends(get_db),
    admin : User = Depends(require_roles('admin'))
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    if target.id == admin.id and request.role != 'admin':
        raise HTTPException(400, "Administrators cannot demote themselves")
    target.role = request.role
    db.commit()
    db.refresh(target)
    return target

@router.get("/services", response_model = list[ServiceOut])
def list_services(
    db:Session = Depends(get_db),
    user : User = Depends(current_user)
):
    return db.query(Service).order_by(Service.id).all()

def is_correct(incident, predicted_cause):
    """Whether a predicted service matches the label, stored as "service (fault)"."""
    return predicted_cause == incident.root_cause.split(" (")[0]

@router.get("/incidents", response_model = list[IncidentSummary])
def list_incidents(
    db : Session = Depends(get_db),
    user : User = Depends(current_user)
):
    sync_runs_to_db(db)
    incidents = db.query(Incident).order_by(
        Incident.id.desc()
    ).limit(1000).all()

    counts = dict(
        db.query(Investigation.incident_id, func.count(Investigation.id))
        .group_by(Investigation.incident_id).all()
    )
    latest_ids = [
        latest for (latest,) in
        db.query(func.max(Investigation.id)).group_by(Investigation.incident_id).all()
    ]
    latest = {
        inv.incident_id : inv
        for inv in db.query(Investigation).filter(Investigation.id.in_(latest_ids)).all()
    } if latest_ids else {}

    summaries = []
    for incident in incidents:
        summary = IncidentSummary.model_validate(incident)
        run = latest.get(incident.id)
        if run is not None:
            summary.investigations = counts.get(incident.id, 0)
            summary.latest_prediction = run.predicted_cause
            summary.latest_method = run.method
            summary.latest_correct = is_correct(incident, run.predicted_cause)
        summaries.append(summary)
    return summaries

@router.get("/stats")
def stats(
    db : Session = Depends(get_db),
    user : User = Depends(current_user)
):
    sync_runs_to_db(db)
    by_system = [
        {"system" : system, "count" : count}
        for system, count in db.query(Incident.system, func.count(Incident.id))
        .group_by(Incident.system).order_by(func.count(Incident.id).desc()).all()
    ]
    by_method = dict(
        db.query(Investigation.method, func.count(Investigation.id)).group_by(Investigation.method).all()
    )
    agent_runs = (
        db.query(Investigation, Incident)
        .join(Incident, Investigation.incident_id == Incident.id)
        .filter(Investigation.method.in_(["agent", "hybrid"])).all()
    )
    agent = None
    if agent_runs:
        n = len(agent_runs)
        agent = {
            "runs" : n,
            "accuracy" : round(sum(is_correct(i, r.predicted_cause) for r, i in agent_runs) / n, 4),
            "grounded_rate" : round(sum(bool(r.verification.get("grounded")) for r, _ in agent_runs) / n, 4),
            "avg_cost_usd" : round(sum(r.usage.get("cost_usd", 0) for r, _ in agent_runs) / n, 4),
            "avg_latency_s" : round(sum(r.usage.get("latency_s", 0) for r, _ in agent_runs) / n, 1),
            "avg_tool_calls" : round(sum(r.usage.get("tool_calls", 0) for r, _ in agent_runs) / n, 1),
            "from_evaluation" : sum(r.usage.get("origin") == "evaluation" for r, _ in agent_runs),
        }
    return {
        "incidents" : {"total" : sum(s["count"] for s in by_system), "by_system" : by_system},
        "investigations" : {"total" : sum(by_method.values()), "by_method" : by_method},
        "agent" : agent,
    }

@router.get("/incidents/{incident_id}/telemetry")
def incident_telemetry(
    incident_id : int,
    db : Session = Depends(get_db),
    user : User = Depends(current_user)
):
    """Service graph and metric anomalies for visualization."""
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    entry = db.get(Service, incident.service_id)

    from app.telemetry import CaseTelemetry
    telemetry = CaseTelemetry(incident.case_id)
    scores = {s: telemetry.service_score(s) for s in telemetry.services}
    shown = sorted(scores, key = lambda s: -scores[s])[:14]
    if entry.name not in shown:
        shown.append(entry.name)
    shown_set = set(shown)
    edges = [
        [caller, callee]
        for caller, callees in telemetry.edges.items() if caller in shown_set
        for callee in callees if callee in shown_set
    ]
    anomalies = []
    for item in telemetry.top_anomalies(12):
        name = item["id"].removeprefix("MET:")
        metric = telemetry.metrics[name]
        anomalies.append({
            "id" : item["id"], "service" : metric["service"], "indicator" : metric["indicator"],
            "z" : item["z"], "dir" : item["dir"],
        })
    return {
        "entry" : entry.name,
        "nodes" : [{"id" : s, "score" : round(scores.get(s, 0.0), 2)} for s in shown],
        "edges" : edges,
        "anomalies" : anomalies,
    }

@router.get("/incidents/{incident_id}", response_model = IncidentOut)
def get_incident(
    incident_id : int,
    db : Session = Depends(get_db),
    user : User = Depends(current_user)
):
    incident = db.get(Incident, incident_id)

    if not incident:
        raise HTTPException(404, "Incident not found")
    return incident

@router.post("/investigations/{incident_id}", response_model = InvestigationOut)
def investigate(
    incident_id : int,
    mode : Literal["hybrid", "agent"] = "hybrid",
    db :Session = Depends(get_db),
    user : User = Depends(
        require_roles('analyst','admin')
    )
):
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")

    result = run_agent_investigation(incident, mode, user, db)
    db.add(result)
    db.commit()
    db.refresh(result)
    return result

def run_agent_investigation(incident, mode, user, db):
    if not llm_configured():
        raise HTTPException(503, "Azure OpenAI is not configured on the server")
    from app.agent import investigate_case

    run = investigate_case(incident.case_id, use_ml = mode == "hybrid")
    runbooks = {rb.code: rb for rb in db.query(Runbook).all()}
    return investigation_from_run(incident, run, mode, user.id, runbooks, {"origin" : "app"})

@router.get("/evaluations")
def get_evaluations(user : User = Depends(current_user)):
    reports = {}
    for name, filename in REPORTS.items():
        path = BACKEND_DIR / filename
        reports[name] = json.loads(path.read_text()) if path.exists() else None
    # Interim scores while the held-out evaluation is still running.
    reports["live"] = live_progress()
    return reports

@router.get("/investigations/{incident_id}", response_model = list[InvestigationOut])
def get_investigations(
    incident_id : int,
    db :Session = Depends(get_db),
    user : User = Depends(current_user)
):
    sync_runs_to_db(db)
    return db.query(Investigation).filter(
        Investigation.incident_id == incident_id
    ).order_by(
        Investigation.id.desc()
    ).all()
