#!/usr/bin/env python3
"""Evaluate the rule-based recommender on a TEMPORAL split (train: issued_at < 2026-07-01, test: >= 2026-07-01).

Metrics (test period, resolved recommendations only unless noted):
  acceptance_rate, pass_rate_accepted vs pass_rate_self_selected (lift), prerequisite_compliance,
  reason_code_coverage, mean_abs_difficulty_gap, and a Brier score for an acceptance-propensity model
  (per-reason-code rates fitted on TRAIN only) against a global-rate baseline.
ground_truth.csv is used only to report a 'clean' variant that excludes injected anomalies; it never feeds a model.

Usage: python evaluate.py data/starter
"""
import csv, json, os, sys
from collections import defaultdict
import generate as G
import mastery as M


def rate(xs):
    return round(sum(xs) / len(xs), 4) if xs else None


def run(d, quiet=False):
    split = M.to_sec(G.SPLIT_DATE)
    recs = list(csv.DictReader(open(os.path.join(d, "recommendation.csv"), encoding="utf-8")))
    bad = defaultdict(set)
    for g in csv.DictReader(open(os.path.join(d, "ground_truth.csv"), encoding="utf-8")):
        bad[g["entity"]].add(g["entity_id"])
    sp_pass, sp_n = [], 0
    with open(os.path.join(d, "attempt.csv"), newline="", encoding="utf-8") as f:
        r = csv.reader(f); next(r)
        for row in r:
            if M.to_sec(row[5]) >= split and not row[11]:
                sp_pass.append(int(row[10]))
    out = {"split_date": G.SPLIT_DATE}
    for variant in ("all", "clean"):
        rs = [x for x in recs if variant == "all" or x["recommendation_id"] not in bad["recommendation"]]
        for x in rs:
            x["_t"] = M.to_sec(x["issued_at"])
        train = [x for x in rs if x["_t"] < split and x["status"] != "PENDING"]
        test = [x for x in rs if x["_t"] >= split]
        res = [x for x in test if x["status"] != "PENDING"]
        acc = [x for x in res if x["status"] == "ACCEPTED"]
        by = defaultdict(list)
        for x in train:
            by[x["reason_code"]].append(x["status"] == "ACCEPTED")
        g_rate = rate([x["status"] == "ACCEPTED" for x in train]) or 0.0
        pr = {k: rate(v) for k, v in by.items()}
        y = [1.0 if x["status"] == "ACCEPTED" else 0.0 for x in res]
        brier = lambda ps: round(sum((p - t) ** 2 for p, t in zip(ps, y)) / len(y), 4) if y else None
        out[variant] = dict(
            train_recommendations=len(train), test_recommendations=len(test), test_resolved=len(res),
            acceptance_rate=rate(y),
            pass_rate_accepted=rate([int(x["outcome_passed"]) for x in acc]),
            pass_rate_self_selected=rate(sp_pass),
            pass_rate_lift=(round(rate([int(x["outcome_passed"]) for x in acc]) - rate(sp_pass), 4) if acc and sp_pass else None),
            prerequisite_compliance=rate([1 if (x["prereq_margin"] == "" or float(x["prereq_margin"]) >= 0) else 0 for x in test]),
            reason_code_coverage=rate([1 if x["reason_code"] and x["rationale"] else 0 for x in test]),
            mean_abs_difficulty_gap=rate([abs(int(x["difficulty_gap"])) for x in test]),
            acceptance_by_reason_code_train=pr,
            brier_reason_code_model=brier([pr.get(x["reason_code"], g_rate) or g_rate for x in res]),
            brier_global_rate_baseline=brier([g_rate] * len(res)),
            test_reason_code_mix={k: sum(1 for x in test if x["reason_code"] == k) for k in G.REASONS})
    with open(os.path.join(d, "evaluation.json"), "w") as f:
        json.dump(out, f, indent=2)
    if not quiet:
        print(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "data/starter")
