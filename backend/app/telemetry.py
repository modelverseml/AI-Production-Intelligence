"""Telemetry feature extraction for RCAEval benchmark cases.

Every case is split at the fault-injection time into a normal window (before)
and an anomalous window (after). Each piece of evidence gets a stable ID so
the agent's findings can cite it and the citations can be verified:

    MET:<metric>            metric anomaly, e.g. MET:carts_cpu
    LOG:<service>:volume    change in log rate
    LOG:<service>:errors    change in error-keyword rate
    LOG:<service>:new       log templates never seen before the fault
    TRC:<service>:errors    trace error-rate change for calls to the service
    TRC:<service>:latency   trace latency change for calls to the service
"""
import json
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "rcaeval"
DEFAULT_SUITES = ["re2ob", "re2ss", "re3ob", "re3ss", "re3tt"]
FEATURE_VERSION = 1
Z_CAP = 100.0

INDICATOR_FAMILIES = ["cpu", "mem", "diskio", "socket", "workload", "error", "latency"]

# Sock Shop emits no traces, so its call graph comes from the published architecture.
STATIC_TOPOLOGY = {
    "ss" : {
        "front-end" : ["carts", "catalogue", "orders", "user"],
        "orders" : ["carts", "payment", "shipping", "user", "orders-db"],
        "carts" : ["carts-db"],
        "catalogue" : ["catalogue-db"],
        "user" : ["user-db"],
        "shipping" : ["rabbitmq"],
        "queue-master" : ["rabbitmq"],
    },
}

ERROR_PATTERN = re.compile(
    r"error|exception|fail|refused|timeout|timed out|unavailable|panic|fatal|"
    r"traceback|denied|\b5\d\d\b",
    re.IGNORECASE,
)
MASK_PATTERNS = [
    (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I), "<uuid>"),
    (re.compile(r"\b[0-9a-f]{16,}\b", re.I), "<hex>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[t ][\d:.]+z?", re.I), "<ts>"),
    (re.compile(r"\"[^\"]*\""), "<str>"),
    (re.compile(r"\d+(\.\d+)?"), "<num>"),
]
OPERATION_SERVICE = re.compile(r"\.([A-Za-z]+Service)/")

def sig(value, digits = 4):
    """Round to significant digits to keep tool output compact."""
    return float(f"{value:.{digits}g}")

def indicator_family(indicator):
    for family in INDICATOR_FAMILIES:
        if indicator.startswith(family):
            return family
    return indicator

def log_template(message):
    template = message.strip()[:300]
    for pattern, token in MASK_PATTERNS:
        template = pattern.sub(token, template)
    return template

def robust_z(pre, post):
    """Robust z-scores of post values against the pre-fault distribution."""
    pre = pre[~np.isnan(pre)]
    post = post[~np.isnan(post)]
    if len(pre) < 5 or len(post) == 0:
        return None
    median = np.median(pre)
    q75, q25 = np.percentile(pre, [75, 25])
    scale = q75 - q25
    if scale <= 0:
        scale = np.std(pre)
    if scale <= 0:
        scale = max(abs(median) * 0.01, 1e-3)
    z = np.clip((post - median) / scale, -Z_CAP, Z_CAP)
    return {
        "max_abs_z" : float(np.max(np.abs(z))),
        "p95_abs_z" : float(np.percentile(np.abs(z), 95)),
        "direction" : "up" if np.median(post) >= median else "down",
        "pre_median" : float(median),
        "post_median" : float(np.median(post)),
    }

@lru_cache(maxsize = 1)
def load_cases():
    return pd.read_parquet(DATA_DIR / "cases.parquet").set_index("case")

def available_cases(suites = None):
    cases = load_cases()
    prefixes = tuple(suites or DEFAULT_SUITES)
    present = [
        case for case in cases.index
        if case.startswith(prefixes) and (DATA_DIR / case / "metrics.parquet").exists()
    ]
    return cases.loc[present]

class CaseTelemetry:
    """Pre-computed, cached anomaly evidence for one benchmark case."""

    def __init__(self, case_id):
        self.case_id = case_id
        self.path = DATA_DIR / case_id
        self.meta = load_cases().loc[case_id]
        cache = self.path / "_features.json"
        if cache.exists():
            data = json.loads(cache.read_text())
            if data.get("version") == FEATURE_VERSION:
                self.__dict__.update(data["features"])
                return
        self._compute()
        cache.write_text(json.dumps({
            "version" : FEATURE_VERSION,
            "features" : {
                "services" : self.services,
                "metrics" : self.metrics,
                "logs" : self.logs,
                "traces" : self.traces,
                "edges" : self.edges,
            },
        }))

    # ------------------------------------------------------------------ compute
    def _compute(self):
        inject = int((self.path / "inject_time.txt").read_text().strip())
        self._metric_features(inject)
        self.logs = self._log_features(inject)
        self.traces, trace_edges = self._trace_features(inject)
        static = STATIC_TOPOLOGY.get(self.meta["system"], {})
        edges = defaultdict(set)
        for caller, callees in static.items():
            edges[caller].update(callees)
        for caller, callee in trace_edges:
            edges[caller].add(callee)
        self.edges = {
            caller: sorted(c for c in callees if c in self.services and c != caller)
            for caller, callees in edges.items() if caller in self.services
        }

    def _metric_features(self, inject):
        frame = pd.read_parquet(self.path / "metrics.parquet")
        times = frame["time"].to_numpy(dtype = float)
        before, after = times < inject, times >= inject
        metrics = {}
        services = set()
        for column in frame.columns:
            if column == "time" or "_" not in column:
                continue
            service, indicator = column.rsplit("_", 1)
            values = pd.to_numeric(frame[column], errors = "coerce").to_numpy(dtype = float)
            stats = robust_z(values[before], values[after])
            services.add(service)
            if stats is None:
                continue
            metrics[column] = {
                "service" : service,
                "indicator" : indicator,
                "family" : indicator_family(indicator),
                **{key: round(value, 4) if isinstance(value, float) else value
                   for key, value in stats.items()},
            }
        self.services = sorted(services)
        self.metrics = metrics

    def _log_features(self, inject):
        path = self.path / "logs.parquet"
        if not path.exists():
            return {}
        frame = pd.read_parquet(path, columns = ["timestamp", "container_name", "message"])
        frame["timestamp"] = pd.to_numeric(frame["timestamp"], errors = "coerce")
        start, end = frame["timestamp"].min(), frame["timestamp"].max()
        pre_seconds = max(inject - start, 1)
        post_seconds = max(end - inject, 1)
        result = {}
        for service, group in frame.groupby("container_name"):
            service = str(service)
            messages = group["message"].fillna("").astype(str)
            after = (group["timestamp"] >= inject).to_numpy()
            is_error = messages.str.contains(ERROR_PATTERN).to_numpy()
            pre_count, post_count = int((~after).sum()), int(after.sum())
            pre_rate = pre_count / pre_seconds
            post_rate = post_count / post_seconds

            pre_templates = set(messages[~after].map(log_template))
            post_messages = messages[after]
            post_templates = post_messages.map(log_template)
            novel = post_templates[~post_templates.isin(pre_templates)]
            novel_examples = (
                post_messages[novel.index].groupby(novel).first()
                .loc[novel.value_counts().index[:5]].tolist()
                if len(novel) else []
            )
            error_examples = post_messages[is_error[after]].str.slice(0, 240)

            result[service] = {
                "pre_rate" : round(pre_rate, 4),
                "post_rate" : round(post_rate, 4),
                "rate_ratio" : round((post_rate + 0.01) / (pre_rate + 0.01), 4),
                "pre_error_rate" : round(float(is_error[~after].mean()) if pre_count else 0.0, 4),
                "post_error_rate" : round(float(is_error[after].mean()) if post_count else 0.0, 4),
                "novel_templates" : int(novel.nunique()),
                "novel_fraction" : round(len(novel) / max(1, post_count), 4),
                "novel_examples" : [m[:240] for m in novel_examples],
                "error_examples" : error_examples.value_counts().index[:5].tolist(),
            }
        return result

    def _trace_features(self, inject):
        path = self.path / "traces.parquet"
        if not path.exists():
            return {}, set()
        frame = pd.read_parquet(path, columns = [
            "spanID", "parentSpanID", "serviceName", "operationName",
            "startTimeMillis", "duration", "statusCode",
        ])
        frame["callee"] = frame["operationName"].astype(str).str.extract(OPERATION_SERVICE)[0].str.lower()
        frame["target"] = frame["callee"].fillna(frame["serviceName"].astype(str))
        status = pd.to_numeric(frame["statusCode"], errors = "coerce").fillna(0)
        # gRPC codes are non-zero on failure; HTTP codes fail at >= 500.
        frame["failed"] = ((status > 0) & (status < 100)) | (status >= 500)
        after = frame["startTimeMillis"].to_numpy(dtype = float) >= inject * 1000

        result = {}
        for service, group in frame.groupby("target"):
            mask = after[group.index]
            pre, post = group[~mask], group[mask]
            if len(pre) < 5 or len(post) < 5:
                continue
            result[str(service)] = {
                "pre_error_rate" : round(float(pre["failed"].mean()), 4),
                "post_error_rate" : round(float(post["failed"].mean()), 4),
                "pre_p90_ms" : round(float(pre["duration"].quantile(0.9)) / 1000, 3),
                "post_p90_ms" : round(float(post["duration"].quantile(0.9)) / 1000, 3),
                "latency_ratio" : round(
                    float((post["duration"].quantile(0.9) + 1) / (pre["duration"].quantile(0.9) + 1)), 4
                ),
                "spans" : int(len(group)),
            }

        edges = set()
        parents = frame.set_index("spanID")["serviceName"].astype(str)
        parents = parents[~parents.index.duplicated()]
        child_parent = frame["parentSpanID"].map(parents)
        for caller, callee in zip(child_parent, frame["serviceName"].astype(str)):
            if isinstance(caller, str) and caller != callee:
                edges.add((caller, callee))
        for caller, callee in zip(frame["serviceName"].astype(str), frame["callee"]):
            if isinstance(callee, str) and caller != callee:
                edges.add((caller, callee))
        return result, edges

    # ------------------------------------------------------------------ queries
    def service_score(self, service, key = "max_abs_z", family = None):
        values = [
            m[key] for m in self.metrics.values()
            if m["service"] == service and (family is None or m["family"] == family)
        ]
        return max(values, default = 0.0)

    def top_anomalies(self, k = 15):
        ranked = sorted(self.metrics.items(), key = lambda item: -item[1]["max_abs_z"])
        return [
            {"id" : f"MET:{name}", "z" : sig(m["max_abs_z"], 3), "dir" : m["direction"],
             "before" : sig(m["pre_median"]), "after" : sig(m["post_median"])}
            for name, m in ranked[:k]
        ]

    def service_metrics(self, service):
        return [
            {"id" : f"MET:{name}", "z" : sig(m["max_abs_z"], 3), "p95_z" : sig(m["p95_abs_z"], 3),
             "dir" : m["direction"], "before" : sig(m["pre_median"]), "after" : sig(m["post_median"])}
            for name, m in sorted(self.metrics.items(), key = lambda item: -item[1]["max_abs_z"])
            if m["service"] == service
        ]

    def service_logs(self, service):
        stats = self.logs.get(service)
        if stats is None:
            return {"available" : False}
        return {
            "available" : True,
            "evidence" : [
                {"id" : f"LOG:{service}:volume", "pre_rate_per_s" : stats["pre_rate"],
                 "post_rate_per_s" : stats["post_rate"], "rate_ratio" : stats["rate_ratio"]},
                {"id" : f"LOG:{service}:errors", "pre_error_rate" : stats["pre_error_rate"],
                 "post_error_rate" : stats["post_error_rate"],
                 "examples" : [e[:160] for e in stats["error_examples"][:3]]},
                {"id" : f"LOG:{service}:new", "novel_templates" : stats["novel_templates"],
                 "novel_fraction" : stats["novel_fraction"],
                 "examples" : [e[:160] for e in stats["novel_examples"][:3]]},
            ],
        }

    def service_traces(self, service):
        stats = self.traces.get(service)
        if stats is None:
            return {"available" : False}
        return {
            "available" : True,
            "evidence" : [
                {"id" : f"TRC:{service}:errors", "pre_error_rate" : stats["pre_error_rate"],
                 "post_error_rate" : stats["post_error_rate"]},
                {"id" : f"TRC:{service}:latency", "pre_p90_ms" : stats["pre_p90_ms"],
                 "post_p90_ms" : stats["post_p90_ms"], "latency_ratio" : stats["latency_ratio"]},
            ],
        }

    def neighbors(self, service):
        callers = sorted(c for c, callees in self.edges.items() if service in callees)
        return {"calls" : self.edges.get(service, []), "called_by" : callers}

    def evidence_ids(self):
        ids = {f"MET:{name}" for name in self.metrics}
        for service in self.logs:
            ids.update({f"LOG:{service}:volume", f"LOG:{service}:errors", f"LOG:{service}:new"})
        for service in self.traces:
            ids.update({f"TRC:{service}:errors", f"TRC:{service}:latency"})
        return ids

def baro_ranking(telemetry):
    """BARO-style baseline: rank services by their largest robust z-score.

    Ties (z-scores are capped) are broken by the 95th-percentile z-score.
    """
    scores = {
        s: (telemetry.service_score(s), telemetry.service_score(s, "p95_abs_z"))
        for s in telemetry.services
    }
    return sorted(scores, key = lambda s: scores[s], reverse = True)
