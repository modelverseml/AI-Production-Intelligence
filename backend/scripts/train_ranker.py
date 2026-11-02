"""Train and evaluate the LightGBM root-cause ranker on RCAEval.

Usage (from backend/):
    python -m scripts.train_ranker

Outputs:
    data/rcaeval/ranker_oof.json      out-of-fold rankings (used by the agent's
                                      ml_ranking tool so no case is scored by a
                                      model that saw it during training)
    models/ranker.txt                 model trained on all cases (for new data)
    ranker_evaluation.json            BARO baseline vs. ranker

Evaluation protocols, strictest last:
    ranker_case_cv     folds split by case. Optimistic: other repetitions of
                       the same fault on the same service are in training.
    ranker_cv          folds split by root-cause service, so every test case's
                       faulty service was never a root cause in training.
                       This is the headline number.
    ranker_loso        trained on the other systems, tested on a held-out one.
"""
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

from app.ranker import MODEL_DIR, MODEL_PATH, OOF_PATH, candidate_features, feature_columns
from app.rca_metrics import rank_of, summarize_by
from app.telemetry import CaseTelemetry, available_cases, baro_ranking

SEED = 42
FOLDS = 5
OUTPUT = Path("ranker_evaluation.json")
PARAMS = dict(
    objective = "lambdarank",
    n_estimators = 300,
    learning_rate = 0.05,
    num_leaves = 15,
    min_child_samples = 10,
    subsample = 0.8,
    subsample_freq = 1,
    colsample_bytree = 0.8,
    random_state = SEED,
    verbose = -1,
)

def case_rows(case_id):
    telemetry = CaseTelemetry(case_id)
    meta = telemetry.meta
    frame = candidate_features(telemetry)
    frame["case"] = case_id
    frame["dataset"] = meta["dataset"]
    frame["system"] = meta["system"]
    frame["label"] = (frame["service"] == meta["root_cause_service"]).astype(int)
    baro = baro_ranking(telemetry)
    return frame, rank_of(baro, meta["root_cause_service"])

def fit(train):
    train = train.sort_values("case", kind = "stable")
    model = lgb.LGBMRanker(**PARAMS)
    model.fit(
        train[feature_columns(train)],
        train["label"],
        group = train.groupby("case", sort = True).size().to_numpy(),
    )
    return model

def predict_rankings(model, test):
    test = test.copy()
    test["score"] = model.predict(test[feature_columns(test)])
    rankings = {}
    for case, rows in test.groupby("case"):
        rows = rows.sort_values("score", ascending = False)
        rankings[case] = [
            {"service" : s, "score" : round(float(v), 5)}
            for s, v in zip(rows["service"], rows["score"])
        ]
    return rankings

def main():
    cases = available_cases()
    print(f"Building features for {len(cases)} cases...")
    with ProcessPoolExecutor() as pool:
        results = list(pool.map(case_rows, cases.index, chunksize = 4))
    frame = pd.concat([rows for rows, _ in results], ignore_index = True)
    baro_ranks = {case: rank for case, (_, rank) in zip(cases.index, results)}
    truth = cases["root_cause_service"]

    def cross_validate(groups):
        splitter = StratifiedGroupKFold(n_splits = FOLDS, shuffle = True, random_state = SEED)
        rankings = {}
        for train_idx, test_idx in splitter.split(frame, frame["dataset"], groups):
            model = fit(frame.iloc[train_idx])
            rankings.update(predict_rankings(model, frame.iloc[test_idx]))
        return rankings

    case_oof = cross_validate(frame["case"])
    root_cause_group = frame["case"].map(
        lambda c: f"{cases.loc[c, 'system']}:{cases.loc[c, 'root_cause_service']}"
    )
    oof = cross_validate(root_cause_group)

    # Leave-one-system-out: can the ranker generalize to an unseen system?
    loso = {}
    for system in sorted(frame["system"].unique()):
        model = fit(frame[frame["system"] != system])
        loso.update(predict_rankings(model, frame[frame["system"] == system]))

    summary = cases[["dataset", "system", "fault"]].copy()
    summary["baro"] = [baro_ranks[c] for c in summary.index]
    summary["ranker_case_cv"] = [
        rank_of([r["service"] for r in case_oof[c]], truth[c]) for c in summary.index
    ]
    summary["ranker_cv"] = [
        rank_of([r["service"] for r in oof[c]], truth[c]) for c in summary.index
    ]
    summary["ranker_loso"] = [
        rank_of([r["service"] for r in loso[c]], truth[c]) for c in summary.index
    ]
    candidates = frame.groupby("case").size()

    final = fit(frame)
    MODEL_DIR.mkdir(exist_ok = True)
    final.booster_.save_model(str(MODEL_PATH))
    OOF_PATH.write_text(json.dumps(oof))

    importance = pd.Series(
        final.booster_.feature_importance("gain"), index = final.booster_.feature_name()
    ).sort_values(ascending = False)

    report = {
        "cases" : len(cases),
        "protocol" : {
            "ranker_case_cv" : f"{FOLDS}-fold CV grouped by case (optimistic)",
            "ranker_cv" : f"{FOLDS}-fold CV grouped by root-cause service (headline)",
            "ranker_loso" : "trained on the other systems, tested on the held-out system",
            "baro" : "rank services by maximum robust z-score of their metrics (BARO-style)",
        },
        "chance_AC@1" : round(float((1 / candidates).mean()), 4),
        "methods" : {
            method : summarize_by(summary, method)
            for method in ("baro", "ranker_case_cv", "ranker_cv", "ranker_loso")
        },
        "by_fault" : {
            method : summarize_by(summary, method, "fault")
            for method in ("baro", "ranker_cv")
        },
        "top_features" : {k: round(float(v), 1) for k, v in importance.head(12).items()},
    }
    OUTPUT.write_text(json.dumps(report, indent = 2))

    table = pd.DataFrame({
        method : {ds: m["AC@1"] for ds, m in report["methods"][method].items()}
        for method in report["methods"]
    })
    print("\nAC@1")
    print(table.round(3).to_string())
    print("\nAvg@5")
    print(pd.DataFrame({
        method : {ds: m["Avg@5"] for ds, m in report["methods"][method].items()}
        for method in report["methods"]
    }).round(3).to_string())
    print("\nTop features:", list(report["top_features"])[:8])
    print(f"\nWrote {OUTPUT.resolve()}, {MODEL_PATH}, {OOF_PATH}")

if __name__ == "__main__":
    main()
