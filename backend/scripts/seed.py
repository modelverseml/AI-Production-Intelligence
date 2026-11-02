"""Seed the runbook library and the admin user.

Usage (from backend/):
    python -m scripts.seed           # create tables, add runbooks, create/update admin
    python -m scripts.seed --reset   # drop all tables first (re-run import_rcaeval afterwards)

Runbooks are what the agent's search_runbooks tool retrieves with hybrid RAG.
Incidents come from the RCAEval benchmark via scripts/import_rcaeval.py.
"""
import argparse

from app.config import settings
from app.database import Base, engine, SessionLocal
from app.models import User, Runbook
from app.security import hash_password

RUNBOOKS = [
    # code, category, title, body
    ("RB-DB-001", "DATABASE_POOL_EXHAUSTION", "Database connection pool exhaustion",
     "Symptoms: connection pool exhausted errors, requests timed out waiting for connection, "
     "rising p99 latency on database-backed endpoints. Check active versus idle pool connections "
     "and pg_stat_activity for long-running or idle-in-transaction sessions. Mitigate by killing "
     "stuck sessions, temporarily raising pool size, and shedding non-critical traffic."),
    ("RB-DB-002", "DATABASE_POOL_EXHAUSTION", "PostgreSQL too many connections",
     "When PostgreSQL reports FATAL too many connections, verify max_connections, count clients per "
     "role, and confirm PgBouncer is in transaction pooling mode. Scale replicas carefully because "
     "each pod opens its own pool and multiplies database connections."),
    ("RB-DB-003", "DATABASE_POOL_EXHAUSTION", "Connection leak investigation",
     "A connection leak shows as steadily increasing active connections that never return to the pool. "
     "Enable leak detection thresholds in HikariCP or SQLAlchemy pool logging, look for sessions not "
     "closed on exception paths, and restart affected pods to recover capacity."),
    ("RB-DB-004", "DATABASE_POOL_EXHAUSTION", "Slow query causing pool saturation",
     "Slow queries hold connections longer and saturate the pool. Identify top queries by total time, "
     "check for missing indexes or lock contention, and add statement timeouts so a single slow "
     "query cannot exhaust database connections."),
    ("RB-CPU-001", "CPU_SATURATION", "CPU saturation and throttling",
     "Symptoms: CPU throttling in container metrics, CPU utilization above 90 percent, rising request "
     "latency and worker saturation. Compare CPU limits with requests, check throttled periods, and "
     "scale out replicas or raise limits. Capture a CPU profile before restarting."),
    ("RB-CPU-002", "CPU_SATURATION", "Worker pool saturation",
     "When all application workers are busy, requests queue and latency climbs. Inspect worker counts, "
     "event loop lag and blocking calls on hot paths. Horizontal pod autoscaling at max replicas "
     "indicates capacity, not code, is the immediate constraint."),
    ("RB-CPU-003", "CPU_SATURATION", "Garbage collection pressure",
     "Long GC pauses and heap pressure consume CPU and stall request handling. Review heap sizing, "
     "allocation hot spots, and GC logs. Increase memory or reduce allocation rate in tight loops."),
    ("RB-CPU-004", "CPU_SATURATION", "Hot loop and regex CPU regression",
     "Pathological regular expressions or tight retry loops can pin cores at full CPU utilization. "
     "Use a flame graph to locate the hot function and add input limits or backoff."),
    ("RB-DEP-001", "FAULTY_DEPLOYMENT", "Rolling back a faulty deployment",
     "If error rate rises shortly after a release, correlate the deployment timestamp with the first "
     "errors. Roll back to the previous version, then confirm error rate recovers. Preserve logs of the "
     "new release for the postmortem."),
    ("RB-DEP-002", "FAULTY_DEPLOYMENT", "Database schema mismatch after release",
     "A schema mismatch occurs when application code expects a column or table that a migration has "
     "not yet created. Check migration status, apply expand-then-contract migrations, and roll back "
     "the application if the migration cannot be applied safely."),
    ("RB-DEP-003", "FAULTY_DEPLOYMENT", "New release exceptions and feature flags",
     "Exceptions such as NullPointerException introduced by a new release often hide behind feature "
     "flags. Disable the flag first, which is faster than a rollback, then fix forward with a test "
     "that covers the failing path."),
    ("RB-DEP-004", "FAULTY_DEPLOYMENT", "Canary analysis and progressive delivery",
     "Use canary deployments to compare error rate and latency of the new version against the stable "
     "baseline. Abort the rollout automatically when the canary error rate exceeds the baseline."),
    ("RB-UP-001", "UPSTREAM_FAILURE", "Upstream dependency timeout",
     "Symptoms: upstream timeout errors, 504 gateway timeout responses, and elevated upstream error "
     "percent while local CPU and database are healthy. Check the dependency status page and tracing "
     "spans to locate the failing hop. Tighten timeouts and serve cached or degraded responses."),
    ("RB-UP-002", "UPSTREAM_FAILURE", "Circuit breaker open on dependency",
     "An open circuit breaker means a dependency is unavailable or failing fast. Confirm the dependency "
     "health, avoid retry storms by honoring retry budgets, and fail over to a secondary provider."),
    ("RB-UP-003", "UPSTREAM_FAILURE", "Third-party provider outage",
     "When a third-party provider such as a card processor or email provider returns 503 dependency "
     "unavailable, enable the fallback provider, queue requests for replay, and communicate impact."),
    ("RB-UP-004", "UPSTREAM_FAILURE", "Connection refused to internal service",
     "Connection refused errors to an internal service indicate the target pods are down or the service "
     "endpoint has no ready backends. Check readiness probes, endpoints, and recent node evictions."),
    ("RB-MEM-001", "MEMORY_PRESSURE", "Memory leak and memory stress",
     "Symptoms: container memory climbing steadily or pinned near the limit, OOMKilled restarts, "
     "rising GC activity and latency. Compare memory against the previous release, capture a heap "
     "dump, raise the memory limit temporarily, and restart affected pods to restore service."),
    ("RB-MEM-002", "MEMORY_PRESSURE", "Noisy neighbour memory stress",
     "A co-located process stressing memory starves the service of page cache and causes swapping. "
     "Identify the offending process, cordon the node, and reschedule the workload."),
    ("RB-DISK-001", "DISK_IO", "Disk I/O saturation",
     "Symptoms: high disk I/O wait, slow writes, database or cache latency climbing while CPU is "
     "normal. Check iostat and per-container disk throughput, stop heavy batch jobs, and move hot "
     "volumes to faster storage."),
    ("RB-DISK-002", "DISK_IO", "Disk stress on data stores",
     "Disk stress on a node hosting a data store slows every query. Fail over to a replica on a "
     "healthy node and throttle background compaction or backups."),
    ("RB-SOCK-001", "SOCKET_EXHAUSTION", "Socket and file descriptor exhaustion",
     "Symptoms: too many open files, connection refused, sockets stuck in TIME_WAIT or CLOSE_WAIT, "
     "socket count metrics spiking. Raise ulimit, enable connection pooling and keep-alive, and "
     "restart the leaking process."),
    ("RB-NET-001", "NETWORK_DELAY", "Injected network latency",
     "Symptoms: one service's response latency jumps by a constant amount while its CPU and memory "
     "stay normal, and every caller inherits the delay. Check network policies, service mesh "
     "faults, and node network health; drain the affected pod."),
    ("RB-NET-002", "PACKET_LOSS", "Packet loss and retransmissions",
     "Symptoms: intermittent timeouts and errors, TCP retransmissions, error rate rising for calls "
     "to one service without resource saturation. Check the node NIC and CNI plugin, and move "
     "the pod to another node."),
    ("RB-CODE-001", "CODE_DEFECT", "Application code defect",
     "Symptoms: new exception types or stack traces in logs, error responses or crashes after a "
     "change, gRPC status codes such as UNKNOWN or UNAVAILABLE from one service. Identify the "
     "failing code path from the new log templates, roll back or disable the feature, and add a "
     "regression test."),
    ("RB-CODE-002", "CODE_DEFECT", "Service crash loop after code fault",
     "When a service process exits or shuts down, its log volume drops, callers receive connection "
     "errors, and restarts increase. Inspect the last log lines before shutdown and roll back."),
    ("RB-GEN-001", "GENERAL", "Incident commander checklist",
     "Declare the incident, assign roles, open a communication channel, post status updates every 30 "
     "minutes, and record a timeline for the postmortem."),
    ("RB-GEN-002", "GENERAL", "Writing a blameless postmortem",
     "Document impact, timeline, contributing factors, and action items. Focus on systems and processes "
     "rather than individuals."),
    ("RB-GEN-003", "GENERAL", "TLS certificate expiry",
     "Expired certificates cause handshake failures. Check certificate expiry dates, renew through the "
     "certificate manager, and add alerts thirty days before expiry."),
    ("RB-GEN-004", "GENERAL", "Disk space exhaustion on nodes",
     "Disk pressure evicts pods and blocks writes. Clean up old logs and images, expand volumes, and set "
     "log rotation policies."),
    ("RB-GEN-005", "GENERAL", "DNS resolution failures",
     "Intermittent DNS failures appear as name resolution errors. Check CoreDNS pods, ndots settings, and "
     "upstream resolvers."),
    ("RB-GEN-006", "GENERAL", "Memory leak and OOM kills",
     "OOMKilled containers restart repeatedly. Compare memory growth across releases, take heap dumps, "
     "and set memory limits with headroom."),
    ("RB-GEN-007", "GENERAL", "Cache stampede on Redis",
     "A cache stampede happens when many keys expire together and requests hit the backing store. Add "
     "jittered TTLs and request coalescing."),
    ("RB-GEN-008", "GENERAL", "Message queue consumer lag",
     "Consumer lag grows when consumers are slower than producers. Scale consumers, check for poison "
     "messages, and monitor partition skew."),
    ("RB-GEN-009", "GENERAL", "Alert fatigue and noisy monitors",
     "Tune thresholds, group related alerts, and route only actionable pages to on-call."),
    ("RB-GEN-010", "GENERAL", "Rate limiting abusive clients",
     "Identify abusive clients by API key or IP, apply per-client rate limits at the gateway, and "
     "return 429 responses with retry-after headers."),
]

def upsert_admin(db):
    """Create the admin from .env, or update its password and role."""
    if settings.ADMIN_EMAIL and settings.ADMIN_PASSWORD:
        email = settings.ADMIN_EMAIL.lower()
        admin = db.query(User).filter(User.email == email).first()
        if admin is None:
            db.add(User(
                email = email,
                password_hash = hash_password(settings.ADMIN_PASSWORD),
                role = "admin",
            ))
        else:
            admin.role = "admin"
            admin.password_hash = hash_password(settings.ADMIN_PASSWORD)
    else:
        print("ADMIN_EMAIL / ADMIN_PASSWORD not set; skipping admin user.")


def seed(reset):
    if reset:
        Base.metadata.drop_all(bind = engine)
    Base.metadata.create_all(bind = engine)

    with SessionLocal() as db:
        upsert_admin(db)
        existing = {code for (code,) in db.query(Runbook.code)}
        added = 0
        for code, category, title, body in RUNBOOKS:
            if code not in existing:
                db.add(Runbook(code = code, category = category, title = title, body = body))
                added += 1
        db.commit()
        print(f"Runbooks: {added} added, {len(existing)} already present. Admin user ready.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description = __doc__)
    parser.add_argument("--reset", action = "store_true", help = "drop and recreate all tables")
    seed(parser.parse_args().reset)
