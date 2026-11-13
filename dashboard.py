"""Builds a self-contained dashboard.html (data embedded) from a generated dataset folder.
Recommendations shown are recomputed at the data cut-off with the same rules-v1 logic as the generator."""
import csv, json, os, random
from collections import defaultdict
import generate as G, mastery as M


def make(d, n_active=22, n_cold=3):
    rd = lambda n: list(csv.DictReader(open(os.path.join(d, n + ".csv"), encoding="utf-8")))
    skills = {r["skill_id"]: r for r in rd("skill")}
    content = {r["content_id"]: r for r in rd("content_item")}
    cs = defaultdict(list)
    for r in rd("content_skill"):
        if r["skill_id"] in skills:
            cs[r["content_id"]].append((r["skill_id"], float(r["weight"])))
    prereq = defaultdict(list)
    for r in rd("skill_prerequisite"):
        prereq[r["skill_id"]].append((r["prerequisite_skill_id"], float(r["min_mastery"])))
    cont, ccont = {}, defaultdict(list)
    for c, r in content.items():
        cont[c] = dict(course=r["course_id"], skills=sorted(cs[c], key=lambda x: -x[1]), diff=int(r["difficulty"]), fmt=r["format"],
                       pm=int(r["pass_mark"]), pub=M.to_sec(r["published_at"]) if r["published_at"] else G.INF,
                       ret=M.to_sec(r["retired_at"]) if r["retired_at"] else G.INF)
        ccont[r["course_id"]].append(c)
    gt = rd("ground_truth")
    badl = {x["learner_id"] for x in gt if x["learner_id"]}
    paths, att = defaultdict(list), defaultdict(list)
    for r in rd("learning_path"):
        paths[r["learner_id"]].append(r["course_id"])
    for r in rd("attempt"):
        att[r["learner_id"]].append(r)
    learners = {r["learner_id"]: r for r in rd("learner")}
    rng = random.Random(1)
    act = [l for l in sorted(att) if 25 <= len(att[l]) <= 70 and l not in badl] or [l for l in sorted(att) if l not in badl]
    cold = [l for l in learners if l not in att and l not in badl]
    pick = rng.sample(act, min(n_active, len(act))) + cold[:n_cold]
    out = []
    for l in pick:
        rows = sorted(att[l], key=lambda r: r["submitted_at"])
        EV, passed = defaultdict(list), set()
        for r in rows:
            for s, w in cont[r["content_id"]]["skills"]:
                EV[s].append((M.to_sec(r["submitted_at"]), float(r["score"]) / 100, w))
            if r["passed"] == "1":
                passed.add(r["content_id"])
        mast = {s: M.mastery_from(e) for s, e in EV.items()}
        pl = [c for cr in paths[l] for c in ccont[cr]]
        recs = []
        for _ in range(3):
            b = G.recommend(G.CUTOFF, pl, cont, prereq, mast, passed, learners[l]["preferred_format"], bool(mast))
            if not b:
                break
            sc, c, code, m, mg, des = b
            pl.remove(c)
            ci = cont[c]
            recs.append(dict(id=c, title=content[c]["title"], fmt=ci["fmt"], diff=ci["diff"], desired=des, code=code,
                             skill=skills[ci["skills"][0][0]]["name"], m=m,
                             pre=[dict(n=skills[p]["name"], m=mast.get(p), t=t, ok=(mast.get(p) or 0) >= t)
                                  for s, _ in ci["skills"] for p, t in prereq.get(s, [])]))
        out.append(dict(id=l, tag="new learner (no history)" if not rows else f"{len(rows)} attempts",
                        mastery=sorted([dict(n=skills[s]["name"], m=m) for s, m in mast.items()], key=lambda x: x["m"]),
                        hist=[dict(t=content[r["content_id"]]["title"], s=float(r["score"]), p=r["passed"] == "1") for r in rows[-6:]][::-1],
                        recs=recs))
    ev = json.load(open(os.path.join(d, "evaluation.json")))["clean"]
    data = dict(learners=out, kpi=dict(acc=ev["acceptance_rate"], comp=ev["prerequisite_compliance"], cov=ev["reason_code_coverage"], n=ev["test_resolved"]))
    tpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_template.html"), encoding="utf-8").read()
    path = os.path.join(d, "dashboard.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(tpl.replace("__DATA__", json.dumps(data, separators=(",", ":"))))
    return path
