-- Logic step 4 (mapped): clean data + mapped concepts + person / visit / procedure links + surrogate ids.
-- IDs are positional bands (mappings/modality_profile.csv): base + row_number over a deterministic order, so
-- re-running on the same inputs gives the same ids and bands never collide with the hashed int64 ids of
-- the OHDSI/MIMIC CDM.
-- Visit link, rules in this order (all on the same person):
--  (1) stay = any visit that is NOT a point event (visit_concept_id <> 38004207; the 5 types 262, 581385, 8870, 8883, 9201,
--      visit_source_value = subject_id|hadm_id ...). Link the image to the stay whose
--      [visit_start_datetime, visit_end_datetime] contains the image datetime (StudyDate + StudyTime).
--      Several stays contain it: earliest start, then lowest visit_occurrence_id.   rule = 'stay_datetime'
--  (2) no stay found (incl. image without StudyTime): link to a clinic record (visit_concept_id = 38004207,
--      visit_source_value = subject_id|date) whose [visit_start_date, visit_end_date] contains the StudyDate.
--      Several: earliest start, then lowest visit_occurrence_id.                    rule = 'clinic_date'
--  (3) neither: no visit (visit_occurrence_id stays NULL).
-- A stay that only matches by date but not by time is NOT used any more (it used to win over a clinic record).
-- lk_img_visit_link keeps, per image_occurrence, the chosen visit and the rule that decided it (QA prints the counts).
DROP TABLE IF EXISTS @etl.lk_img_visit_cand;
CREATE TABLE @etl.lk_img_visit_cand AS
SELECT c.modality_group, c.study_uid, c.series_uid, v.visit_occurrence_id, v.visit_start_datetime, 'stay_datetime' AS rule
FROM @etl.lk_img_occurrence_clean c
JOIN @etl.src_person p ON p.person_source_value = c.subject_id::text
JOIN @etl.src_visit v ON v.person_id = p.person_id AND v.visit_concept_id <> 38004207
 AND c.image_ts BETWEEN v.visit_start_datetime AND v.visit_end_datetime
UNION ALL
SELECT c.modality_group, c.study_uid, c.series_uid, v.visit_occurrence_id, v.visit_start_datetime, 'clinic_date'
FROM @etl.lk_img_occurrence_clean c
JOIN @etl.src_person p ON p.person_source_value = c.subject_id::text
JOIN @etl.src_visit v ON v.person_id = p.person_id AND v.visit_concept_id = 38004207
 AND c.image_date BETWEEN v.visit_start_date AND v.visit_end_date;

DROP TABLE IF EXISTS @etl.lk_img_visit_link;
CREATE TABLE @etl.lk_img_visit_link AS
WITH k AS (
    SELECT *, count(*) FILTER (WHERE rule = 'stay_datetime') OVER w AS n_stay,
              count(*) FILTER (WHERE rule = 'clinic_date')   OVER w AS n_clinic,
              ROW_NUMBER() OVER (w ORDER BY (rule = 'clinic_date'), visit_start_datetime, visit_occurrence_id) AS rn   -- stay before clinic
    FROM @etl.lk_img_visit_cand WINDOW w AS (PARTITION BY modality_group, study_uid, series_uid)
)
SELECT modality_group, study_uid, series_uid, visit_occurrence_id, n_stay, n_clinic, rule
FROM k WHERE rn = 1;
CREATE UNIQUE INDEX ux_lk_visit_link ON @etl.lk_img_visit_link (modality_group, study_uid, series_uid);

DROP TABLE IF EXISTS @etl.lk_img_occurrence_mapped;
CREATE TABLE @etl.lk_img_occurrence_mapped AS
WITH o AS (
    SELECT c.*, p.person_id, mp.io_id_base::bigint AS io_id_base,
           NULLIF(mp.anatomic_site_concept_id, '')::bigint AS anatomic_site_concept_id,
           mp.procedure_link_source_value, mc.target_concept_id AS modality_concept_id
    FROM @etl.lk_img_occurrence_clean c
    JOIN @etl.src_person p ON p.person_source_value = c.subject_id::text
    JOIN @etl.src_modality_profile mp ON mp.modality_group = c.modality_group
    JOIN @etl.lk_img_modality_concept mc ON mc.modality_group = c.modality_group AND mc.source_code = c.dicom_modality
    WHERE mc.target_concept_id IS NOT NULL
)
SELECT o.io_id_base + ROW_NUMBER() OVER (PARTITION BY o.modality_group ORDER BY o.subject_id, o.study_id, o.series_uid) AS image_occurrence_id,
       o.modality_group, o.person_id, o.subject_id, o.study_id,
       v.visit_occurrence_id, pr.procedure_occurrence_id, o.anatomic_site_concept_id,
       o.local_path,
       o.image_date AS image_occurrence_date, o.study_uid AS image_study_uid, o.series_uid AS image_series_uid,
       o.modality_concept_id, o.dicom_count
FROM o
-- visit chosen by the rules above (lk_img_visit_link)
LEFT JOIN @etl.lk_img_visit_link v ON v.modality_group = o.modality_group AND v.study_uid = o.study_uid AND v.series_uid = o.series_uid
-- same person, same day, procedure_source_value = profile rule (blank rule = no link)
LEFT JOIN LATERAL (SELECT procedure_occurrence_id FROM @etl.src_procedure p
                   WHERE o.procedure_link_source_value <> '' AND p.person_id = o.person_id
                     AND p.procedure_date = o.image_date AND p.procedure_source_value = o.procedure_link_source_value
                   ORDER BY p.procedure_occurrence_id LIMIT 1) pr ON TRUE;
CREATE UNIQUE INDEX ux_lk_io_mapped ON @etl.lk_img_occurrence_mapped (modality_group, image_study_uid, image_series_uid);

DROP TABLE IF EXISTS @etl.lk_img_feature_mapped;
CREATE TABLE @etl.lk_img_feature_mapped AS
WITH f AS (
    SELECT o.image_occurrence_id, o.person_id, o.visit_occurrence_id, o.image_occurrence_date, o.anatomic_site_concept_id AS occ_site,
           c.modality_group, c.instance_uid, c.block_ord, c.k_scope, c.row_seq, c.k, c.tag, c.target_table, c.value_field,
           c.attribute_concept_id, c.source_value, c.value_num,
           fc.image_date AS feature_date,  -- the instance's own StudyDate (differs from the occurrence date if a study's files disagree)
           -- unmapped / empty CS value -> 0 (No matching concept); the code itself stays in value_source_value
           CASE WHEN c.value_field = 'value_as_concept_id' THEN COALESCE(vc.target_concept_id, 0) END AS value_concept_id
    FROM @etl.lk_img_feature_clean c
    JOIN @etl.lk_img_file_clean fc ON fc.modality_group = c.modality_group AND fc.instance_uid = c.instance_uid
    JOIN @etl.lk_img_occurrence_mapped o ON o.modality_group = fc.modality_group
         AND o.image_study_uid = fc.study_uid AND o.image_series_uid = fc.series_uid
    LEFT JOIN @etl.lk_img_value_concept vc ON vc.modality_group = c.modality_group AND vc.tag = c.tag
         AND vc.source_value = c.source_value AND c.value_field = 'value_as_concept_id'
)
SELECT ROW_NUMBER() OVER w_all AS n, ROW_NUMBER() OVER w_tgt AS n_target, f.*
FROM f
WINDOW w_all AS (PARTITION BY modality_group ORDER BY image_occurrence_id, instance_uid, block_ord, COALESCE(k, 0), row_seq),
       w_tgt AS (PARTITION BY modality_group, target_table ORDER BY image_occurrence_id, instance_uid, block_ord, COALESCE(k, 0), row_seq);
CREATE INDEX ix_lk_feat_mapped ON @etl.lk_img_feature_mapped (modality_group, n);
