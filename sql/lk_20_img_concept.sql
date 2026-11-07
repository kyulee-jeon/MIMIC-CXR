-- Logic step 3 (concept): distinct source codes -> concepts.  Custom mappings = custom_mapping_csv/*.csv
-- (loaded as src_custom_map; OHDSI/MIMIC format: source concept + 'Maps to' relationship, valid rows only; a file is the raw -> standard
-- table only. Which attribute (tag) a file belongs to is tag_spec.csv: value_map + attribute_concept_id, cf. DICOM2OMOP 'Maps to value').  Anything with target_concept_id IS NULL, or whose concept is not in the
-- vocabulary, is listed in lk_img_unmapped -> that is the review list for mapping decisions.
DROP TABLE IF EXISTS @etl.lk_img_modality_concept;
CREATE TABLE @etl.lk_img_modality_concept AS
SELECT o.modality_group, o.dicom_modality AS source_code, o.n_series,
       m.target_concept_id::bigint AS target_concept_id, c.concept_id IS NOT NULL AS in_vocab
FROM (SELECT modality_group, dicom_modality, count(*) AS n_series
      FROM @etl.lk_img_occurrence_clean GROUP BY 1, 2) o
LEFT JOIN @etl.src_custom_map m ON m.map_name = 'modality' AND m.concept_code = o.dicom_modality AND m.relationship_id = 'Maps to' AND m.invalid_reason_cr = ''
LEFT JOIN @voc.concept c ON c.concept_id = m.target_concept_id::bigint;

DROP TABLE IF EXISTS @etl.lk_img_value_concept;
CREATE TABLE @etl.lk_img_value_concept AS
SELECT v.modality_group, v.tag, v.value_map, v.source_value, v.n_rows,
       COALESCE(m.target_concept_id::bigint, NULLIF(v.const_concept_id, '')::bigint) AS target_concept_id,
       c.concept_id IS NOT NULL AS in_vocab
FROM (SELECT modality_group, tag, value_map, source_value, const_concept_id, count(*) AS n_rows
      FROM @etl.lk_img_feature_clean WHERE value_field = 'value_as_concept_id'
      GROUP BY 1, 2, 3, 4, 5) v
LEFT JOIN @etl.src_custom_map m ON m.map_name = v.value_map AND m.concept_code = v.source_value AND m.relationship_id = 'Maps to' AND m.invalid_reason_cr = ''
LEFT JOIN @voc.concept c ON c.concept_id = COALESCE(m.target_concept_id::bigint, NULLIF(v.const_concept_id, '')::bigint);

DROP TABLE IF EXISTS @etl.lk_img_unmapped;
CREATE TABLE @etl.lk_img_unmapped AS
SELECT 'modality'::text AS kind, modality_group, NULL::text AS tag, source_code, n_series AS n_rows, target_concept_id, in_vocab
FROM @etl.lk_img_modality_concept WHERE target_concept_id IS NULL OR NOT in_vocab
UNION ALL
SELECT 'value', modality_group, tag, source_value, n_rows, target_concept_id, in_vocab
FROM @etl.lk_img_value_concept
WHERE value_map <> '' AND (target_concept_id IS NULL OR NOT in_vocab);  -- value_map = '' : concept 0 by design (no mapping wanted)
