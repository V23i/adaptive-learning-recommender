# Adaptive Learning Recommender - Synthetic Data + Rule-Based Recommender

YottaFlex AI candidate project. Recommends next learning activities from **skills, prerequisites, assessment
results and content difficulty**, on a fully synthetic, reproducible dataset with labelled edge cases.
Individual work; stdlib-only Python 3.9+ (no installs, no network, no external data).

## Run it
`python generate.py` does everything: generates the starter data, validates it, evaluates on the temporal split and **opens `data/starter/dashboard.html`** (add `--no-open` to just build it, `--no-dashboard` to skip).
```bash
python generate.py --scale starter --out data/starter --verify-repro   # 500 learners / 10k attempts (seconds)
python generate.py --scale full --out data/full --formats csv --verify-repro   # 10,000 / 500 / 2,000 / 500,000
python validate.py data/starter          # integrity + reproducible mastery + ground-truth scoring
python evaluate.py data/starter          # temporal-split metrics
python -m unittest discover -s tests     # 7 end-to-end tests (tiny scale, ~1s)
```
Fixed seed `20261022` (`--seed` to change). Scale is parameterised: `--scale` presets plus `--learners --skills --content --attempts --courses`
overrides; starter and full use the same code path. `--formats csv,json,sql` (default all; use `csv` for full). `--no-anomalies` gives a clean baseline.
Full run needs ~2 GB RAM. `data/starter` is committed; `data/full` is git-ignored (regenerate; checksums in `docs/VALIDATION_FULL.md`).

## Outputs (per scale folder)
CSV/JSON per table, `schema.sql`, `seed.sql`, `manifest.json` (seed, params, generator command, source manifest, row counts, SHA-256),
`reproducibility.json` (two runs, identical counts + checksums), `ground_truth.csv/json`, `ground_truth_labels.csv`,
`validation_summary.md/json`, `evaluation.json`. Field-level data dictionary, cardinalities, lifecycles: `docs/DATA_DICTIONARY.md`
(generated from the code's schema, so it cannot drift).

## How it works
1. **Master data first** (`gen_master`): Course, Skill (DAG, levels from graph depth), SkillPrerequisite (effective-dated, per-edge `min_mastery`),
   ContentItem (6 formats, difficulty 1-5, DRAFT/PUBLISHED/RETIRED), ContentSkill bridge (1 primary + optional secondary skill).
2. **Transactions from valid parents** (`build_data`): learners (8% cold-start with no attempts), heavy-tailed activity, sessions with non-overlapping attempts,
   repeated attempts (retry after failure), multiple formats. Attempt scores come from a documented rule (latent ability + current mastery - difficulty - prerequisite-gap penalty + noise);
   latent ability is **never exported**.
3. **Mastery** (`mastery.py`, shared by generator/validator/evaluator): recency-weighted mean of the last 5 attempts per skill, using only attempts with `submitted_at <= as_of`.
4. **Recommender** (`recommend`, `rules-v1`): candidates must be published, unpassed, and have **every direct prerequisite of every mapped skill at/above its threshold**.
   Ranking = closeness to desired difficulty `1+round(4*mastery)` + remediation/new-skill bonus - mastered penalty + 0.3 format match. Each recommendation stores a **reason code**
   (`COLD_START_DEFAULT, NEW_SKILL_UNLOCK, GAP_REMEDIATION, DIFFICULTY_MATCH, ENRICHMENT`), rationale text, the mastery and prerequisite margin used, the last attempt used (`as_of_attempt_id`),
   and its **outcome** (the attempt that followed it, derived from the real attempt record, or EXPIRED after 14 days).
5. **History is append-only**: `learning_path_event` and `recommendation_event` record every state change; current status is a snapshot equal to the last event.
6. **Edge cases injected after the valid baseline**, labelled only in `ground_truth.csv` (inputs carry no label columns):
   `REC_PREREQ_VIOLATION`, `ATT_TIMESTAMP_ORDER`, `CONTENT_SKILL_ORPHAN` (extra bridge rows; existing rows untouched), `MASTERY_FUTURE_LEAK`, `PATH_LOOP`.
   `ground_truth_labels.csv` additionally lists natural prerequisite-gap attempts (learner attempted content with unmet prerequisites) as expected labels.

## Verification (what I ran)
- `validate.py`: PK uniqueness, FK integrity, enums/ranges, DAG acyclicity, date ordering, arithmetic (duration, pass flag, attempt_no, assessment mastery/band),
  **mastery recomputed from raw attempts and matched against stored values**, no future data in recommendations, prerequisites respected, reason codes present,
  lifecycle chains, duplicates, no ground-truth columns in inputs. Findings are then scored against ground truth: every injected issue must be found (recall 1.0) and nothing else may be flagged (precision 1.0).
  Starter result: PASS (see `data/starter/validation_summary.md`).
- Reproducibility: `--verify-repro` regenerates with the same seed and compares row counts and SHA-256 of every file (identical).
- `evaluate.py`: **temporal split** on `issued_at` (train < 2026-07-01 <= test). Metrics: acceptance rate, pass rate of accepted recs vs self-selected attempts, prerequisite compliance,
  reason-code coverage, difficulty gap, and a per-reason-code acceptance model fitted on train only (Brier vs global-rate baseline).

## Assumptions, deviations and known limitations
- Recommendation ID format `REC-000001` (also `RES-`, `EVT-`, `RCE-`, `ISS-`) is my extension; the five required formats are used exactly. `PATH-2026-` is the fixed prefix from the brief for all paths.
- Prerequisites are direct edges only (no transitive closure); thresholds are per edge. One recommendation (rank 1) per recommendation event, issued every 10th attempt and for cold-start learners.
- Learners follow a recommendation with fixed probability 0.65 and otherwise self-select (12% ignore prerequisites), so acceptance is simulated behaviour, not measured behaviour.
- Honest result: in the temporal test period accepted recommendations pass **less** often than self-selected attempts (see `evaluation.json`). The recommender deliberately targets new skills and remediation,
  which are harder than the average self-picked item, and the reason-code propensity model barely beats the global-rate baseline. I left this visible rather than tuning the simulator to flatter the policy.
- Mastery is a simple recency-weighted average, not IRT/BKT; no calendar effects, decay of unused skills, or instructor/support-staff actors are modelled.
- Not covered: hosted demo (not required). Environment: Python stdlib only; full run ~2 GB RAM.

## Repository layout
`generate.py` `dashboard.py` `dashboard_template.html` `mastery.py` `validate.py` `evaluate.py` `tests/` `docs/` `data/starter/` `prompts/` (prompt history) `.gitignore`
