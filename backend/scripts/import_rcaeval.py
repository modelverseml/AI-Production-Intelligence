"""Import downloaded RCAEval cases into PostgreSQL as incidents.

Usage (from backend/, after seed and download_rcaeval):
    python -m scripts.import_rcaeval

Each case becomes an incident on the system's entry-point service (where users
see the failure). The root-cause label is stored for comparison in the UI but
never passed to the agent; the case folder name, which encodes the label, is
kept server-side only.
"""
from datetime import datetime, timezone

from app.database import Base, SessionLocal, engine
from app.models import Incident, Service
from app.telemetry import CaseTelemetry, available_cases

ENTRY_SERVICE = {"ob" : "frontend", "ss" : "front-end", "tt" : "ts-ui-dashboard"}
TOP_METRICS = 6
LOG_LINES = 8

def alert_logs(telemetry):
    """Error and never-seen-before log lines, as an on-call engineer would see them."""
    lines = []
    for service, stats in sorted(
        telemetry.logs.items(), key = lambda item: -item[1]["novel_templates"]
    ):
        for message in stats["novel_examples"][:2] + stats["error_examples"][:1]:
            lines.append(f"[{service}] {message[:200]}")
    return list(dict.fromkeys(lines))[:LOG_LINES]

def main():
    Base.metadata.create_all(bind = engine)
    cases = available_cases()
    if cases.empty:
        raise SystemExit("No RCAEval cases found. Run: python -m scripts.download_rcaeval")

    with SessionLocal() as db:
        existing = {case for (case,) in db.query(Incident.case_id).filter(Incident.case_id.isnot(None))}
        services = {s.name: s for s in db.query(Service).all()}
        counters = {}
        added = 0

        for case_id, meta in cases.iterrows():
            counters[meta["dataset"]] = counters.get(meta["dataset"], 0) + 1
            if case_id in existing:
                continue
            telemetry = CaseTelemetry(case_id)

            for name in telemetry.services:
                dependencies = telemetry.neighbors(name)["calls"]
                if name not in services:
                    services[name] = Service(name = name, dependencies = dependencies)
                    db.add(services[name])
                else:
                    merged = sorted(set(services[name].dependencies or []) | set(dependencies))
                    services[name].dependencies = merged
            db.flush()

            entry = services[ENTRY_SERVICE[meta["system"]]]
            started = datetime.fromtimestamp(int(meta["inject_time"]), tz = timezone.utc)
            db.add(Incident(
                title = f"{meta['system_name']} degradation alert #{counters[meta['dataset']]} ({meta['dataset']})",
                description = (
                    f"Users of {meta['system_name']} report slow and failing requests starting "
                    f"{started:%Y-%m-%d %H:%M} UTC. {len(telemetry.services)} services are emitting "
                    "metrics, logs and traces. Root cause unknown."
                ),
                service_id = entry.id,
                severity = "SEV2",
                logs = alert_logs(telemetry),
                metrics = {
                    item["id"].removeprefix("MET:") : f"z={item['z']:g} {item['dir']}"
                    for item in telemetry.top_anomalies(TOP_METRICS)
                },
                root_cause = f"{meta['root_cause_service']} ({meta['fault_description']})",
                system = meta["system_name"],
                case_id = case_id,
                created_at = started,
            ))
            added += 1

        db.commit()
    print(f"Imported {added} RCAEval incidents ({len(existing)} already present).")

if __name__ == "__main__":
    main()
