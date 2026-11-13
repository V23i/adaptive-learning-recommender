#!/usr/bin/env python3
"""Synthetic adaptive-learning dataset generator (stdlib only, fully deterministic).

Usage:  python generate.py --scale starter --out data/starter
        python generate.py --scale full --out data/full --formats csv
"""
import argparse, csv, hashlib, json, math, os, random, shutil, sys
from collections import defaultdict
from datetime import datetime

import mastery as M
from mastery import DAY, margin_of, mastery_at, mastery_from, desired_diff

SEED = 20261022
SCALES = {
    "starter": dict(learners=500, skills=60, content=200, attempts=10000, courses=6),
    "full": dict(learners=10000, skills=500, content=2000, attempts=500000, courses=40),
}
CUTOFF = (datetime(2026, 10, 22) - M.T0).days * DAY      # data cut-off (sec since 2025-01-01)
SPLIT_DATE = "2026-07-01"                                # temporal train/test split on issued_at
REC_EVERY, FOLLOW_P, GAP_P, RETRY_P = 10, 0.65, 0.12, 0.35
EXPIRE_DAYS, ABANDON_DAYS, COMPLETE_SKILLS, COMPLETE_M = 14, 45, 5, 0.7
INF = 10 ** 12
FORMATS = ["video", "reading", "quiz", "exercise", "project", "assessment"]
FORMAT_P = [.25, .20, .20, .15, .08, .12]
DUR = {"video": (8, 25), "reading": (5, 20), "quiz": (5, 15), "exercise": (15, 40), "project": (40, 60), "assessment": (20, 45)}
SUBJECTS = ["Python", "Statistics", "Databases", "WebDev", "MachineLearning", "Cloud", "Algorithms", "Security", "DataViz", "Math"]
COUNTRIES = ["IN", "US", "GB", "DE", "BR", "NG", "ID", "PH"]
COUNTRY_P = [.30, .20, .08, .06, .10, .08, .10, .08]
EDU = ["HIGH_SCHOOL", "UNDERGRAD", "POSTGRAD", "PROFESSIONAL"]
EDU_P = [.15, .45, .20, .20]
REASONS = ["COLD_START_DEFAULT", "NEW_SKILL_UNLOCK", "GAP_REMEDIATION", "DIFFICULTY_MATCH", "ENRICHMENT"]
ISSUE_TYPES = ["REC_PREREQ_VIOLATION", "ATT_TIMESTAMP_ORDER", "CONTENT_SKILL_ORPHAN", "MASTERY_FUTURE_LEAK", "PATH_LOOP"]

# --------------------------------------------------------------------------- schema (single source of truth)
# (column, sql type, required, kind, rule/description)
F = {
 "learner": [
  ("learner_id", "TEXT", "Y", None, "PK, LRN-######, immutable"),
  ("signup_date", "DATE", "Y", "date", "UTC date within 2025-01-01..2026-10-22"),
  ("country", "TEXT", "Y", None, "enum " + "/".join(COUNTRIES)),
  ("education_level", "TEXT", "Y", None, "enum " + "/".join(EDU)),
  ("preferred_format", "TEXT", "Y", None, "content format enum; +0.3 ranking bonus when it matches"),
  ("cohort", "TEXT", "Y", None, "YYYY-Qn derived from signup_date"),
  ("status", "TEXT", "Y", None, "ACTIVE|DORMANT; DORMANT = no attempt within 60 days before cut-off (derived)")],
 "course": [
  ("course_id", "TEXT", "Y", None, "PK, CRS-######"),
  ("title", "TEXT", "Y", None, "free text"),
  ("subject_area", "TEXT", "Y", None, "one of generator subjects"),
  ("status", "TEXT", "Y", None, "ACTIVE"),
  ("created_at", "DATE", "Y", "date", "UTC date")],
 "skill": [
  ("skill_id", "TEXT", "Y", None, "PK, SKL-######"),
  ("course_id", "TEXT", "Y", None, "FK course; home course (1:N)"),
  ("name", "TEXT", "Y", None, "free text"),
  ("level", "INTEGER", "Y", None, "1..5, derived from prerequisite-graph depth"),
  ("status", "TEXT", "Y", None, "ACTIVE"),
  ("created_at", "DATE", "Y", "date", "UTC date")],
 "skill_prerequisite": [
  ("skill_id", "TEXT", "Y", None, "FK skill (dependent skill)"),
  ("prerequisite_skill_id", "TEXT", "Y", None, "FK skill; numerically lower than skill_id (graph is a DAG); pair unique"),
  ("min_mastery", "REAL", "Y", None, "0..1; one of 0.5/0.6/0.7; mastery needed to satisfy the edge"),
  ("effective_from", "DATE", "Y", "date", "UTC date"),
  ("effective_to", "DATE", "N", "date", "NULL = open-ended; > effective_from")],
 "content_item": [
  ("content_id", "TEXT", "Y", None, "PK, CNT-######"),
  ("course_id", "TEXT", "Y", None, "FK course"),
  ("title", "TEXT", "Y", None, "free text"),
  ("format", "TEXT", "Y", None, "enum " + "/".join(FORMATS)),
  ("difficulty", "INTEGER", "Y", None, "1..5 (ordinal)"),
  ("duration_min", "INTEGER", "Y", None, "minutes, 5..60"),
  ("pass_mark", "INTEGER", "Y", None, "percent: 60 default, 65 assessment, 70 project"),
  ("status", "TEXT", "Y", None, "DRAFT|PUBLISHED|RETIRED"),
  ("published_at", "DATE", "N", "date", "NULL iff DRAFT"),
  ("retired_at", "DATE", "N", "date", "NOT NULL iff RETIRED; > published_at")],
 "content_skill": [
  ("content_id", "TEXT", "Y", None, "FK content_item"),
  ("skill_id", "TEXT", "Y", None, "FK skill"),
  ("weight", "REAL", "Y", None, "1.0 primary, 0.5 secondary; evidence weight in mastery"),
  ("is_primary", "INTEGER", "Y", None, "0/1; exactly one primary per content")],
 "learning_path": [
  ("path_id", "TEXT", "Y", None, "PK, PATH-2026-######"),
  ("learner_id", "TEXT", "Y", None, "FK learner"),
  ("course_id", "TEXT", "Y", None, "FK course; (learner_id, course_id) unique"),
  ("target_skill_id", "TEXT", "Y", None, "FK skill; last skill of the course (informational goal)"),
  ("status", "TEXT", "Y", None, "CREATED|ACTIVE|COMPLETED|ABANDONED|STALLED; equals to_status of last event"),
  ("created_at", "TIMESTAMP", "Y", "ts", "UTC"),
  ("closed_at", "TIMESTAMP", "N", "ts", "set for COMPLETED/ABANDONED")],
 "learning_path_event": [
  ("event_id", "TEXT", "Y", None, "PK, EVT-######"),
  ("path_id", "TEXT", "Y", None, "FK learning_path"),
  ("event_seq", "INTEGER", "Y", None, "1..n contiguous per path"),
  ("event_type", "TEXT", "Y", None, "CREATED|ACTIVATED|SKILL_MASTERED|COMPLETED|ABANDONED|STEP_REVISITED|STALLED"),
  ("from_status", "TEXT", "N", None, "NULL only for CREATED"),
  ("to_status", "TEXT", "Y", None, "path status enum"),
  ("event_ts", "TIMESTAMP", "Y", "ts", "UTC, non-decreasing per path"),
  ("skill_id", "TEXT", "N", None, "FK skill"),
  ("content_id", "TEXT", "N", None, "FK content_item"),
  ("mastery_after", "REAL", "N", None, "0..1"),
  ("attempt_id", "TEXT", "N", None, "FK attempt")],
 "attempt": [
  ("attempt_id", "TEXT", "Y", None, "PK, ATT-<learner-id>-######, sequential per learner in time order"),
  ("learner_id", "TEXT", "Y", None, "FK learner"),
  ("content_id", "TEXT", "Y", None, "FK content_item"),
  ("path_id", "TEXT", "Y", None, "FK learning_path (learner x content's course)"),
  ("attempt_no", "INTEGER", "Y", None, "1.. per (learner, content); >1 = repeated attempt"),
  ("started_at", "TIMESTAMP", "Y", "ts", "UTC; within content active window"),
  ("submitted_at", "TIMESTAMP", "Y", "ts", "UTC; >= started_at"),
  ("duration_sec", "INTEGER", "Y", None, "= submitted_at - started_at, 60..3600"),
  ("score", "REAL", "Y", None, "0..100, 1 dp"),
  ("max_score", "REAL", "Y", None, "100"),
  ("passed", "INTEGER", "Y", None, "0/1 = score >= content.pass_mark"),
  ("recommendation_id", "TEXT", "N", None, "FK recommendation when the attempt followed a recommendation")],
 "assessment_result": [
  ("result_id", "TEXT", "Y", None, "PK, RES-######; one per attempt on assessment-format content"),
  ("attempt_id", "TEXT", "Y", None, "FK attempt (1:1)"),
  ("learner_id", "TEXT", "Y", None, "FK learner"),
  ("skill_id", "TEXT", "Y", None, "FK skill; primary skill of the content"),
  ("score_pct", "REAL", "Y", None, "= attempt.score"),
  ("mastery_before", "REAL", "N", None, "mastery of skill before the attempt (NULL = no evidence)"),
  ("mastery_after", "REAL", "Y", None, "mastery after the attempt (mastery.py)"),
  ("proficiency_band", "TEXT", "Y", None, "NOVICE<0.4<=DEVELOPING<0.6<=PROFICIENT<0.8<=MASTERED, from mastery_after"),
  ("recorded_at", "TIMESTAMP", "Y", "ts", "= attempt.submitted_at")],
 "recommendation": [
  ("recommendation_id", "TEXT", "Y", None, "PK, REC-######"),
  ("learner_id", "TEXT", "Y", None, "FK learner"),
  ("path_id", "TEXT", "Y", None, "FK learning_path"),
  ("content_id", "TEXT", "Y", None, "FK content_item (recommended item)"),
  ("target_skill_id", "TEXT", "Y", None, "FK skill (primary skill of the content)"),
  ("issued_at", "TIMESTAMP", "Y", "ts", "UTC"),
  ("reason_code", "TEXT", "Y", None, "enum " + "/".join(REASONS)),
  ("rationale", "TEXT", "Y", None, "human-readable explanation"),
  ("target_skill_mastery", "REAL", "N", None, "mastery of target skill using attempts with submitted_at <= issued_at"),
  ("prereq_margin", "REAL", "N", None, "min over direct prerequisites of (mastery - min_mastery); NULL = no prerequisites; must be >= 0"),
  ("difficulty_gap", "INTEGER", "Y", None, "content difficulty - desired difficulty (1+round(4*mastery); 2 if unseen)"),
  ("rank_score", "REAL", "Y", None, "rule score used for ranking"),
  ("as_of_attempt_id", "TEXT", "N", None, "FK attempt; newest attempt used; submitted_at must be <= issued_at"),
  ("model_version", "TEXT", "Y", None, "rules-v1"),
  ("status", "TEXT", "Y", None, "ACCEPTED|EXPIRED|PENDING (final snapshot; history in recommendation_event)"),
  ("resolved_at", "TIMESTAMP", "N", "ts", "NULL while PENDING"),
  ("outcome_attempt_id", "TEXT", "N", None, "FK attempt; set when ACCEPTED"),
  ("outcome_score", "REAL", "N", None, "= outcome attempt score"),
  ("outcome_passed", "INTEGER", "N", None, "= outcome attempt passed")],
 "recommendation_event": [
  ("event_id", "TEXT", "Y", None, "PK, RCE-######"),
  ("recommendation_id", "TEXT", "Y", None, "FK recommendation"),
  ("event_type", "TEXT", "Y", None, "ISSUED|ACCEPTED|COMPLETED|EXPIRED"),
  ("event_ts", "TIMESTAMP", "Y", "ts", "UTC"),
  ("attempt_id", "TEXT", "N", None, "FK attempt for ACCEPTED/COMPLETED")],
}
PKS = {t: [F[t][0][0]] for t in F}
PKS["skill_prerequisite"] = ["skill_id", "prerequisite_skill_id"]
PKS["content_skill"] = ["content_id", "skill_id"]
FKS = [("skill", "course_id", "course", "course_id"),
       ("skill_prerequisite", "skill_id", "skill", "skill_id"), ("skill_prerequisite", "prerequisite_skill_id", "skill", "skill_id"),
       ("content_item", "course_id", "course", "course_id"),
       ("content_skill", "content_id", "content_item", "content_id"), ("content_skill", "skill_id", "skill", "skill_id"),
       ("learning_path", "learner_id", "learner", "learner_id"), ("learning_path", "course_id", "course", "course_id"),
       ("learning_path", "target_skill_id", "skill", "skill_id"),
       ("learning_path_event", "path_id", "learning_path", "path_id"), ("learning_path_event", "skill_id", "skill", "skill_id"),
       ("learning_path_event", "content_id", "content_item", "content_id"), ("learning_path_event", "attempt_id", "attempt", "attempt_id"),
       ("attempt", "learner_id", "learner", "learner_id"), ("attempt", "content_id", "content_item", "content_id"),
       ("attempt", "path_id", "learning_path", "path_id"), ("attempt", "recommendation_id", "recommendation", "recommendation_id"),
       ("assessment_result", "attempt_id", "attempt", "attempt_id"), ("assessment_result", "learner_id", "learner", "learner_id"),
       ("assessment_result", "skill_id", "skill", "skill_id"),
       ("recommendation", "learner_id", "learner", "learner_id"), ("recommendation", "path_id", "learning_path", "path_id"),
       ("recommendation", "content_id", "content_item", "content_id"), ("recommendation", "target_skill_id", "skill", "skill_id"),
       ("recommendation", "as_of_attempt_id", "attempt", "attempt_id"), ("recommendation", "outcome_attempt_id", "attempt", "attempt_id"),
       ("recommendation_event", "recommendation_id", "recommendation", "recommendation_id"),
       ("recommendation_event", "attempt_id", "attempt", "attempt_id")]
PATH_STATES = ["CREATED", "ACTIVE", "COMPLETED", "ABANDONED", "STALLED"]
ENUMS = {("learner", "country"): COUNTRIES, ("learner", "education_level"): EDU, ("learner", "preferred_format"): FORMATS,
         ("learner", "status"): ["ACTIVE", "DORMANT"], ("content_item", "format"): FORMATS,
         ("content_item", "status"): ["DRAFT", "PUBLISHED", "RETIRED"], ("learning_path", "status"): PATH_STATES,
         ("learning_path_event", "event_type"): ["CREATED", "ACTIVATED", "SKILL_MASTERED", "COMPLETED", "ABANDONED", "STEP_REVISITED", "STALLED"],
         ("learning_path_event", "to_status"): PATH_STATES, ("recommendation", "reason_code"): REASONS,
         ("recommendation", "status"): ["ACCEPTED", "EXPIRED", "PENDING"],
         ("recommendation_event", "event_type"): ["ISSUED", "ACCEPTED", "COMPLETED", "EXPIRED"],
         ("assessment_result", "proficiency_band"): ["NOVICE", "DEVELOPING", "PROFICIENT", "MASTERED"]}
COLS = {t: [c[0] for c in F[t]] for t in F}
KINDS = {t: {c[0]: c[3] for c in F[t]} for t in F}
GT_COLS = ["issue_id", "issue_type", "entity", "entity_id", "learner_id", "detection_rule", "description"]
A_ID, A_LRN, A_CNT, A_PATH, A_NO, A_ST, A_SUB, A_DUR, A_SCORE, A_MAX, A_PASS, A_REC = range(12)


def sid(i): return f"SKL-{i:06d}"
def crs(i): return f"CRS-{i:06d}"
def cnt(i): return f"CNT-{i:06d}"
def active(ci, t): return ci["pub"] <= t and t + 3600 < ci["ret"]
def rationale(code, skill, m, diff, desired):
    return (f"{code}: target skill {skill} mastery={'n/a' if m is None else m}; "
            f"difficulty {diff} vs desired {desired}; prerequisites met")


# --------------------------------------------------------------------------- master data
def gen_master(p, rng):
    nC, nS, nT = p["courses"], p["skills"], p["content"]
    course_of, by_course = {}, defaultdict(list)
    for i in range(1, nS + 1):
        c = (i - 1) * nC // nS + 1
        course_of[i] = c
        by_course[c].append(i)
    pre_i, depth, level, prereq = {}, {}, {}, {}
    course_rows = [[crs(c), f"{SUBJECTS[(c - 1) % len(SUBJECTS)]} Fundamentals {c}", SUBJECTS[(c - 1) % len(SUBJECTS)], "ACTIVE", 0]
                   for c in range(1, nC + 1)]
    skill_rows, pre_rows, skill_course = [], [], {}
    for i in range(1, nS + 1):
        c = course_of[i]
        prior = [j for j in by_course[c] if j < i]
        ps = set()
        if prior and rng.random() < 0.85:
            win = prior[-8:]
            ps.update(rng.sample(win, min(len(win), rng.choice([1, 1, 2, 2, 3]))))
        if i != by_course[c][0] and c > 1 and rng.random() < 0.10:
            ps.add(rng.randint(1, by_course[c][0] - 1))
        pre_i[i] = sorted(ps)
        depth[i] = 1 + max((depth[j] for j in ps), default=0)
        level[i] = min(5, 1 + (depth[i] - 1) // 2)
        pos = by_course[c].index(i) + 1
        skill_rows.append([sid(i), crs(c), f"{SUBJECTS[(c - 1) % len(SUBJECTS)]} Topic {pos}", level[i], "ACTIVE", 0])
        skill_course[sid(i)] = c
        prereq[sid(i)] = []
        for j in pre_i[i]:
            thr = rng.choice([0.5, 0.6, 0.6, 0.7])
            prereq[sid(i)].append((sid(j), thr))
            pre_rows.append([sid(i), sid(j), thr, 0, None])
    cont, ct_rows, cs_rows, ccont = {}, [], [], defaultdict(list)
    for k in range(1, nT + 1):
        prim = k if k <= nS else rng.randint(1, nS)          # first nS items cover every skill
        c = course_of[prim]
        diff = min(5, max(1, level[prim] + rng.choice([-1, 0, 0, 0, 1])))
        fmt = rng.choices(FORMATS, FORMAT_P)[0]
        dur = rng.randint(*DUR[fmt])
        pm = {"project": 70, "assessment": 65}.get(fmt, 60)
        r = rng.random()
        status = "DRAFT" if r < .05 else "RETIRED" if r < .10 else "PUBLISHED"
        pub = None if status == "DRAFT" else (0 if rng.random() < .7 else rng.randint(1, 150) * DAY)
        ret = rng.randint(400, 640) * DAY if status == "RETIRED" else None
        skills = [(sid(prim), 1.0)]
        if rng.random() < .35:
            cand = [j for j in by_course[c] if j != prim and j not in pre_i[prim] and prim not in pre_i[j]]
            if cand:
                skills.append((sid(rng.choice(cand)), 0.5))
        cont[cnt(k)] = dict(course=c, skills=skills, diff=diff, fmt=fmt, pm=pm, dur=dur,
                            pub=INF if pub is None else pub, ret=INF if ret is None else ret)
        ccont[c].append(cnt(k))
        ct_rows.append([cnt(k), crs(c), f"{SUBJECTS[(c - 1) % len(SUBJECTS)]} {fmt} {k}", fmt, diff, dur, pm, status, pub, ret])
        for idx, (s, w) in enumerate(skills):
            cs_rows.append([cnt(k), s, w, 1 if idx == 0 else 0])
    return dict(course=course_rows, skill=skill_rows, skill_prerequisite=pre_rows, content_item=ct_rows, content_skill=cs_rows,
                prereq=prereq, cont=cont, ccont=ccont, skill_course=skill_course,
                last_skill={c: sid(by_course[c][-1]) for c in by_course})


def recommend(t, pool, cont, prereq, mast, passed, pref, has_hist):
    best = None
    for c in pool:
        ci = cont[c]
        if c in passed or not active(ci, t):
            continue
        mg = margin_of(ci["skills"], prereq, mast.get)
        if mg is not None and mg < 0:
            continue
        ps = ci["skills"][0][0]
        m = mast.get(ps)
        if not has_hist:
            if mg is not None or ci["diff"] > 2:
                continue
            sc, code, desired = -ci["diff"], "COLD_START_DEFAULT", 1
        else:
            desired = desired_diff(m)
            sc = -abs(ci["diff"] - desired)
            if m is None:
                sc += 0.5; code = "NEW_SKILL_UNLOCK"
            elif m < 0.6:
                sc += 1.0; code = "GAP_REMEDIATION"
            elif m >= 0.8:
                sc -= 2.0; code = "ENRICHMENT"
            else:
                code = "DIFFICULTY_MATCH"
        if ci["fmt"] == pref:
            sc += 0.3
        if best is None or sc > best[0]:
            best = (sc, c, code, m, mg, desired)
    return best


def allocate(weights, total):
    A = len(weights)
    base = min(3, total // A)
    rem = total - base * A
    s = sum(weights)
    raw = [rem * w / s for w in weights]
    cntv = [base + int(x) for x in raw]
    left = total - sum(cntv)
    for i in sorted(range(A), key=lambda i: (-(raw[i] - int(raw[i])), i))[:left]:
        cntv[i] += 1
    return cntv


# --------------------------------------------------------------------------- main simulation
def build_data(p, seed, anomalies=True):
    rm, rl, rs, ri = (random.Random(seed * 10 + k) for k in (1, 2, 3, 4))
    mst = gen_master(p, rm)
    cont, prereq, ccont, skill_course = mst["cont"], mst["prereq"], mst["ccont"], mst["skill_course"]
    nL, nC, N = p["learners"], p["courses"], p["attempts"]
    cold = set(rl.sample(range(1, nL + 1), max(1, int(0.08 * nL))))
    L = {}
    for li in range(1, nL + 1):
        if li in cold:
            signup = CUTOFF - rl.randint(2, 10) * DAY - rl.randint(0, DAY - 1)
        else:
            signup = rl.randint(0, CUTOFF - 90 * DAY)
        L[li] = dict(signup=signup, pref=rl.choice(FORMATS), country=rl.choices(COUNTRIES, COUNTRY_P)[0],
                     edu=rl.choices(EDU, EDU_P)[0], ability=rl.gauss(0, 1), w=min(15.0, rl.lognormvariate(0, 0.8)))
    act = [li for li in range(1, nL + 1) if li not in cold]
    counts = dict(zip(act, allocate([L[li]["w"] for li in act], N)))

    EV, attempts, results, recs, paths, labels, lrange = {}, [], [], [], [], [], {}
    learner_rows = []
    path_n = rec_n = res_n = 0
    for li in range(1, nL + 1):
        lid = f"LRN-{li:06d}"
        d = L[li]
        k = 1 if li in cold else rs.choice([1, 2, 2, 3])
        courses = sorted(rs.sample(range(1, nC + 1), min(k, nC)))
        pst = {}
        for c in courses:
            path_n += 1
            pst[c] = dict(pid=f"PATH-2026-{path_n:06d}", lid=lid, course=c, created=d["signup"] + rs.randint(60, 3500),
                          first=None, last=None, mastered=set(), completed=False, events=[])
        pool = [x for c in courses for x in ccont[c]]
        mast, passed, nby = {}, set(), defaultdict(int)
        last = None
        last_aid = None
        start_idx = len(attempts)

        def draw(t):
            for _ in range(200):
                c = rs.choice(pool)
                if active(cont[c], t):
                    return c
            for c in pool:
                if cont[c]["pub"] <= t:
                    return c
            raise RuntimeError("no content available")

        def new_rec(t, best):
            nonlocal rec_n
            sc, c, code, m, mg, desired = best
            rec_n += 1
            ci = cont[c]
            ps = ci["skills"][0][0]
            r = dict(recommendation_id=f"REC-{rec_n:06d}", learner_id=lid, path_id=pst[ci["course"]]["pid"], content_id=c,
                     target_skill_id=ps, issued_at=t, reason_code=code, rationale=rationale(code, ps, m, ci["diff"], desired),
                     target_skill_mastery=m, prereq_margin=mg, difficulty_gap=ci["diff"] - desired, rank_score=round(sc, 3),
                     as_of_attempt_id=last_aid, model_version="rules-v1", status="PENDING", resolved_at=None,
                     outcome_attempt_id=None, outcome_score=None, outcome_passed=None)
            recs.append(r)
            return r

        if li in cold:
            t = d["signup"] + rs.randint(3600, DAY)
            best = recommend(t, pool, cont, prereq, mast, passed, d["pref"], False)
            if best:
                new_rec(t, best)
            n = 0
        else:
            n = counts[li]
        if n:
            lo = d["signup"] + 3600 + rs.randint(0, 2 * DAY)
            hi = CUTOFF - 3700
            ts = sorted(rs.randint(lo, hi) for _ in range(n))
            for i in range(1, n):
                ts[i] = max(ts[i], ts[i - 1] + 3700)
            if ts[-1] > hi:
                sh = ts[-1] - hi
                ts = [x - sh for x in ts]
        for i in range(n):
            t = ts[i]
            rec = None
            if i % REC_EVERY == 0:
                best = recommend(t, pool, cont, prereq, mast, passed, d["pref"], bool(mast))
                if best:
                    rec = new_rec(t - rs.randint(10, 90), best)
            follow = rec is not None and rs.random() < FOLLOW_P
            if follow:
                cid = rec["content_id"]
            elif last and not last[1] and rs.random() < RETRY_P and active(cont[last[0]], t):
                cid = last[0]
            elif rs.random() < GAP_P:
                cid = draw(t)
            else:
                cid = None
                for _ in range(8):
                    c = draw(t)
                    mg = margin_of(cont[c]["skills"], prereq, mast.get)
                    if mg is None or mg >= 0:
                        cid = c
                        break
                if cid is None:
                    cid = c
            ci = cont[cid]
            mg = margin_of(ci["skills"], prereq, mast.get)
            unmet = mg is not None and mg < 0
            nby[cid] += 1
            ps = ci["skills"][0][0]
            m0 = mast.get(ps)
            z = (d["ability"] + 3.0 * ((m0 if m0 is not None else 0.3) - 0.5) - 0.7 * (ci["diff"] - 3)
                 - (0.8 if unmet else 0.0) + (0.3 if nby[cid] > 1 else 0.0))
            score = round(min(100.0, max(0.0, 100.0 / (1.0 + math.exp(-z)) + rs.gauss(0, 9))), 1)
            dur = int(min(3600, max(60, ci["dur"] * 60 * rs.uniform(0.5, 1.2))))
            sub = t + dur
            ok = 1 if score >= ci["pm"] else 0
            aid = f"ATT-{lid}-{i + 1:06d}"
            pth = pst[ci["course"]]
            attempts.append([aid, lid, cid, pth["pid"], nby[cid], t, sub, dur, score, 100.0, ok, rec["recommendation_id"] if follow else None])
            if unmet:
                labels.append(aid)
            if ok:
                passed.add(cid)
            if pth["first"] is None:
                pth["first"] = t
            pth["last"] = sub
            for s, w in ci["skills"]:
                ev = EV.setdefault((lid, s), [])
                ev.append((sub, score / 100.0, w))
                old = mast.get(s)
                mast[s] = new = mastery_from(ev)
                pp = pst.get(skill_course[s])
                if pp is not None and new >= COMPLETE_M and s not in pp["mastered"]:
                    pp["mastered"].add(s)
                    if not pp["completed"]:      # no lifecycle events after a terminal state
                        pp["events"].append(dict(ts=sub, order=2, type="SKILL_MASTERED", frm="ACTIVE", to="ACTIVE", skill=s,
                                                 content=None, mast=new, attempt=aid))
                    if len(pp["mastered"]) >= COMPLETE_SKILLS and not pp["completed"]:
                        pp["completed"] = True
                        pp["events"].append(dict(ts=sub, order=3, type="COMPLETED", frm="ACTIVE", to="COMPLETED", skill=None,
                                                 content=None, mast=None, attempt=aid))
                if s == ps and ci["fmt"] == "assessment":
                    res_n += 1
                    results.append([f"RES-{res_n:06d}", aid, lid, s, score, old, new, M.band(new), sub])
            if rec is not None:
                if follow:
                    rec.update(status="ACCEPTED", resolved_at=sub, outcome_attempt_id=aid, outcome_score=score, outcome_passed=ok)
                elif rec["issued_at"] + EXPIRE_DAYS * DAY <= CUTOFF:
                    rec.update(status="EXPIRED", resolved_at=rec["issued_at"] + EXPIRE_DAYS * DAY)
            last = (cid, ok)
            last_aid = aid
        lrange[lid] = (start_idx, len(attempts))
        lastsub = attempts[-1][A_SUB] if len(attempts) > start_idx else None
        learner_rows.append([lid, d["signup"], d["country"], d["edu"], d["pref"], f"{M.iso(d['signup'])[:4]}-Q{(int(M.iso(d['signup'])[5:7]) - 1) // 3 + 1}",
                             "DORMANT" if lastsub is not None and lastsub + 60 * DAY < CUTOFF else "ACTIVE"])
        for c in courses:
            pp = pst[c]
            ev = [dict(ts=pp["created"], order=0, type="CREATED", frm=None, to="CREATED", skill=None, content=None, mast=None, attempt=None)]
            status = "CREATED"
            if pp["first"] is not None:
                ev.append(dict(ts=pp["first"], order=1, type="ACTIVATED", frm="CREATED", to="ACTIVE", skill=None, content=None, mast=None, attempt=None))
                status = "ACTIVE"
            ev += pp["events"]
            if pp["completed"]:
                status = "COMPLETED"
            else:
                la = pp["last"] if pp["last"] is not None else pp["created"]
                if la + ABANDON_DAYS * DAY <= CUTOFF:
                    ev.append(dict(ts=la + ABANDON_DAYS * DAY, order=4, type="ABANDONED", frm=status, to="ABANDONED", skill=None,
                                   content=None, mast=None, attempt=None))
                    status = "ABANDONED"
            paths.append(dict(pid=pp["pid"], lid=lid, course=c, target=mst["last_skill"][c], status=status, created=pp["created"],
                              events=ev))

    # ----------------------------------------------------------------------- labelled edge cases (after valid baseline)
    gt = []
    def add(typ, ent, eid, lid, rule, desc):
        gt.append([f"ISS-{len(gt) + 1:06d}", typ, ent, eid, lid, rule, desc])
    rec_by = {r["recommendation_id"]: r for r in recs}
    path_course = {x["pid"]: x["course"] for x in paths}
    orphan_rows = []
    if anomalies:
        used = set()
        # 1) recommendation violates prerequisite
        cands = sorted(r["recommendation_id"] for r in recs if r["status"] == "EXPIRED")
        for rid in ri.sample(cands, min(len(cands), max(5, int(0.002 * len(recs))))):
            r = rec_by[rid]
            l, t = r["learner_id"], r["issued_at"]
            getm = lambda pre: mastery_at(EV.get((l, pre), []), t)
            for _ in range(80):
                c = ri.choice(ccont[path_course[r["path_id"]]])
                ci = cont[c]
                if c == r["content_id"] or not active(ci, t):
                    continue
                mg = margin_of(ci["skills"], prereq, getm)
                if mg is not None and mg < 0:
                    ps = ci["skills"][0][0]
                    m = getm(ps)
                    r.update(content_id=c, target_skill_id=ps, target_skill_mastery=m, prereq_margin=mg,
                             difficulty_gap=ci["diff"] - desired_diff(m),
                             rationale=rationale(r["reason_code"], ps, m, ci["diff"], desired_diff(m)))
                    used.add(rid)
                    add("REC_PREREQ_VIOLATION", "recommendation", rid, l, "recomputed prereq_margin < 0 at issued_at",
                        f"recommended {c} while a prerequisite is below its threshold (margin {mg})")
                    break
        # 2) mastery uses a future attempt
        cands = sorted(r["recommendation_id"] for r in recs if r["recommendation_id"] not in used and r["as_of_attempt_id"])
        for rid in ri.sample(cands, min(len(cands), max(5, int(0.002 * len(recs))))):
            r = rec_by[rid]
            a0, a1 = lrange[r["learner_id"]]
            later = [i for i in range(a0, a1) if attempts[i][A_SUB] > r["issued_at"] + DAY]
            if not later:
                continue
            a = attempts[ri.choice(later)]
            r["as_of_attempt_id"] = a[A_ID]
            r["target_skill_mastery"] = mastery_at(EV.get((r["learner_id"], r["target_skill_id"]), []), a[A_SUB])
            used.add(rid)
            add("MASTERY_FUTURE_LEAK", "recommendation", rid, r["learner_id"], "as_of_attempt.submitted_at > issued_at",
                f"mastery computed with future attempt {a[A_ID]}")
        # 3) attempt timestamp order invalid
        cands = [i for i, a in enumerate(attempts) if a[A_REC] is None and cont[a[A_CNT]]["fmt"] != "assessment"
                 and a[A_ST] // DAY == a[A_SUB] // DAY]
        for i in sorted(ri.sample(cands, min(len(cands), max(5, int(0.001 * len(attempts)))))):
            a = attempts[i]
            a[A_ST], a[A_SUB] = a[A_SUB], a[A_ST]
            add("ATT_TIMESTAMP_ORDER", "attempt", a[A_ID], a[A_LRN], "submitted_at < started_at (and duration_sec != submitted-started)",
                "started_at and submitted_at swapped")
        # 4) content mapped to nonexistent skill (extra bridge rows; existing rows untouched)
        for n_, c in enumerate(sorted(ri.sample(sorted(cont), min(len(cont), max(5, int(0.005 * len(cont))))))):
            bad = f"SKL-{900001 + n_:06d}"
            orphan_rows.append([c, bad, 0.5, 0])
            add("CONTENT_SKILL_ORPHAN", "content_skill", f"{c}|{bad}", "", "content_skill.skill_id not in skill", f"{c} mapped to nonexistent {bad}")
        # 5) learner path loops without progress
        cands = sorted(x["pid"] for x in paths if x["status"] == "ACTIVE" and max(e["ts"] for e in x["events"]) + 9 * DAY <= CUTOFF)
        pbyid = {x["pid"]: x for x in paths}
        for pid in ri.sample(cands, min(len(cands), max(3, int(0.005 * len(paths))))):
            x = pbyid[pid]
            lt = max(e["ts"] for e in x["events"])
            a_, b_ = ri.sample(ccont[x["course"]], 2) if len(ccont[x["course"]]) > 1 else (ccont[x["course"]][0],) * 2
            skill = cont[a_]["skills"][0][0]
            m0 = mastery_at(EV.get((x["lid"], skill), []), lt)
            for j in range(ri.randint(6, 8)):
                x["events"].append(dict(ts=lt + (j + 1) * DAY, order=5, type="STEP_REVISITED", frm="ACTIVE", to="ACTIVE",
                                        skill=skill, content=(a_, b_)[j % 2], mast=m0, attempt=None))
            x["events"].append(dict(ts=lt + 9 * DAY, order=6, type="STALLED", frm="ACTIVE", to="STALLED", skill=None, content=None, mast=None, attempt=None))
            x["status"] = "STALLED"
            add("PATH_LOOP", "learning_path", pid, x["lid"], ">=5 consecutive STEP_REVISITED events, <=2 distinct contents, unchanged mastery_after",
                f"path alternates between {a_} and {b_} without mastery change")

    # ----------------------------------------------------------------------- flatten derived/event tables
    path_rows, evt_rows, evt_n = [], [], 0
    for x in paths:
        evs = sorted(x["events"], key=lambda e: (e["ts"], e["order"]))
        closed = None
        for seq, e in enumerate(evs, 1):
            evt_n += 1
            evt_rows.append([f"EVT-{evt_n:06d}", x["pid"], seq, e["type"], e["frm"], e["to"], e["ts"], e["skill"], e["content"], e["mast"], e["attempt"]])
            if e["type"] in ("COMPLETED", "ABANDONED"):
                closed = e["ts"]
        path_rows.append([x["pid"], x["lid"], crs(x["course"]), x["target"], x["status"], x["created"], closed])
    need = {r["outcome_attempt_id"] for r in recs if r["outcome_attempt_id"]}
    ast = {a[A_ID]: (a[A_ST], a[A_SUB]) for a in attempts if a[A_ID] in need}
    rec_rows, rce_rows, rce_n = [], [], 0
    for r in recs:
        rec_rows.append([r[c] for c in COLS["recommendation"]])
        seq = [("ISSUED", r["issued_at"], None)]
        if r["status"] == "ACCEPTED":
            st, sb = ast[r["outcome_attempt_id"]]
            seq += [("ACCEPTED", st, r["outcome_attempt_id"]), ("COMPLETED", sb, r["outcome_attempt_id"])]
        elif r["status"] == "EXPIRED":
            seq.append(("EXPIRED", r["resolved_at"], None))
        for typ, ts_, aid in seq:
            rce_n += 1
            rce_rows.append([f"RCE-{rce_n:06d}", r["recommendation_id"], typ, ts_, aid])
    tables = dict(learner=learner_rows, course=mst["course"], skill=mst["skill"], skill_prerequisite=mst["skill_prerequisite"],
                  content_item=mst["content_item"], content_skill=mst["content_skill"] + orphan_rows, learning_path=path_rows,
                  learning_path_event=evt_rows, attempt=attempts, assessment_result=results, recommendation=rec_rows,
                  recommendation_event=rce_rows)
    return tables, gt, labels


# --------------------------------------------------------------------------- export
def cook(name, row):
    out = []
    for c, v in zip(COLS[name], row):
        k = KINDS[name][c]
        if v is not None and k == "ts":
            v = M.iso(v)
        elif v is not None and k == "date":
            v = M.iso(v)[:10]
        out.append(v)
    return out


def sql_val(v):
    if v is None: return "NULL"
    if isinstance(v, str): return "'" + v.replace("'", "''") + "'"
    return repr(v)


def schema_sql():
    out = ["-- Generated by generate.py (SQLite/ANSI compatible). Injected anomaly rows intentionally violate some FKs;",
           "-- keep PRAGMA foreign_keys=OFF when loading the full seed, or generate with --no-anomalies.", ""]
    for t, fields in F.items():
        lines = [f"  {c} {typ}{' NOT NULL' if req == 'Y' else ''}" for c, typ, req, _, _ in fields]
        lines.append(f"  PRIMARY KEY ({', '.join(PKS[t])})")
        for ct, cc, pt, pc in FKS:
            if ct == t:
                lines.append(f"  FOREIGN KEY ({cc}) REFERENCES {pt}({pc})")
        out.append(f"CREATE TABLE {t} (\n" + ",\n".join(lines) + "\n);\n")
    return "\n".join(out)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def write_rows(path, name, rows, fmt, cols):
    with open(path, "w", newline="", encoding="utf-8") as f:
        if fmt == "csv":
            w = csv.writer(f, lineterminator="\n")
            w.writerow(cols)
            for r in rows:
                w.writerow(["" if v is None else v for v in r])
        elif fmt == "json":
            f.write("[\n")
            for i, r in enumerate(rows):
                f.write(("" if i == 0 else ",\n") + json.dumps(dict(zip(cols, r))))
            f.write("\n]\n")
        else:  # sql
            f.write("PRAGMA foreign_keys=OFF;\nBEGIN;\n")
            batch = []
            for r in rows:
                batch.append("(" + ",".join(sql_val(v) for v in r) + ")")
                if len(batch) == 500:
                    f.write(f"INSERT INTO {name} ({','.join(cols)}) VALUES\n" + ",\n".join(batch) + ";\n"); batch = []
            if batch:
                f.write(f"INSERT INTO {name} ({','.join(cols)}) VALUES\n" + ",\n".join(batch) + ";\n")
            f.write("COMMIT;\n")


def export(out, tables, gt, labels, formats, p, seed, scale, anomalies):
    os.makedirs(out, exist_ok=True)
    files, counts = {}, {}
    for name, rows in tables.items():
        counts[name] = len(rows)
        for fmt in formats:
            if fmt == "sql":
                continue
            path = os.path.join(out, f"{name}.{'csv' if fmt == 'csv' else 'json'}")
            write_rows(path, name, (cook(name, r) for r in rows), fmt, COLS[name])
            files[os.path.basename(path)] = sha(path)
    with open(os.path.join(out, "schema.sql"), "w") as f:
        f.write(schema_sql())
    files["schema.sql"] = sha(os.path.join(out, "schema.sql"))
    if "sql" in formats:
        path = os.path.join(out, "seed.sql")
        with open(path, "w", encoding="utf-8") as f:
            for name, rows in tables.items():
                tmp = os.path.join(out, "_t.sql")
                write_rows(tmp, name, (cook(name, r) for r in rows), "sql", COLS[name])
                f.write(open(tmp, encoding="utf-8").read())
                os.remove(tmp)
        files["seed.sql"] = sha(path)
    for fmt in formats:
        if fmt == "sql":
            continue
        for nm, cols, rows in (("ground_truth", GT_COLS, gt), ("ground_truth_labels", ["attempt_id", "label"], [[a, "ATTEMPT_PREREQ_GAP"] for a in labels])):
            path = os.path.join(out, f"{nm}.{'csv' if fmt == 'csv' else 'json'}")
            write_rows(path, nm, rows, fmt, cols)
            files[os.path.basename(path)] = sha(path)
    counts["ground_truth"] = len(gt)
    counts["ground_truth_labels"] = len(labels)
    manifest = dict(dataset="adaptive-learning-recommendation-synthetic", seed=seed, scale=scale, parameters=p,
                    anomalies_injected=anomalies, cutoff=M.iso(CUTOFF), temporal_split_date=SPLIT_DATE,
                    generator_command=" ".join(["python"] + sys.argv), python=sys.version.split()[0],
                    source_manifest=dict(external_data=[], provenance="Fully synthetic; no external or personal data used."),
                    row_counts=counts, sha256=files)
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def build(scale="starter", seed=SEED, out="data/starter", formats=("csv", "json", "sql"), anomalies=True, overrides=None):
    p = dict(SCALES[scale])
    p.update({k: v for k, v in (overrides or {}).items() if v is not None})
    tables, gt, labels = build_data(p, seed, anomalies)
    return export(out, tables, gt, labels, formats, p, seed, scale, anomalies)


def write_docs(path):
    rel = [f"- `{ct}.{cc}` -> `{pt}.{pc}`" for ct, cc, pt, pc in FKS]
    lines = ["# Data dictionary", "", "Generated from `generate.py` (`F`, `PKS`, `FKS`) so it never drifts from the code.",
             "Timestamps are UTC ISO-8601 (`YYYY-MM-DDTHH:MM:SSZ`), dates `YYYY-MM-DD`. Empty CSV cell / JSON null / SQL NULL = missing.", ""]
    for t, fields in F.items():
        lines += [f"## {t}", f"Primary key: `{', '.join(PKS[t])}`", "", "| field | type | required | rule / allowed values / units |", "|---|---|---|---|"]
        lines += [f"| {c} | {typ} | {req} | {d} |" for c, typ, req, _, d in fields]
        lines.append("")
    lines += ["## Foreign keys", *rel, "",
              "## Cardinality", "- course 1:N skill, content_item, learning_path", "- skill N:M skill via skill_prerequisite (DAG, optional, effective-dated)",
              "- content_item N:M skill via content_skill (exactly one primary)", "- learner 1:N learning_path (one per enrolled course); learning_path 1:N attempt, 1:N learning_path_event",
              "- learner 1:N attempt; content_item 1:N attempt; attempt 1:0..1 assessment_result (assessment-format content only)",
              "- recommendation 1:0..1 attempt (the attempt that followed it, `attempt.recommendation_id`); recommendation 1:N recommendation_event",
              "", "## Lifecycles (history is append-only in event tables)",
              "- learning_path: CREATED -> ACTIVE -> COMPLETED | ABANDONED | STALLED; CREATED -> ABANDONED",
              "- recommendation: ISSUED -> ACCEPTED -> COMPLETED, or ISSUED -> EXPIRED (14 days), or ISSUED (pending at cut-off)",
              "- content_item: DRAFT (never served) / PUBLISHED -> RETIRED (retired items are not served after `retired_at`)", ""]
    with open(path, "w") as f:
        f.write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scale", choices=SCALES, default="starter")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", default=None)
    ap.add_argument("--formats", default="csv,json,sql")
    ap.add_argument("--no-anomalies", action="store_true")
    ap.add_argument("--verify-repro", action="store_true", help="regenerate with the same seed and compare row counts + checksums")
    ap.add_argument("--write-docs", metavar="PATH")
    ap.add_argument("--no-dashboard", action="store_true", help="skip validation/evaluation/dashboard after generating")
    ap.add_argument("--no-open", action="store_true", help="build the dashboard but do not open the browser")
    for k in ("learners", "skills", "content", "attempts", "courses"):
        ap.add_argument("--" + k, type=int)
    a = ap.parse_args()
    if a.write_docs:
        write_docs(a.write_docs)
        return
    out = a.out or f"data/{a.scale}"
    ov = {k: getattr(a, k) for k in ("learners", "skills", "content", "attempts", "courses")}
    fm = tuple(x for x in a.formats.split(",") if x)
    m1 = build(a.scale, a.seed, out, fm, not a.no_anomalies, ov)
    print("row counts:", m1["row_counts"])
    same = True
    if a.verify_repro:
        tmp = out.rstrip("/") + "_repro_tmp"
        m2 = build(a.scale, a.seed, tmp, fm, not a.no_anomalies, ov)
        shutil.rmtree(tmp)
        same = m1["row_counts"] == m2["row_counts"] and m1["sha256"] == m2["sha256"]
        rep = dict(seed=a.seed, run1=dict(row_counts=m1["row_counts"], sha256=m1["sha256"]),
                   run2=dict(row_counts=m2["row_counts"], sha256=m2["sha256"]), identical=same)
        with open(os.path.join(out, "reproducibility.json"), "w") as f:
            json.dump(rep, f, indent=2)
        print("reproducible (row counts + sha256 identical):", same)
    if not a.no_dashboard:
        if "csv" not in fm:
            print("dashboard needs csv output; skipped")
        else:
            import validate, evaluate, dashboard, webbrowser
            s = validate.run(out, quiet=True)
            print("validation:", "PASS" if s["passed"] else "FAIL", "| injected issues found:",
                  {k: f"{v['true_pos']}/{v['labelled']}" for k, v in s["injected_issue_detection"].items()})
            e = evaluate.run(out, quiet=True)["clean"]
            print("temporal-split test:", {k: e[k] for k in ("acceptance_rate", "prerequisite_compliance", "reason_code_coverage", "pass_rate_accepted", "pass_rate_self_selected")})
            path = os.path.abspath(dashboard.make(out))
            print("dashboard:", path)
            if not a.no_open:
                webbrowser.open("file://" + path)
    if not same:
        sys.exit(1)

if __name__ == "__main__":
    main()
