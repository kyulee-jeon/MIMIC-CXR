-- Logic step 1 (snapshot): freeze the parts of the finished MIMIC-IV OMOP CDM that the imaging ETL links to.
DROP TABLE IF EXISTS @etl.src_person;
CREATE TABLE @etl.src_person AS
SELECT person_id::bigint AS person_id, person_source_value::text AS person_source_value
FROM @cdm.person;
CREATE INDEX ix_src_person_src ON @etl.src_person (person_source_value);

DROP TABLE IF EXISTS @etl.src_visit;
CREATE TABLE @etl.src_visit AS
SELECT visit_occurrence_id::bigint AS visit_occurrence_id, person_id::bigint AS person_id,
       visit_start_date::date AS visit_start_date, visit_end_date::date AS visit_end_date,
       visit_start_datetime::timestamp AS visit_start_datetime, visit_end_datetime::timestamp AS visit_end_datetime,
       visit_source_value::text AS visit_source_value, visit_concept_id::bigint AS visit_concept_id
FROM @cdm.visit_occurrence;
CREATE INDEX ix_src_visit_person ON @etl.src_visit (person_id, visit_start_date);

-- only the procedures that can be linked to an image (rule = mappings/modality_profile.csv)
DROP TABLE IF EXISTS @etl.src_procedure;
CREATE TABLE @etl.src_procedure AS
SELECT procedure_occurrence_id::bigint AS procedure_occurrence_id, person_id::bigint AS person_id,
       procedure_date::date AS procedure_date, procedure_source_value::text AS procedure_source_value
FROM @cdm.procedure_occurrence
WHERE procedure_source_value IN (SELECT procedure_link_source_value FROM @etl.src_modality_profile
                                 WHERE procedure_link_source_value <> '');
CREATE INDEX ix_src_proc_person ON @etl.src_procedure (person_id, procedure_date);
