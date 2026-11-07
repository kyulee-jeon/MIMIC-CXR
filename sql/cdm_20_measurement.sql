-- target_domain: rows whose spec says target_table = measurement
TRUNCATE @etl.cdm_measurement;
INSERT INTO @etl.cdm_measurement
SELECT mp.measurement_id_base::bigint + f.n_target, f.person_id, f.attribute_concept_id, f.feature_date,
       NULL, NULL, mp.measurement_type_concept_id::bigint, NULL,
       CASE WHEN f.value_field = 'value_as_number' THEN f.value_num END,
       CASE WHEN f.value_field = 'value_as_concept_id' THEN f.value_concept_id END,
       NULL, NULL, NULL, NULL, f.visit_occurrence_id, NULL,
       f.tag, NULLIF(mp.measurement_source_concept_id, '')::bigint, NULL, left(f.source_value, 50)
FROM @etl.lk_img_feature_mapped f
JOIN @etl.src_modality_profile mp ON mp.modality_group = f.modality_group
WHERE f.target_table = 'measurement';
