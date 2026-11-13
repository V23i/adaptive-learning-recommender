# Data dictionary

Generated from `generate.py` (`F`, `PKS`, `FKS`) so it never drifts from the code.
Timestamps are UTC ISO-8601 (`YYYY-MM-DDTHH:MM:SSZ`), dates `YYYY-MM-DD`. Empty CSV cell / JSON null / SQL NULL = missing.

## learner
Primary key: `learner_id`

| field | type | required | rule / allowed values / units |
|---|---|---|---|
| learner_id | TEXT | Y | PK, LRN-######, immutable |
| signup_date | DATE | Y | UTC date within 2025-01-01..2026-10-22 |
| country | TEXT | Y | enum IN/US/GB/DE/BR/NG/ID/PH |
| education_level | TEXT | Y | enum HIGH_SCHOOL/UNDERGRAD/POSTGRAD/PROFESSIONAL |
| preferred_format | TEXT | Y | content format enum; +0.3 ranking bonus when it matches |
| cohort | TEXT | Y | YYYY-Qn derived from signup_date |
| status | TEXT | Y | ACTIVE|DORMANT; DORMANT = no attempt within 60 days before cut-off (derived) |

## course
Primary key: `course_id`

| field | type | required | rule / allowed values / units |
|---|---|---|---|
| course_id | TEXT | Y | PK, CRS-###### |
| title | TEXT | Y | free text |
| subject_area | TEXT | Y | one of generator subjects |
| status | TEXT | Y | ACTIVE |
| created_at | DATE | Y | UTC date |

## skill
Primary key: `skill_id`

| field | type | required | rule / allowed values / units |
|---|---|---|---|
| skill_id | TEXT | Y | PK, SKL-###### |
| course_id | TEXT | Y | FK course; home course (1:N) |
| name | TEXT | Y | free text |
| level | INTEGER | Y | 1..5, derived from prerequisite-graph depth |
| status | TEXT | Y | ACTIVE |
| created_at | DATE | Y | UTC date |

## skill_prerequisite
Primary key: `skill_id, prerequisite_skill_id`

| field | type | required | rule / allowed values / units |
|---|---|---|---|
| skill_id | TEXT | Y | FK skill (dependent skill) |
| prerequisite_skill_id | TEXT | Y | FK skill; numerically lower than skill_id (graph is a DAG); pair unique |
| min_mastery | REAL | Y | 0..1; one of 0.5/0.6/0.7; mastery needed to satisfy the edge |
| effective_from | DATE | Y | UTC date |
| effective_to | DATE | N | NULL = open-ended; > effective_from |

## content_item
Primary key: `content_id`

| field | type | required | rule / allowed values / units |
|---|---|---|---|
| content_id | TEXT | Y | PK, CNT-###### |
| course_id | TEXT | Y | FK course |
| title | TEXT | Y | free text |
| format | TEXT | Y | enum video/reading/quiz/exercise/project/assessment |
| difficulty | INTEGER | Y | 1..5 (ordinal) |
| duration_min | INTEGER | Y | minutes, 5..60 |
| pass_mark | INTEGER | Y | percent: 60 default, 65 assessment, 70 project |
| status | TEXT | Y | DRAFT|PUBLISHED|RETIRED |
| published_at | DATE | N | NULL iff DRAFT |
| retired_at | DATE | N | NOT NULL iff RETIRED; > published_at |

## content_skill
Primary key: `content_id, skill_id`

| field | type | required | rule / allowed values / units |
|---|---|---|---|
| content_id | TEXT | Y | FK content_item |
| skill_id | TEXT | Y | FK skill |
| weight | REAL | Y | 1.0 primary, 0.5 secondary; evidence weight in mastery |
| is_primary | INTEGER | Y | 0/1; exactly one primary per content |

## learning_path
Primary key: `path_id`

| field | type | required | rule / allowed values / units |
|---|---|---|---|
| path_id | TEXT | Y | PK, PATH-2026-###### |
| learner_id | TEXT | Y | FK learner |
| course_id | TEXT | Y | FK course; (learner_id, course_id) unique |
| target_skill_id | TEXT | Y | FK skill; last skill of the course (informational goal) |
| status | TEXT | Y | CREATED|ACTIVE|COMPLETED|ABANDONED|STALLED; equals to_status of last event |
| created_at | TIMESTAMP | Y | UTC |
| closed_at | TIMESTAMP | N | set for COMPLETED/ABANDONED |

## learning_path_event
Primary key: `event_id`

| field | type | required | rule / allowed values / units |
|---|---|---|---|
| event_id | TEXT | Y | PK, EVT-###### |
| path_id | TEXT | Y | FK learning_path |
| event_seq | INTEGER | Y | 1..n contiguous per path |
| event_type | TEXT | Y | CREATED|ACTIVATED|SKILL_MASTERED|COMPLETED|ABANDONED|STEP_REVISITED|STALLED |
| from_status | TEXT | N | NULL only for CREATED |
| to_status | TEXT | Y | path status enum |
| event_ts | TIMESTAMP | Y | UTC, non-decreasing per path |
| skill_id | TEXT | N | FK skill |
| content_id | TEXT | N | FK content_item |
| mastery_after | REAL | N | 0..1 |
| attempt_id | TEXT | N | FK attempt |

## attempt
Primary key: `attempt_id`

| field | type | required | rule / allowed values / units |
|---|---|---|---|
| attempt_id | TEXT | Y | PK, ATT-<learner-id>-######, sequential per learner in time order |
| learner_id | TEXT | Y | FK learner |
| content_id | TEXT | Y | FK content_item |
| path_id | TEXT | Y | FK learning_path (learner x content's course) |
| attempt_no | INTEGER | Y | 1.. per (learner, content); >1 = repeated attempt |
| started_at | TIMESTAMP | Y | UTC; within content active window |
| submitted_at | TIMESTAMP | Y | UTC; >= started_at |
| duration_sec | INTEGER | Y | = submitted_at - started_at, 60..3600 |
| score | REAL | Y | 0..100, 1 dp |
| max_score | REAL | Y | 100 |
| passed | INTEGER | Y | 0/1 = score >= content.pass_mark |
| recommendation_id | TEXT | N | FK recommendation when the attempt followed a recommendation |

## assessment_result
Primary key: `result_id`

| field | type | required | rule / allowed values / units |
|---|---|---|---|
| result_id | TEXT | Y | PK, RES-######; one per attempt on assessment-format content |
| attempt_id | TEXT | Y | FK attempt (1:1) |
| learner_id | TEXT | Y | FK learner |
| skill_id | TEXT | Y | FK skill; primary skill of the content |
| score_pct | REAL | Y | = attempt.score |
| mastery_before | REAL | N | mastery of skill before the attempt (NULL = no evidence) |
| mastery_after | REAL | Y | mastery after the attempt (mastery.py) |
| proficiency_band | TEXT | Y | NOVICE<0.4<=DEVELOPING<0.6<=PROFICIENT<0.8<=MASTERED, from mastery_after |
| recorded_at | TIMESTAMP | Y | = attempt.submitted_at |

## recommendation
Primary key: `recommendation_id`

| field | type | required | rule / allowed values / units |
|---|---|---|---|
| recommendation_id | TEXT | Y | PK, REC-###### |
| learner_id | TEXT | Y | FK learner |
| path_id | TEXT | Y | FK learning_path |
| content_id | TEXT | Y | FK content_item (recommended item) |
| target_skill_id | TEXT | Y | FK skill (primary skill of the content) |
| issued_at | TIMESTAMP | Y | UTC |
| reason_code | TEXT | Y | enum COLD_START_DEFAULT/NEW_SKILL_UNLOCK/GAP_REMEDIATION/DIFFICULTY_MATCH/ENRICHMENT |
| rationale | TEXT | Y | human-readable explanation |
| target_skill_mastery | REAL | N | mastery of target skill using attempts with submitted_at <= issued_at |
| prereq_margin | REAL | N | min over direct prerequisites of (mastery - min_mastery); NULL = no prerequisites; must be >= 0 |
| difficulty_gap | INTEGER | Y | content difficulty - desired difficulty (1+round(4*mastery); 2 if unseen) |
| rank_score | REAL | Y | rule score used for ranking |
| as_of_attempt_id | TEXT | N | FK attempt; newest attempt used; submitted_at must be <= issued_at |
| model_version | TEXT | Y | rules-v1 |
| status | TEXT | Y | ACCEPTED|EXPIRED|PENDING (final snapshot; history in recommendation_event) |
| resolved_at | TIMESTAMP | N | NULL while PENDING |
| outcome_attempt_id | TEXT | N | FK attempt; set when ACCEPTED |
| outcome_score | REAL | N | = outcome attempt score |
| outcome_passed | INTEGER | N | = outcome attempt passed |

## recommendation_event
Primary key: `event_id`

| field | type | required | rule / allowed values / units |
|---|---|---|---|
| event_id | TEXT | Y | PK, RCE-###### |
| recommendation_id | TEXT | Y | FK recommendation |
| event_type | TEXT | Y | ISSUED|ACCEPTED|COMPLETED|EXPIRED |
| event_ts | TIMESTAMP | Y | UTC |
| attempt_id | TEXT | N | FK attempt for ACCEPTED/COMPLETED |

## Foreign keys
- `skill.course_id` -> `course.course_id`
- `skill_prerequisite.skill_id` -> `skill.skill_id`
- `skill_prerequisite.prerequisite_skill_id` -> `skill.skill_id`
- `content_item.course_id` -> `course.course_id`
- `content_skill.content_id` -> `content_item.content_id`
- `content_skill.skill_id` -> `skill.skill_id`
- `learning_path.learner_id` -> `learner.learner_id`
- `learning_path.course_id` -> `course.course_id`
- `learning_path.target_skill_id` -> `skill.skill_id`
- `learning_path_event.path_id` -> `learning_path.path_id`
- `learning_path_event.skill_id` -> `skill.skill_id`
- `learning_path_event.content_id` -> `content_item.content_id`
- `learning_path_event.attempt_id` -> `attempt.attempt_id`
- `attempt.learner_id` -> `learner.learner_id`
- `attempt.content_id` -> `content_item.content_id`
- `attempt.path_id` -> `learning_path.path_id`
- `attempt.recommendation_id` -> `recommendation.recommendation_id`
- `assessment_result.attempt_id` -> `attempt.attempt_id`
- `assessment_result.learner_id` -> `learner.learner_id`
- `assessment_result.skill_id` -> `skill.skill_id`
- `recommendation.learner_id` -> `learner.learner_id`
- `recommendation.path_id` -> `learning_path.path_id`
- `recommendation.content_id` -> `content_item.content_id`
- `recommendation.target_skill_id` -> `skill.skill_id`
- `recommendation.as_of_attempt_id` -> `attempt.attempt_id`
- `recommendation.outcome_attempt_id` -> `attempt.attempt_id`
- `recommendation_event.recommendation_id` -> `recommendation.recommendation_id`
- `recommendation_event.attempt_id` -> `attempt.attempt_id`

## Cardinality
- course 1:N skill, content_item, learning_path
- skill N:M skill via skill_prerequisite (DAG, optional, effective-dated)
- content_item N:M skill via content_skill (exactly one primary)
- learner 1:N learning_path (one per enrolled course); learning_path 1:N attempt, 1:N learning_path_event
- learner 1:N attempt; content_item 1:N attempt; attempt 1:0..1 assessment_result (assessment-format content only)
- recommendation 1:0..1 attempt (the attempt that followed it, `attempt.recommendation_id`); recommendation 1:N recommendation_event

## Lifecycles (history is append-only in event tables)
- learning_path: CREATED -> ACTIVE -> COMPLETED | ABANDONED | STALLED; CREATED -> ABANDONED
- recommendation: ISSUED -> ACCEPTED -> COMPLETED, or ISSUED -> EXPIRED (14 days), or ISSUED (pending at cut-off)
- content_item: DRAFT (never served) / PUBLISHED -> RETIRED (retired items are not served after `retired_at`)
