# Full-scale run (10,000 learners / 500 skills / 2,000 content / 500,000 attempts)

Command: `python generate.py --scale full --out data/full --formats csv --verify-repro` (seed 20261022; ~51 s for both runs combined on the build machine).

Validation: **PASS** (no unexplained findings). Reproducibility: two runs identical = True.

| issue_type | labelled | detected | FP | FN |
|---|---|---|---|---|
| REC_PREREQ_VIOLATION | 100 | 100 | 0 | 0 |
| ATT_TIMESTAMP_ORDER | 500 | 500 | 0 | 0 |
| CONTENT_SKILL_ORPHAN | 10 | 10 | 0 | 0 |
| MASTERY_FUTURE_LEAK | 102 | 102 | 0 | 0 |
| PATH_LOOP | 96 | 96 | 0 | 0 |

Row counts: learner=10000, course=40, skill=500, skill_prerequisite=727, content_item=2000, content_skill=2700, learning_path=19329, learning_path_event=97910, attempt=500000, assessment_result=57894, recommendation=52620, recommendation_event=137367, ground_truth=808, ground_truth_labels=110136

Temporal-split evaluation (clean variant): {"train_recommendations": 33778, "test_recommendations": 18640, "test_resolved": 17039, "acceptance_rate": 0.6776, "pass_rate_accepted": 0.4345, "pass_rate_self_selected": 0.6618, "pass_rate_lift": -0.2273, "prerequisite_compliance": 1.0, "reason_code_coverage": 1.0, "mean_abs_difficulty_gap": 0.4337, "brier_reason_code_model": 0.2193, "brier_global_rate_baseline": 0.219}

SHA-256 of generated CSVs (identical across both runs):

| file | sha256 |
|---|---|
| assessment_result.csv | `09bc5b9c796a908fcc0af90d4df33caef46ac6816b0b22047804ad995d03a6b8` |
| attempt.csv | `cfa03eef5b6e58c406f35907bff8709f497fcb23411de303f50f14fed9a330e1` |
| content_item.csv | `2b26b902df27f3cba7b8174ac2c8628f333cd45e925870da69bf47f471ae119a` |
| content_skill.csv | `f69a68956c998ed4da5b5b8e7e91cb189aa202e82c001d71bee925e3811be2d7` |
| course.csv | `9e6fd59cc3392a9e08dc2649cc6d545d0355a4f50ef0f051f2526f028f2e071d` |
| ground_truth.csv | `0e0bd8fd9c033efd82f70788b87df7edeadc19ef8f88b30c27f48560fa88cae2` |
| ground_truth_labels.csv | `1660ea710e4fcb0d090470adaeb9392de7b10a7802a4b556a0181f2dd8c58e8d` |
| learner.csv | `98cef2541c00c978b87ca5ab0d4e93ab41e201505361cbaacbbb057509aff7a1` |
| learning_path.csv | `530d0dda5556f656859005fee81d78091213f02fd173b1065e829a58e6e4cf2e` |
| learning_path_event.csv | `4d6ea6025c46be7db752c10fe0a966b8fc9063b2e8c9681538f295d351000837` |
| recommendation.csv | `59df61774d7d557e8091afcb97077b6a6733a2b7b5cc6c7eb1d7acfacbe826d3` |
| recommendation_event.csv | `2e31917061de2f382ccf8f46f187b809e82276d2fdb0ea32f31944101010c6dd` |
| schema.sql | `77736492f464e4a5dd0cdd0aff114b754cc9e1c84b6af14906871755aac53f50` |
| skill.csv | `63f8b35d354775f2799b6a811f9ff614326aafed3f1ed6b2cc5fa678bda8ccc9` |
| skill_prerequisite.csv | `8c61789dc19ff1b7531ba179751bd6e511bb3570ba20723116c29a216a6747b2` |
