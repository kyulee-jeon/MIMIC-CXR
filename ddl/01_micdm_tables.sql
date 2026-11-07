-- Target tables of the Medical Imaging CDM extension (OHDSI ImageWG conventions) plus the
-- measurement rows that carry the DICOM attribute values.
-- Created in the ETL schema with the prefix "cdm_" (OHDSI/MIMIC convention); the unload step copies
-- or exports them.  Column order == the published Extension/*.csv files.
-- Notes
--   * measurement follows the CDM v5.4 column set (value_source_value, *_event_id): the
--     published Extension CSVs were produced with those columns.
--   * image_feature_value_order is not in the ImageWG wiki DDL nor in "CREATE TABLE image_feature.txt",
--     but it is in the published image_feature.csv (ordered multi-value features, e.g. ECG lead 1..12).

CREATE TABLE IF NOT EXISTS @etl.cdm_image_occurrence (
    image_occurrence_id       bigint NOT NULL,
    person_id                 bigint NOT NULL,
    procedure_occurrence_id   bigint,
    visit_occurrence_id       bigint,
    anatomic_site_concept_id  bigint,
    wadors_uri                varchar(10000),
    local_path                varchar(10000),
    image_occurrence_date     date   NOT NULL,
    image_study_uid           varchar(10000) NOT NULL,
    image_series_uid          varchar(10000) NOT NULL,
    modality_concept_id       bigint NOT NULL
);

CREATE TABLE IF NOT EXISTS @etl.cdm_image_feature (
    image_feature_id                      bigint NOT NULL,
    person_id                             bigint NOT NULL,
    image_occurrence_id                   bigint NOT NULL,
    image_feature_event_field_concept_id  bigint,
    image_feature_event_id                bigint,
    image_feature_concept_id              bigint NOT NULL,
    image_feature_value_order             integer,
    image_feature_type_concept_id         bigint NOT NULL,
    image_finding_concept_id              bigint,
    image_finding_id                      bigint,
    anatomic_site_concept_id              bigint,
    alg_system                            varchar(10000),
    alg_datetime                          timestamp,
    image_instance_uid                    varchar(10000)
);

CREATE TABLE IF NOT EXISTS @etl.cdm_measurement (
    measurement_id                bigint NOT NULL,
    person_id                     bigint NOT NULL,
    measurement_concept_id        bigint NOT NULL,
    measurement_date              date   NOT NULL,
    measurement_datetime          timestamp,
    measurement_time              varchar(10),
    measurement_type_concept_id   bigint NOT NULL,
    operator_concept_id           bigint,
    value_as_number               numeric,
    value_as_concept_id           bigint,
    unit_concept_id               bigint,
    range_low                     numeric,
    range_high                    numeric,
    provider_id                   bigint,
    visit_occurrence_id           bigint,
    visit_detail_id               bigint,
    measurement_source_value      varchar(50),
    measurement_source_concept_id bigint,
    unit_source_value             varchar(50),
    value_source_value            varchar(50)
);

