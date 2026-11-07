# Visit link decision record — MIMIC-CXR

Date: 2026-11-07
Target: `image_occurrence.visit_occurrence_id`
Summary: [docs/visit_link.md](../docs/visit_link.md)

## 1. Decision

### 1.1 Visit classification

Visits are classified by **`visit_concept_id`**, not by the `visit_source_value` string.

| Class | visit_concept_id | Meaning | Rows (src_visit 2,922,008) |
|---|---|---|---|
| Clinic (point event) | 38004207 | `subject\|date`, mostly start = end | 2,383,175 |
| Stay (visits with a duration, 5 types) | 262, 581385, 8870, 8883, 9201 | `subject\|hadm` family | 54,929 / 228,444 / 199,432 / 42,898 / 13,130 |

- The earlier regular expression (`visit_source_value ~ '^[0-9]+\|[0-9]+$'`) classified **7,195** visits with `visit_concept_id` 38004207 as stays because their value looks numeric. Under the new rule they are clinics.
- Some clinic visits end after they start (duration 1 day: 5,974; 2 days: 761; 3 days: 206; 4 days: 54; and so on). Clinic matching therefore uses the range `[start_date, end_date]`, not date `=`.

### 1.2 Link order

Within the same `person_id`:

1. **Stay (rule = `stay_datetime`)**: a stay whose `[visit_start_datetime, visit_end_datetime]` contains the image time (StudyDate + StudyTime). If there are several, the one with the earliest start, then the lowest `visit_occurrence_id`.
2. **Clinic (rule = `clinic_date`)**: if step 1 finds none (this includes studies without StudyTime), a clinic visit whose `[visit_start_date, visit_end_date]` contains the image date. If there are several, the earliest start, then the lowest `visit_occurrence_id`.
3. **Neither**: `visit_occurrence_id = NULL`.

An image whose date matches but whose time lies outside the stay is **not** linked to that stay.

Rule names used in the comparisons:

| Name | Content |
|---|---|
| Date-only rule | Among visits whose `[start_date, end_date]` contains the image date, the one with the earliest start date, then the lowest id. The time is ignored. The former `LATERAL` in `lk_30` (start date → id, one row) is this rule |
| Earlier rule (datetime-aware) | `lk_30` before the change: date candidates → narrow by datetime if there are several → stay priority → earliest start |
| New rule | 1.2 above |

### 1.3 Where it is applied

| What | File | Status |
|---|---|---|
| Visit link | `sql/lk_30_img_mapped.sql` (`lk_img_visit_cand` → `lk_img_visit_link`) | changed to the new rule |
| StudyTime, visit datetimes | `sql/lk_10_img_clean.sql`, `sql/st_01_src_cdm_snapshot.sql`, `run_etl.py` | changed |
| QA output | `qa/validate.py` | adapted to the new columns (`rule`, `n_stay`, `n_clinic`) |

The rule needed these changes as well:
- `lk_10_img_clean.sql`: add `image_ts` from StudyTime (00080030) to `lk_img_file_clean` and `lk_img_occurrence_clean`.
- `st_01_src_cdm_snapshot.sql`: add `visit_start_datetime`, `visit_end_datetime`, `visit_source_value` and `visit_concept_id` to `src_visit`.
- `run_etl.py`: include tag 00080030 in the silver snapshot. Before, only StudyDate (00080020) and the tag_spec tags were read.
  **A `src_dicom_header` built earlier has no StudyTime, so `run_etl.py src` must be run again.** Otherwise `image_ts` is NULL everywhere, no stay is matched by datetime, and only clinic date matching remains.
- `lk_30_img_mapped.sql`: the date-only `LATERAL` is replaced by `lk_img_visit_cand` / `lk_img_visit_link`.
- `qa/validate.py`: prints the number of links per rule.

Columns of `lk_img_visit_link`: `modality_group, study_uid, series_uid, visit_occurrence_id, n_stay, n_clinic, rule`.

## 2. Evidence (earlier rule vs new rule)

Computed on the whole `src_dicom_header` (377,110 files) with read-only queries and temporary tables, taking the image time from the DICOM header the same way as `lk_10_img_clean.sql`. The "earlier rule" is a reproduction of the `lk_30` logic before the change (datetime-aware).
The internal labels of the earlier rule (`single` / `datetime` / `stay_priority` / `tie_break`) are approximations in the reproduction and are not used below; only whether an image is linked and to which visit is compared.

| Item | Count | Note |
|---|---|---|
| image_occurrence candidates (study, series) | 227,835 | |
| with a person | 215,006 | 12,829 have no person and are not linkable |
| without StudyTime | 0 | every linkable image has a time |
| Date-only rule: linked | 196,353 | 91.3 % of 215,006; 18,653 without candidate |
| **New rule: linked** | **195,574** | 91.0 % of 215,006 |
| ├ stay by datetime (`stay_datetime`) | 163,198 | |
| └ clinic by date (`clinic_date`) | 32,376 | |
| New rule: not linked | 19,432 | |
| **Earlier rule: linked** | **196,353** | 91.3 % of 215,006 (same count as the date-only rule) |

Comparison with the earlier rule:

| | Count | Description |
|---|---|---|
| Identical | 194,694 | 163,198 stay + 31,496 clinic |
| Different | 880 | all now linked to a clinic |
| Linked only before | 779 | not linked under the new rule |
| Linked only under the new rule | 0 | |
| Not linked under either | 18,653 | |

- The 880 different = stay → clinic **767** (8870: 466, 581385: 276, 262: 17, 9201: 7, 8883: 1) + clinic → another clinic **113**.
- Images that were linked to a stay by date only and no longer are: **1,546** in total (stay → clinic 767 + linked only before 779).

**Time state of these 1,546**
- Without StudyTime: **0**.
- Before the stay start: **1,397** (90.4 %); after its end: **149** (9.6 %).

| Stay type linked before | Before start | After end | Median before start (h) |
|---|---|---|---|
| 8870 | 891 | 108 | 1.6 |
| 581385 | 445 | 23 | 2.5 |
| 262 | 40 | 12 | 0.7 |
| 8883 | 13 | 4 | 0.8 |
| 9201 | 8 | 2 | 1.6 |

The largest distance is about 20 hours. These images are outside the visit interval; it is not that their time is missing.

Overlaps:
- Earlier rule: 8,233 images have two or more date candidates (4.2 % of 196,353).
- New rule: 155 images fall into two or more overlapping stays.

## 3. Interpretation and limits

- The link rate under the new rule is slightly lower than before (91.0 % vs 91.3 %). The difference is made of links that existed because the date matched although the time lies outside the stay; when a clinic exists on the same day, it replaces the stay.
- Most of these images are stamped a few hours **before** the stay starts, which may mean that the ED arrival or registration time was recorded after the image. Whether to link such images to the stay within a tolerance (for example N hours before the start) is **undecided**. The rule has no tolerance.
- The five stay types include ER (8870) and observation (581385). Whether the number in their `visit_source_value` is a `hadm_id` or a `stay_id` has not been checked.
- The figures above were computed from `src_dicom_header` in temporary tables, not from a real run of `lk_30` (`lk_img_visit_link`). Compare them with the `qa/validate.py` output after a full pipeline run.

## 4. Open items

1. Run the changed code: `run_etl.py src` must be run again (see 1.3). Only a syntax check (`py_compile`) and `tests/test_spec.py` have been done; the whole pipeline has not been run.
2. Run the full pipeline and compare with the figures in section 2.
3. Decide whether to add a tolerance before the stay start.
4. Check what the number in `visit_source_value` of the five stay types means (hadm_id or stay_id).
