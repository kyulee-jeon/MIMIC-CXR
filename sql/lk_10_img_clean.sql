-- Logic step 2 (clean): instance / series level.  Drops files without UIDs or a parsable StudyDate.
-- Instance level.  One StudyDate row (tag 00080020) exists per DICOM file in the silver layer, so it is the file list.
-- modality_group (ECG | CXR) comes from the DICOM Modality via mappings/modality_profile.csv (dicom_modality_values).
-- subject_id / study_id are parsed from the MIMIC folder layout  .../p<subject>/s<study>/ .
DROP TABLE IF EXISTS @etl.lk_img_file_clean;
CREATE TABLE @etl.lk_img_file_clean AS
SELECT DISTINCT ON (g.modality_group, h.instance_uid)
       g.modality_group,
       -- bronze location of the SERIES = the DICOM source folder given at run time + the series folder below it (p<NN>/p<subject>/s<study>)
       '@dicom_dir/' || (regexp_match(h.file_path, '(p[0-9]+/p[0-9]+/s[0-9]+)/[^/]+$'))[1] AS local_path,
       h.instance_uid, h.study_uid, h.series_uid,
       (regexp_match(h.file_path, '/p([0-9]+)/s([0-9]+)/'))[1]::bigint AS subject_id,
       (regexp_match(h.file_path, '/p([0-9]+)/s([0-9]+)/'))[2]::bigint AS study_id,
       to_date(h.value, 'YYYYMMDD') AS image_date, h.modality AS dicom_modality,
       -- image datetime = StudyDate + StudyTime (HHMMSS[.ffffff]); NULL when the file has no valid StudyTime
       CASE WHEN tm.value ~ '^([01][0-9]|2[0-3])[0-5][0-9][0-5][0-9]'
            THEN to_date(h.value, 'YYYYMMDD') + make_interval(hours => substr(tm.value, 1, 2)::int, mins => substr(tm.value, 3, 2)::int,
                                                              secs => substr(tm.value, 5, 2)::int) END AS image_ts
FROM @etl.src_dicom_header h
LEFT JOIN (SELECT instance_uid, min(value) AS value FROM @etl.src_dicom_header WHERE tag = '00080030' GROUP BY instance_uid) tm
       ON tm.instance_uid = h.instance_uid
JOIN @etl.src_modality_profile g ON h.modality = ANY (string_to_array(g.dicom_modality_values, '|'))
WHERE h.tag = '00080020' AND h.instance_uid <> '' AND h.study_uid <> '' AND h.series_uid <> ''
  AND h.value ~ '^[0-9]{8}$' AND h.file_path ~ 'p[0-9]+/p[0-9]+/s[0-9]+/[^/]+$'
ORDER BY g.modality_group, h.instance_uid, h.file_path;

-- one image_occurrence candidate per (study, series).  ECG: study = series = instance.
-- CXR: all images of a study share one series -> one occurrence; local_path = the series folder (same for every file of it).
DROP TABLE IF EXISTS @etl.lk_img_occurrence_clean;
CREATE TABLE @etl.lk_img_occurrence_clean AS
SELECT modality_group, study_uid, series_uid,
       min(local_path) AS local_path, min(subject_id) AS subject_id, min(study_id) AS study_id,
       min(image_date) AS image_date, min(image_ts) AS image_ts, min(dicom_modality) AS dicom_modality, count(*) AS dicom_count
FROM @etl.lk_img_file_clean
GROUP BY modality_group, study_uid, series_uid;
