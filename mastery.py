"""Shared deterministic helpers used by generator, validator and evaluator.

Mastery model (documented rule, reproducible from attempt records alone):
  * evidence for (learner, skill) = attempts whose content maps to the skill,
    ordered by submitted_at, as (submitted_at, score/100, content_skill.weight)
  * only evidence with submitted_at <= as_of is used (no future leakage)
  * mastery = weighted mean of the last WINDOW evidence items, each weighted by
    weight * 0.5 ** (age_days / HALF_LIFE_DAYS), age measured against the newest
    evidence item (so the value does not depend on when it is asked), rounded to 4 dp.
"""
from bisect import bisect_right
from datetime import datetime, timedelta

T0 = datetime(2025, 1, 1)
DAY = 86400
WINDOW = 5
HALF_LIFE_DAYS = 90.0


def iso(sec):
    return (T0 + timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_sec(s):
    if len(s) == 10:
        s += "T00:00:00Z"
    return int((datetime(int(s[0:4]), int(s[5:7]), int(s[8:10]), int(s[11:13]),
                         int(s[14:16]), int(s[17:19])) - T0).total_seconds())


def mastery_from(ev):
    ev = ev[-WINDOW:]
    if not ev:
        return None
    ref = ev[-1][0] // DAY
    num = den = 0.0
    for sec, score, w in ev:
        d = w * 0.5 ** ((ref - sec // DAY) / HALF_LIFE_DAYS)
        num += d * score
        den += d
    return round(num / den, 4)


def mastery_at(ev, as_of):
    """ev: chronological list of (submitted_sec, score01, weight)."""
    if not ev:
        return None
    k = bisect_right(ev, (as_of, 9.0, 9.0))
    return mastery_from(ev[max(0, k - WINDOW):k])


def margin_of(skills, prereq, getm):
    """Min over all direct prerequisites of (mastery - threshold); None if no prerequisites.
    Unknown mastery counts as 0.0. skills: [(skill_id, weight)], prereq: skill -> [(pre, thr)]."""
    mg = None
    for s, _ in skills:
        for pre, thr in prereq.get(s, ()):
            m = getm(pre)
            v = (0.0 if m is None else m) - thr
            if mg is None or v < mg:
                mg = v
    return None if mg is None else round(mg, 4)


def desired_diff(m):
    return 2 if m is None else 1 + int(round(m * 4))


def band(m):
    if m is None:
        return None
    return "NOVICE" if m < 0.4 else "DEVELOPING" if m < 0.6 else "PROFICIENT" if m < 0.8 else "MASTERED"
