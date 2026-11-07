-- Logic step 5 (load): target tables.
TRUNCATE @etl.cdm_image_occurrence;
INSERT INTO @etl.cdm_image_occurrence
SELECT image_occurrence_id, person_id, procedure_occurrence_id, visit_occurrence_id, anatomic_site_concept_id,
       NULL::varchar AS wadors_uri, local_path, image_occurrence_date, image_study_uid, image_series_uid, modality_concept_id
FROM @etl.lk_img_occurrence_mapped;
