# Visit link (MIMIC-CXR)

Implemented in `sql/lk_30_img_mapped.sql` (the rule is also in the header of that file).

## Rule

1. A **stay** (any visit that is not a point event, i.e. `visit_concept_id` <> 38004207: 262, 581385, 8870, 8883, 9201) whose `[visit_start_datetime, visit_end_datetime]` contains StudyDate + StudyTime wins.
2. If there is none (or the study has no StudyTime): a **clinic** record (`visit_concept_id` = 38004207) whose date range contains StudyDate.
3. Otherwise no visit.

Ties: earliest start, then lowest id. A stay that matches by date only is not used. There is no tolerance before the visit start (an ED registration may be stamped after the image); this is an open decision.

## Result on the full CXR set

Computed from `src_dicom_header` with the same logic as `lk_30` (not yet from a full `lk_30` run).

| | occurrences |
|---|---|
| total | 215,006 |
| linked to a visit | 195,574 (163,198 stay, 32,376 clinic) |
| no visit | 19,432 |
| fall into two or more overlapping stays | 155 |

## Versus a date-only rule

A date-only rule links every occurrence for which at least one visit's date range contains the image date: 196,353 linked (91.3 %), 18,653 with no candidate. The new rule links 779 fewer, so 779 occurrences lose the link.

Versus the earlier datetime-aware rule (date candidates, then datetime, then stay priority; 196,353 linked): 194,694 occurrences are identical and 880 differ (all now clinic: 767 from a stay, 113 from another clinic). Together with the 779 that lose the link, 1,546 occurrences lose their stay. All have a StudyTime and lie outside the stay window: 1,397 before its start (median 0.7-2.5 h by type) and 149 after its end.

Decision record (with the detailed counts): `log/visit_link_decision_20261107.md`.
