"""Standard root-cause-analysis ranking metrics (as used by RCAEval).

AC@k   share of cases whose true root-cause service is in the top k
Avg@5  mean of AC@1 .. AC@5
"""
import numpy as np

def rank_of(ranking, truth):
    """1-based position of the true service, or None when it is not ranked."""
    try:
        return ranking.index(truth) + 1
    except ValueError:
        return None

def summarize_ranks(ranks):
    ranks = [r if r is not None else 10**6 for r in ranks]
    if not ranks:
        return {}
    ac = {k: float(np.mean([r <= k for r in ranks])) for k in range(1, 6)}
    return {
        "cases" : len(ranks),
        "AC@1" : round(ac[1], 4),
        "AC@3" : round(ac[3], 4),
        "Avg@5" : round(float(np.mean(list(ac.values()))), 4),
    }

def summarize_by(frame, rank_column, group_column = "dataset"):
    """Overall and per-group metrics from a frame with one row per case."""
    result = {"overall" : summarize_ranks(list(frame[rank_column]))}
    for group, rows in frame.groupby(group_column):
        result[str(group)] = summarize_ranks(list(rows[rank_column]))
    return result
