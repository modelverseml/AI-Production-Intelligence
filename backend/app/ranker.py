"""Learned root-cause service ranker (LightGBM LambdaRank).

Each candidate service in a case becomes one row of features built from the
telemetry evidence; the model learns to rank the true root-cause service first.
"""
import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from app.telemetry import DATA_DIR, INDICATOR_FAMILIES

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_PATH = MODEL_DIR / "ranker.txt"
OOF_PATH = DATA_DIR / "ranker_oof.json"
ANOMALY_Z = 10.0

def candidate_features(telemetry):
    """One feature row per candidate service.

    Features describe only how a service's telemetry changed. Structural
    features (call-graph degree, "is a database") were tried and dropped: they
    let the model memorize which services the benchmark tends to break, which
    hurt accuracy on root-cause services held out from training.
    """
    services = telemetry.services
    z_all = {s: telemetry.service_score(s) for s in services}
    p95_all = {s: telemetry.service_score(s, "p95_abs_z") for s in services}
    max_z = max(z_all.values(), default = 0.0) or 1.0
    z_rank = pd.Series(z_all).rank(ascending = False, method = "min")
    p95_rank = pd.Series(p95_all).rank(ascending = False, method = "min")

    rows = []
    for service in services:
        row = {"service" : service}
        for family in INDICATOR_FAMILIES:
            row[f"z_{family}"] = telemetry.service_score(service, "max_abs_z", family)
            row[f"p95_{family}"] = telemetry.service_score(service, "p95_abs_z", family)
        row["z_all"] = z_all[service]
        row["p95_all"] = p95_all[service]
        row["z_relative"] = z_all[service] / max_z
        row["z_rank"] = float(z_rank[service])
        row["p95_rank"] = float(p95_rank[service])
        row["n_anomalous_metrics"] = sum(
            1 for m in telemetry.metrics.values()
            if m["service"] == service and m["max_abs_z"] >= ANOMALY_Z
        )

        logs = telemetry.logs.get(service)
        row["has_logs"] = float(logs is not None)
        row["log_rate_ratio"] = math.log(logs["rate_ratio"]) if logs else 0.0
        row["log_error_delta"] = logs["post_error_rate"] - logs["pre_error_rate"] if logs else 0.0
        row["log_error_post"] = logs["post_error_rate"] if logs else 0.0
        row["log_novel_templates"] = math.log1p(logs["novel_templates"]) if logs else 0.0
        row["log_novel_fraction"] = logs["novel_fraction"] if logs else 0.0

        traces = telemetry.traces.get(service)
        row["has_traces"] = float(traces is not None)
        row["trace_error_delta"] = traces["post_error_rate"] - traces["pre_error_rate"] if traces else 0.0
        row["trace_error_post"] = traces["post_error_rate"] if traces else 0.0
        row["trace_latency_ratio"] = math.log(traces["latency_ratio"]) if traces else 0.0

        rows.append(row)
    return pd.DataFrame(rows)

def feature_columns(frame):
    return [c for c in frame.columns if c not in ("service", "case", "label", "dataset", "system")]

@lru_cache(maxsize = 1)
def load_model():
    import lightgbm as lgb
    if not MODEL_PATH.exists():
        return None
    return lgb.Booster(model_file = str(MODEL_PATH))

@lru_cache(maxsize = 1)
def load_oof():
    if not OOF_PATH.exists():
        return {}
    return json.loads(OOF_PATH.read_text())

def softmax(scores):
    scores = np.asarray(scores, dtype = float)
    exp = np.exp(scores - scores.max())
    return exp / exp.sum()

def ml_ranking(telemetry, k = 5):
    """Top-k services with probabilities.

    Benchmark cases use out-of-fold predictions so the model never scores a
    case it was trained on; other cases use the model trained on all data.
    """
    oof = load_oof().get(telemetry.case_id)
    if oof is not None:
        ranked = oof
    else:
        model = load_model()
        if model is None:
            return []
        frame = candidate_features(telemetry)
        scores = model.predict(frame[model.feature_name()])
        ranked = [
            {"service" : s, "score" : float(v)}
            for s, v in sorted(zip(frame["service"], scores), key = lambda item: -item[1])
        ]
    probabilities = softmax([item["score"] for item in ranked])
    return [
        {"service" : item["service"], "probability" : round(float(p), 4)}
        for item, p in list(zip(ranked, probabilities))[:k]
    ]
