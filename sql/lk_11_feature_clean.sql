-- Logic step 2 (clean): silver rows -> row template of mappings/tag_spec.csv.
--   k_scope instance      one value per file (shallowest sequence path)
--   k_scope channel       one value per ECG lead; lead index k from the item index in .../003A0200[k]/...
--   k_scope channel_repl  single DICOM value replicated to every lead (SamplingFrequency)
--   k_scope channel_const constant per lead (ChannelSensitivityUnitsSequence = millivolt)
-- Multi-valued attributes (vm > 1, e.g. PixelSpacing) -> one row per value, k = value order 1..n
--   silver holds them either as one text "[a, b]" (dicom_to_parquet under pydicom 3) or as one row per value
--   (path ends in [i]/); both are handled.  The whole text "[a, b]" stays in source_value.
-- Attributes present but empty are kept (CS -> value_as_concept_id 0), as in the published CSV.
DROP TABLE IF EXISTS @etl.lk_img_feature_clean;
CREATE TABLE @etl.lk_img_feature_clean AS
WITH base AS (
    SELECT g.modality_group, h.instance_uid, s.block, s.k_scope, s.row_seq::int AS row_seq, s.tag,
           s.target_table, s.value_field, s.attribute_concept_id::bigint AS attribute_concept_id,
           s.value_map, s.const_source_value, s.const_concept_id, h.path, NULLIF(h.value, '') AS value,
           (regexp_match(h.path, '003A0200\[([0-9]+)\]'))[1]::int + 1 AS k,
           -- value index when the tool already split a multi-valued tag into rows
           CASE WHEN h.vm ~ '^[0-9]+$' AND h.vm::int > 1 AND h.value !~ '^\[.*\]$'
                THEN (regexp_match(h.path, '\[([0-9]+)\]/$'))[1]::int + 1 END AS vidx
    FROM @etl.src_dicom_header h
    JOIN @etl.src_modality_profile g ON h.modality = ANY (string_to_array(g.dicom_modality_values, '|'))
    JOIN @etl.src_tag_spec s ON s.modality_group = g.modality_group AND s.tag = h.tag
),
inst AS (
    SELECT DISTINCT ON (modality_group, instance_uid, tag, COALESCE(vidx, 0)) *
    FROM base WHERE k_scope IN ('instance', 'channel_repl') AND k IS NULL
    ORDER BY modality_group, instance_uid, tag, COALESCE(vidx, 0), length(path), path
),
inst2 AS (
    SELECT inst.*, CASE WHEN vidx IS NOT NULL THEN '[' || string_agg(value, ', ') OVER (
                PARTITION BY modality_group, instance_uid, tag ORDER BY vidx
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) || ']' END AS multi_raw
    FROM inst
),
nch AS (
    SELECT modality_group, instance_uid, value::int AS nch
    FROM inst WHERE tag = '003A0005' AND value ~ '^[0-9]+$'
),
u AS (
    SELECT modality_group, instance_uid, block, k_scope, row_seq, tag, target_table, value_field, attribute_concept_id,
           value_map, const_source_value, const_concept_id, vidx AS k, value, multi_raw
    FROM inst2 WHERE k_scope = 'instance'
    UNION ALL
    SELECT i.modality_group, i.instance_uid, i.block, i.k_scope, i.row_seq, i.tag, i.target_table, i.value_field,
           i.attribute_concept_id, i.value_map, i.const_source_value, i.const_concept_id, g.k, i.value, NULL
    FROM inst2 i JOIN nch n USING (modality_group, instance_uid)
    CROSS JOIN LATERAL generate_series(1, n.nch) AS g(k)
    WHERE i.k_scope = 'channel_repl'
    UNION ALL
    SELECT modality_group, instance_uid, block, k_scope, row_seq, tag, target_table, value_field, attribute_concept_id,
           value_map, const_source_value, const_concept_id, k, value, NULL
    FROM base WHERE k_scope IN ('channel', 'channel_const') AND k IS NOT NULL
)
SELECT u.modality_group, u.instance_uid,
       CASE u.block WHEN 'pre' THEN 0 WHEN 'channel' THEN 1 ELSE 2 END AS block_ord,
       u.k_scope, u.row_seq,
       CASE WHEN e.is_text_multi THEN e.ord::int ELSE u.k END AS k,
       u.tag, u.target_table, u.value_field, u.attribute_concept_id, u.value_map, u.const_concept_id,
       COALESCE(u.multi_raw, CASE WHEN u.const_source_value <> '' THEN u.const_source_value ELSE u.value END) AS source_value,
       CASE WHEN u.value_field = 'value_as_number'
            THEN (substring(e.val from '^\s*(-?[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?)'))::numeric END AS value_num
FROM u
CROSS JOIN LATERAL (
    SELECT x.val, x.ord, (u.value_field = 'value_as_number' AND u.value ~ '^\[.*\]$') AS is_text_multi
    FROM unnest(CASE WHEN u.value_field = 'value_as_number' AND u.value ~ '^\[.*\]$'
                     THEN string_to_array(btrim(u.value, '[]'), ', ') ELSE ARRAY[u.value] END) WITH ORDINALITY AS x(val, ord)
) e;
CREATE INDEX ix_lk_feat_clean ON @etl.lk_img_feature_clean (modality_group, instance_uid);
