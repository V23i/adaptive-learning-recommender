#!/usr/bin/env python3
"""Validate a generated dataset: PK/FK/enums/dates/arithmetic/lifecycles/duplicates/prerequisites/mastery
reproducibility, then score the findings against ground_truth.csv (used for scoring only).

Usage: python validate.py data/starter     (writes validation_summary.json / .md next to the data)
"""
import csv, json, os, sys
from collections import defaultdict

import generate as G
import mastery as M
from mastery import margin_of, mastery_at, mastery_from

EXPLAINED = {  # finding -> issue_type that legitimately explains it
    "fk:content_skill.skill_id": "CONTENT_SKILL_ORPHAN",
    "attempt_submitted_before_started": "ATT_TIMESTAMP_ORDER",
    "attempt_duration_mismatch": "ATT_TIMESTAMP_ORDER",
    "recommendation_prereq_unmet": "REC_PREREQ_VIOLATION",
    "recommendation_basis_attempt_in_future": "MASTERY_FUTURE_LEAK",
    "recommendation_mastery_not_reproducible": "MASTERY_FUTURE_LEAK",
    "path_loop_without_progress": "PATH_LOOP",
}


def read(d, name):
    with open(os.path.join(d, name + ".csv"), newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        head = next(r)
        return head, list(r)


def run(d, quiet=False):
    S, heads = {}, {}
    for t in G.F:
        if t == "attempt":
            continue
        h, rows = read(d, t)
        heads[t] = h
        S[t] = [dict(zip(h, r)) for r in rows]
    h, rows = read(d, "attempt")
    heads["attempt"] = h
    A = [(r[0], r[1], r[2], r[3], int(r[4]), M.to_sec(r[5]), M.to_sec(r[6]), int(r[7]), float(r[8]), float(r[9]), int(r[10]), r[11] or None)
         for r in rows]
    del rows
    F = defaultdict(list)
    bad = lambda check, eid: F[check].append(eid)

    # --- schema, leakage of ground truth into inputs
    for t in G.F:
        if heads[t] != G.COLS[t]:
            bad("schema_columns_mismatch", t)
        for c in heads[t]:
            if {"issue", "ground", "truth", "anomaly", "ability", "label"} & set(c.lower().split("_")):
                bad("ground_truth_leak_in_input_columns", f"{t}.{c}")

    # --- primary keys
    ids = {}
    for t in G.F:
        if t == "attempt":
            ids[t] = [a[0] for a in A]
        else:
            ids[t] = ["|".join(r[c] for c in G.PKS[t]) for r in S[t]]
        seen = set()
        for x in ids[t]:
            if x in seen:
                bad(f"pk_duplicate:{t}", x)
            seen.add(x)
    keyset = {t: set(v) for t, v in ids.items()}

    # --- foreign keys
    AI = {c: i for i, c in enumerate(G.COLS["attempt"])}
    for ct, cc, pt, pc in G.FKS:
        parent = keyset[pt]
        for i, eid in enumerate(ids[ct]):
            v = A[i][AI[cc]] if ct == "attempt" else S[ct][i][cc]
            if v not in (None, "") and v not in parent:
                bad(f"fk:{ct}.{cc}", eid)

    # --- enums / ranges
    for (t, c), allowed in G.ENUMS.items():
        for i, r in enumerate(S[t]):
            if r[c] not in allowed:
                bad(f"enum:{t}.{c}", ids[t][i])
    for r in S["content_item"]:
        if not (1 <= int(r["difficulty"]) <= 5):
            bad("range:content_item.difficulty", r["content_id"])
    for a in A:
        if not (0 <= a[8] <= a[9]):
            bad("range:attempt.score", a[0])
    prim = defaultdict(int)
    for r in S["content_skill"]:
        prim[r["content_id"]] += int(r["is_primary"])
    for c in keyset["content_item"]:
        if prim[c] != 1:
            bad("content_without_single_primary_skill", c)

    # --- skill graph is a DAG
    indeg, adj = defaultdict(int), defaultdict(list)
    for r in S["skill_prerequisite"]:
        adj[r["prerequisite_skill_id"]].append(r["skill_id"])
        indeg[r["skill_id"]] += 1
    q = [s for s in keyset["skill"] if indeg[s] == 0]
    n = 0
    while q:
        s = q.pop(); n += 1
        for t_ in adj[s]:
            indeg[t_] -= 1
            if indeg[t_] == 0:
                q.append(t_)
    if n != len(keyset["skill"]):
        bad("skill_graph_has_cycle", "skill_prerequisite")

    # --- lookups
    skill_ids = keyset["skill"]
    cs = defaultdict(list)
    for r in S["content_skill"]:
        if r["skill_id"] in skill_ids:
            cs[r["content_id"]].append((r["skill_id"], float(r["weight"])))
    for v in cs.values():
        v.sort(key=lambda x: -x[1])
    prereq = defaultdict(list)
    for r in S["skill_prerequisite"]:
        prereq[r["skill_id"]].append((r["prerequisite_skill_id"], float(r["min_mastery"])))
    content = {r["content_id"]: r for r in S["content_item"]}
    signup = {r["learner_id"]: M.to_sec(r["signup_date"]) for r in S["learner"]}

    # --- attempts: ordering, arithmetic, windows, duplicates, sequence
    seen_dup, last_sub_by = set(), {}
    for a in A:
        aid, lid, c, _, no, st, sb, dur, sc, mx, ps, rec = a
        if sb < st:
            bad("attempt_submitted_before_started", aid)
        elif dur != sb - st:
            bad("attempt_duration_mismatch", aid)
        if sb >= st and dur != sb - st:
            pass
        if (lid, c, st) in seen_dup:
            bad("duplicate_attempt", aid)
        seen_dup.add((lid, c, st))
        ci = content.get(c)
        if ci:
            if ps != (1 if sc >= int(ci["pass_mark"]) else 0):
                bad("attempt_passed_mismatch", aid)
            if ci["published_at"] == "" or M.to_sec(ci["published_at"]) > st:
                bad("attempt_before_content_published", aid)
            if ci["retired_at"] and M.to_sec(ci["retired_at"]) <= sb:
                bad("attempt_after_content_retired", aid)
        if lid in signup and st < signup[lid]:
            bad("attempt_before_signup", aid)
    del seen_dup

    order = sorted(range(len(A)), key=lambda i: (A[i][1], A[i][6], A[i][0]))
    EV, gap, ba, cur, mast, nby, prev_sub = defaultdict(list), set(), {}, None, {}, defaultdict(int), None
    for i in order:
        a = A[i]
        if a[1] != cur:
            cur, mast, prev_sub = a[1], {}, None
        sk = cs.get(a[2], [])
        mg = margin_of(sk, prereq, mast.get)
        if mg is not None and mg < 0:
            gap.add(a[0])
        nby[(a[1], a[2])] += 1
        if a[4] != nby[(a[1], a[2])]:
            bad("attempt_no_not_sequential", a[0])
        if prev_sub is not None and a[5] < prev_sub:
            bad("attempts_overlap_for_learner", a[0])
        prev_sub = a[6]
        before = mast.get(sk[0][0]) if sk else None
        for s, w in sk:
            ev = EV[(a[1], s)]
            ev.append((a[6], a[8] / 100.0, w))
            mast[s] = mastery_from(ev)
        ba[a[0]] = (before, mast.get(sk[0][0]) if sk else None)
    asub = {a[0]: a[6] for a in A}
    arec = {a[0]: (a[11], a[8], a[10], a[5], a[6]) for a in A}

    # --- assessment results (derived values)
    for r in S["assessment_result"]:
        b = ba.get(r["attempt_id"])
        if b is None:
            continue
        mb = float(r["mastery_before"]) if r["mastery_before"] != "" else None
        ma = float(r["mastery_after"])
        if (mb is None) != (b[0] is None) or (mb is not None and abs(mb - b[0]) > 1e-9) or abs(ma - b[1]) > 1e-9:
            bad("assessment_mastery_not_reproducible", r["result_id"])
        if r["proficiency_band"] != M.band(ma):
            bad("assessment_band_mismatch", r["result_id"])
        if abs(float(r["score_pct"]) - arec[r["attempt_id"]][1]) > 1e-9:
            bad("assessment_score_mismatch", r["result_id"])

    # --- recommendations: prerequisites, reproducible mastery, no future data, reason codes, outcomes
    for r in S["recommendation"]:
        rid, l, t = r["recommendation_id"], r["learner_id"], M.to_sec(r["issued_at"])
        sk = cs.get(r["content_id"], [])
        getm = lambda pre: mastery_at(EV.get((l, pre), []), t)
        mg = margin_of(sk, prereq, getm)
        if mg is not None and mg < 0:
            bad("recommendation_prereq_unmet", rid)
        stored = float(r["prereq_margin"]) if r["prereq_margin"] != "" else None
        if (stored is None) != (mg is None) or (stored is not None and abs(stored - mg) > 1e-9):
            bad("recommendation_margin_mismatch", rid)
        m = getm(r["target_skill_id"])
        sm = float(r["target_skill_mastery"]) if r["target_skill_mastery"] != "" else None
        if (sm is None) != (m is None) or (sm is not None and abs(sm - m) > 1e-9):
            bad("recommendation_mastery_not_reproducible", rid)
        if r["as_of_attempt_id"] and asub.get(r["as_of_attempt_id"], 0) > t:
            bad("recommendation_basis_attempt_in_future", rid)
        if not r["reason_code"] or not r["rationale"]:
            bad("recommendation_missing_reason", rid)
        if r["status"] == "ACCEPTED":
            o = arec.get(r["outcome_attempt_id"])
            if not o or o[0] != rid or abs(o[1] - float(r["outcome_score"])) > 1e-9 or o[2] != int(r["outcome_passed"]):
                bad("recommendation_outcome_mismatch", rid)
            elif o[3] < t:
                bad("recommendation_outcome_before_issue", rid)
        elif r["outcome_attempt_id"]:
            bad("recommendation_outcome_on_non_accepted", rid)

    # --- lifecycle: recommendation events
    by = defaultdict(list)
    for e in S["recommendation_event"]:
        by[e["recommendation_id"]].append(e)
    rec_status = {r["recommendation_id"]: r["status"] for r in S["recommendation"]}
    want = {"ACCEPTED": ["ISSUED", "ACCEPTED", "COMPLETED"], "EXPIRED": ["ISSUED", "EXPIRED"], "PENDING": ["ISSUED"]}
    for rid, st in rec_status.items():
        evs = sorted(by.get(rid, []), key=lambda e: e["event_id"])
        if [e["event_type"] for e in evs] != want[st] or [M.to_sec(e["event_ts"]) for e in evs] != sorted(M.to_sec(e["event_ts"]) for e in evs):
            bad("recommendation_event_chain_invalid", rid)

    # --- lifecycle: path events, transitions, loops
    allowed = {(None, "CREATED"), ("CREATED", "ACTIVE"), ("CREATED", "ABANDONED"), ("ACTIVE", "ACTIVE"), ("ACTIVE", "COMPLETED"),
               ("ACTIVE", "ABANDONED"), ("ACTIVE", "STALLED")}
    pe = defaultdict(list)
    for e in S["learning_path_event"]:
        pe[e["path_id"]].append(e)
    for p in S["learning_path"]:
        evs = sorted(pe.get(p["path_id"], []), key=lambda e: int(e["event_seq"]))
        if not evs or [int(e["event_seq"]) for e in evs] != list(range(1, len(evs) + 1)):
            bad("path_event_seq_invalid", p["path_id"]); continue
        ok, prev = True, None
        for e in evs:
            if (e["from_status"] or None) != prev or ((e["from_status"] or None), e["to_status"]) not in allowed:
                ok = False
            prev = e["to_status"]
        ts = [M.to_sec(e["event_ts"]) for e in evs]
        if not ok or ts != sorted(ts) or prev != p["status"]:
            bad("path_lifecycle_invalid", p["path_id"])
        run_, cons = [], 0
        loop = False
        for e in evs:
            if e["event_type"] == "STEP_REVISITED":
                run_.append(e)
            else:
                if len(run_) >= 5 and len({x["content_id"] for x in run_}) <= 2 and len({x["mastery_after"] for x in run_}) == 1:
                    loop = True
                run_ = []
        if len(run_) >= 5 and len({x["content_id"] for x in run_}) <= 2 and len({x["mastery_after"] for x in run_}) == 1:
            loop = True
        if loop:
            bad("path_loop_without_progress", p["path_id"])

    # --- score against ground truth (scoring only)
    gt = list(csv.DictReader(open(os.path.join(d, "ground_truth.csv"), encoding="utf-8")))
    gt_ids = defaultdict(set)
    for g in gt:
        gt_ids[g["issue_type"]].add(g["entity_id"])
    detected = defaultdict(set)
    for chk, typ in EXPLAINED.items():
        detected[typ] |= set(F.get(chk, []))
    detection = {}
    for typ in G.ISSUE_TYPES:
        tp, fp, fn = detected[typ] & gt_ids[typ], detected[typ] - gt_ids[typ], gt_ids[typ] - detected[typ]
        detection[typ] = dict(labelled=len(gt_ids[typ]), detected=len(detected[typ]), true_pos=len(tp), false_pos=len(fp), false_neg=len(fn))
    lab = {r["attempt_id"] for r in csv.DictReader(open(os.path.join(d, "ground_truth_labels.csv")))}
    gap_ok = lab == gap
    unexplained = {}
    for chk, ids_ in F.items():
        allowed_ids = gt_ids.get(EXPLAINED.get(chk), set())
        rest = [x for x in ids_ if x not in allowed_ids]
        if rest:
            unexplained[chk] = rest[:5] + ([f"... +{len(rest) - 5} more"] if len(rest) > 5 else [])
    passed = not unexplained and gap_ok and all(v["false_pos"] == 0 and v["false_neg"] == 0 for v in detection.values())
    summary = dict(passed=passed, table_rows={t: len(ids[t]) for t in G.F}, findings={k: len(v) for k, v in sorted(F.items())},
                   unexplained_findings=unexplained, injected_issue_detection=detection,
                   natural_prereq_gap_attempts=dict(labelled=len(lab), recomputed=len(gap), identical=gap_ok),
                   checks_run=["schema", "pk_unique", "fk_integrity", "enums_ranges", "dag_acyclic", "date_ordering", "arithmetic(duration,passed,attempt_no)",
                               "mastery_reproducible(recompute from attempts)", "no_future_data", "prerequisites_respected", "reason_codes_present",
                               "lifecycle(path,recommendation)", "duplicates", "ground_truth_not_in_inputs"])
    with open(os.path.join(d, "validation_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    md = ["# Validation summary", "", f"Result: **{'PASS' if passed else 'FAIL'}**", "", "| issue_type | labelled | detected | TP | FP | FN |", "|---|---|---|---|---|---|"]
    md += [f"| {k} | {v['labelled']} | {v['detected']} | {v['true_pos']} | {v['false_pos']} | {v['false_neg']} |" for k, v in detection.items()]
    md += ["", f"Natural prerequisite-gap attempts: {len(lab)} labelled, recomputed identically: {gap_ok}", "",
           "Unexplained findings (must be empty): " + (json.dumps(unexplained) if unexplained else "none"), "",
           "Rows: " + ", ".join(f"{k}={v}" for k, v in summary["table_rows"].items())]
    with open(os.path.join(d, "validation_summary.md"), "w") as f:
        f.write("\n".join(md) + "\n")
    if not quiet:
        print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    s = run(sys.argv[1] if len(sys.argv) > 1 else "data/starter")
    sys.exit(0 if s["passed"] else 1)
