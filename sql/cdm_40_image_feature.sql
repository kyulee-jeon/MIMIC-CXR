-- image_feature links every measurement row back to its image_occurrence.
--   image_feature_event_field_concept_id: OMOP CDM Table concept of the table image_feature_event_id points to
--   (1147330 = measurement)
TRUNCATE @etl.cdm_image_feature;
INSERT INTO @etl.cdm_image_feature
SELECT mp.feature_id_base::bigint + f.n, f.person_id, f.image_occurrence_id,
       1147330, mp.measurement_id_base::bigint + f.n_target,
       f.attribute_concept_id, f.k, mp.measurement_type_concept_id::bigint,
       NULL, NULL,
       CASE WHEN mp.feature_inherits_anatomic_site = 'Y' THEN f.occ_site END,
       NULL, NULL,
       CASE WHEN mp.feature_has_instance_uid = 'Y' THEN f.instance_uid END
FROM @etl.lk_img_feature_mapped f
JOIN @etl.src_modality_profile mp ON mp.modality_group = f.modality_group;
