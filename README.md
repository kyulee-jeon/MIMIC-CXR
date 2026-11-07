# MIMIC-CXR

This repository loads the DICOM metadata of MIMIC-CXR v2.1.0 into the Medical Imaging extension of the OMOP CDM (MI-CDM), on top of an existing MIMIC-IV v3.1 OMOP CDM. The result is one CDM in which chest radiographs, their acquisition parameters and the patients' clinical records can be queried together with standard OHDSI tools.

MI-CDM is the imaging extension defined by the OHDSI Medical Imaging Working Group. It adds two tables, `image_occurrence` and `image_feature`, and stores DICOM attributes as `measurement` rows coded with a DICOM vocabulary.

| | |
|---|---|
| Input: clinical data | MIMIC-IV v3.1 already loaded into the OMOP CDM (`person`, `visit_occurrence`, `procedure_occurrence`, `concept` …), e.g. with [OHDSI/MIMIC](https://github.com/OHDSI/MIMIC) |
| Input: images | MIMIC-CXR v2.1.0 as DICOM, in any folder you point `DICOM_DIR` at |
| Output | `image_occurrence`, `image_feature`, `measurement` rows for the images, plus the DICOM vocabulary (`concept_ADD`, `vocabulary_ADD`, `concept_class_ADD`) |


## Data flow (medallion layers)

The ETL reads DICOM headers once into a flat table (silver) and builds the CDM tables from it (gold), so a new attribute is a change in a spec file, not a new extraction.

| Layer | What it holds | Produced by |
|---|---|---|
| **Bronze** | The DICOM files in `DICOM_DIR`, read-only | MIMIC-CXR download |
| **Silver** | One parquet row per scalar value of each DICOM file, partitioned as `<SILVER_DIR>/modality=<DX\|CR>/tag=<8 hex>/part-*.parquet` | `extract/build_silver.py`, which runs the `third_party/dicom_to_parquet` submodule (pinned commit) |
| **Gold** | The MI-CDM tables `cdm_image_occurrence`, `cdm_image_feature`, `cdm_measurement`, exported as `*_ADD.csv` | `run_etl.py` (SQL steps) and `export/export_csv.py` |

A silver row has these columns:

* `file_path`, `study_uid`, `series_uid`, `instance_uid`, `sop_class_uid`: which file and which study / series / instance it comes from
* `modality`, `tag`, `vr`, `vm`: the DICOM attribute and its value representation / multiplicity
* `path`: keeps nested sequences traceable
* `value`: the value as text

Silver contains every tag, private tags included. The ETL loads only the tags listed in `mappings/tag_spec.csv`.

## OHDSI/MIMIC's five logic steps, applied

| # | OHDSI/MIMIC step | Here | Artifacts |
|---|---|---|---|
| 1 | snapshot → `src_` | silver parquet → `run_etl.py src` (needed tags only; local dir or `s3://`); `sql/st_01_src_cdm_snapshot.sql` (CDM tables) | `src_dicom_header`, `src_person`, `src_visit`, `src_procedure`, `src_tag_spec`, `src_modality_profile`, `src_custom_map` |
| 2 | clean → `lk_*_clean` | `sql/lk_10_img_clean.sql`, `sql/lk_11_feature_clean.sql` | `lk_img_file_clean`, `lk_img_occurrence_clean`, `lk_img_feature_clean` |
| 3 | map codes → `lk_*_concept` | `sql/lk_20_img_concept.sql`; custom mappings = `custom_mapping_csv/*.csv` (OHDSI/MIMIC `gcpt_*.csv` format) | `lk_img_modality_concept`, `lk_img_value_concept`, **`lk_img_unmapped`** (review list) |
| 4 | join → `lk_*_mapped` | `sql/lk_30_img_mapped.sql` (person / visit / procedure links, ids) | `lk_img_occurrence_mapped`, `lk_img_feature_mapped` |
| 5 | distribute by target domain → `cdm_` | `sql/cdm_*.sql` (attribute values → `measurement`, link rows → `image_feature`) | `cdm_image_occurrence`, `cdm_image_feature`, `cdm_measurement` |
| – | unload | `export/export_csv.py` (PostgreSQL `COPY`, then an exact id round-trip check) | `*.csv` |

SQL files use `@etl` / `@cdm` / `@voc` placeholders (like OHDSI/MIMIC's `@etl_dataset`), set in `config.py`.

## Relation to the MI-CDM conventions

Follows the [ImageWG Medical Imaging Extension Conventions](https://github.com/OHDSI/ImageWG/wiki/Medical-Imaging-Extension-Conventions) and the [ETL guide for DICOM attributes](https://github.com/OHDSI/ImageWG/wiki/Convention:-ETL-DICOM-Attributes-to-OMOP). Steps 1-6 and 11 are implemented; steps 7-10 cover image-derived features (algorithm results, structured reports) and are outside this DICOM-attribute ETL.

| Wiki step | Concrete implementation |
|---|---|
| 1-2 install CDM, create extension tables | `ddl/01_micdm_tables.sql` (created as `cdm_*` in the ETL schema) |
| 3 load DICOM vocabulary | custom `vocabulary_id='DICOM'`, built with [paulnagy/DICOM2OMOP](https://github.com/paulnagy/DICOM2OMOP) (see Prerequisites; `omop_table_staging_v5.csv` is pinned) |
| 4 extract headers only | `extract/build_silver.py` → `dicom_to_parquet.py --skip_pixel_data` |
| 5 choose attributes | `mappings/tag_spec.csv` (22 attributes, single source of truth). The wiki lists proposed attributes for MR, CT and MG only; this list is a proposal for DX/CR |
| 6 series-level → `image_occurrence`; other attributes → `measurement` | one occurrence per (study, series); each attribute value becomes a measurement row |
| 11 custom concepts in the 2-billion range | DICOM concepts 2128000000+ (DICOM2OMOP); source concepts of `custom_mapping_csv` 2129000000+ |

Differences from the conventions:

* **Provenance link.** The ETL guide links `measurement` to `image_occurrence` with `measurement_event_id`, and uses `image_feature` for derived findings only. Here each measurement row also gets an `image_feature` row that carries the instance UID (`image_instance_uid`) and the value order of multi-valued attributes (`image_feature_value_order`); the wiki DDL has no place for either. `image_feature_event_id` + `image_feature_event_field_concept_id` (1147330 = measurement) point at the measurement, and `measurement_event_id` is not set.
* **DDL.** `image_instance_uid` and `image_feature_value_order` are added to `image_feature`; `procedure_occurrence_id` of `image_occurrence` is nullable (NOT NULL in the wiki DDL).
* **Source values.** The DICOM tag goes to `measurement_source_value` and the raw value to `value_source_value`; the wiki puts the raw value in `measurement_source_value`.

## Prerequisites

1. **MIMIC-CXR v2.1.0 data from PhysioNet** - credentialed access with a signed data use agreement; no data is included in this repository. It is distributed as DICOM, so the downloaded `files/` folder is used as is.
2. **MIMIC-IV v3.1 in OMOP CDM v5.3.1**, built with [OHDSI/MIMIC](https://github.com/OHDSI/MIMIC) in the same PostgreSQL database <!-- CHECK: OHDSI/MIMIC main is BigQuery-based and last updated for MIMIC-IV v2.2; name the fork/commit used for PostgreSQL + v3.1 --> (schema = `CDM_SCHEMA`). Needed from it: `person` with `person_source_value = subject_id`, `visit_occurrence`, `procedure_occurrence` (`procedure_source_value = '225459'`, chest X-ray, is used to link a procedure), and the vocabularies (`concept`, …) with the standard concepts used in `custom_mapping_csv/` (SNOMED etc.).
3. **DICOM vocabulary** (custom `vocabulary_id = 'DICOM'`: 8,814 concepts, ids 2128000000+) from [paulnagy/DICOM2OMOP](https://github.com/paulnagy/DICOM2OMOP): `files/OMOP CDM Staging/omop_table_staging_v5.csv` holds the concepts, and its code builds the `concept`, `concept_class` and `vocabulary` rows - follow it and load them into the CDM vocabulary tables. `vocabulary/build_vocabulary_add.py` + `python run_etl.py --steps vocab` is a shortcut that produces the same rows from `omop_table_staging_v5.csv`.
4. **The folder that holds the DICOM files** - you pass it at the start (`DICOM_DIR` / `--dicom_dir`); nothing is assumed about S3 or mounts. It is the folder that contains `p10/p10000032/s50414267/<file>.dcm` (i.e. the `files/` folder), and **it is written as the prefix of `image_occurrence.local_path`** (`<DICOM_DIR>/p10/p10000032/s50414267` - `image_occurrence` is series-level, so it points at the series folder, not at a file).
5. Python with `pydicom`, `pyarrow`, `psycopg2`, `pandas` (`pip install -r requirements.txt`) and the `third_party/dicom_to_parquet` submodule.

## Run

```bash
git clone --recurse-submodules <this repo>        # or: git submodule update --init
pip install -r requirements.txt
export DB_NAME=<your_db> ETL_SCHEMA=micdm_etl_cxr   # copy config.example.py to config.py (not tracked); every setting is documented there (SILVER_DIR, CDM_SCHEMA …)
export DICOM_DIR=/path/to/mimic-cxr/files               # the DICOM source folder (prerequisite 4)

# bronze -> silver (resumable; smoke test first)
python extract/build_silver.py --workers 16 --limit_dirs 1 --max_files 100
python extract/build_silver.py --workers 16                       # 377,110 files

# silver -> gold
python run_etl.py --steps ddl,config,src,snapshot,clean,concept,mapped,cdm,qa
python export/export_csv.py --out work/export                      # --upload_to s3://bucket/prefix/ to also copy them to S3
pytest tests/
```

An existing silver of the same format can be reused instead of re-reading DICOM: `python run_etl.py --silver s3://bucket/prefix …` or a local `SILVER_DIR`.

## Conventions (edit in `mappings/` and `custom_mapping_csv/`)

* 1 `image_occurrence` per (study, series), `local_path` = the series (study) folder; one feature row set per instance (`image_instance_uid`). Modality DX 2128009197 / CR 2128009189, anatomic site 37303885. Procedure link: same person + date + `procedure_source_value = 225459`.
* CS tags: ViewPosition / DetectorType / ImageLaterality are mapped by `custom_mapping_csv`; ExposureControlMode / PhotometricInterpretation / LossyImageCompression keep concept 0 (raw code in `value_source_value`). ViewPosition variants (`AP LLD` …) merge into the base view.
* Multi-valued numeric attributes (PixelSpacing …) → one row per value, `image_feature_value_order` 1..n, raw `"[a, b]"` kept in `value_source_value`.
* Only measurement attributes are loaded (no `observation_ADD`).
* `measurement_source_value` = 8-digit tag, `value_source_value` = raw DICOM text. Unmapped / empty CS value → `value_as_concept_id = 0`.
* ids = positional bands (`mappings/modality_profile.csv`), deterministic for the same input; the bands of the two datasets do not overlap.
* **`custom_mapping_csv/*.csv`** follow OHDSI/MIMIC's `custom_mapping_csv/gcpt_*.csv`: each file is a raw → standard value table only. One row = one *source concept* (`source_concept_id` 2129000001+, `source_vocabulary_id` = `dicom_<map>`, `concept_code` = raw DICOM code, validity dates) plus its `Maps to` relationship (`target_concept_id`, `target_concept_name` = the standard concept's name, added for readability and not used by the ETL, `relationship_id`, `reverse_relationship_id`, relationship dates, `invalid_reason_cr`). Which attribute a file belongs to is `tag_spec.csv` (`value_map` + `attribute_concept_id`), the analogue of DICOM2OMOP's attribute → value `Maps to value` (DICOM2OMOP ships it only for Modality). The ETL joins on `concept_code` and only uses valid `Maps to` rows; retire a mapping by filling `invalid_reason_cr`.
* **Never let an id pass through pandas numbers.** person / visit / procedure / event ids are 64-bit hashes (> 2^53). A nullable bigint column (e.g. `visit_occurrence_id`) read or written by pandas becomes float64 and is silently rounded - joins to `visit_occurrence` then break for some rows. Here the CSVs are written by PostgreSQL `COPY` (no pandas), config tables are read as `dtype=str`, silver is loaded with pyarrow as text, `export/export_csv.py` re-reads every written CSV and compares row count, non-null count and exact sum of each id column with the table (`--no-verify` to skip), and `tests/test_spec.py::test_no_float_path_for_ids` fails if code reads data through pandas numbers.
* `person_id` is joined as exact int64 via `person_source_value = subject_id`.
* `measurement_date` is each instance's own StudyDate.
* `image_occurrence.local_path` = the **series folder**: `DICOM_DIR` + `/p<NN>/p<subject>/s<study>` (image_occurrence is series-level).

## Validation

Full MIMIC-CXR run <!-- CHECK: date and commit of the run -->:

| | count |
|---|---|
| DICOM files | 377,110 |
| studies in the source | 227,835 |
| `image_occurrence` rows | 215,006 |
| subjects → persons | 65,379 → 60,898 |
| `measurement` + `image_feature` rows | 8,439,347 |
| `image_occurrence` linked to a visit | 195,574 (91.0 %): 163,198 stay, 32,376 clinic |

<!-- CHECK: attrition rule (e.g. subjects without a person in the CDM) and that there is one series per study, so occurrences = studies -->

The visit rule and its comparison with a date-only rule (196,353 linked, 91.3 %) are in [docs/visit_link.md](docs/visit_link.md). <!-- CHECK: choose one rule as the public reference; the paper reports 91.3 % -->

`qa/validate.py` runs structural checks (one `image_feature` per `measurement`, ids unique, one occurrence per (study, series), no orphan rows, person / date / concept agreement between the tables). `qa/compare_published.py` compares the content of two builds of the same tables (ids are positional and excluded); it is a development aid. The visit figures were computed from `src_dicom_header` with the same logic as `lk_30`; re-check them after a full run.

## Known limitations

* Open mapping decisions: DetectorType `SCINTILLATOR` (66,692 images) and ImageLaterality `L/R/B` currently get concept 0; anything unmapped is listed in `lk_img_unmapped`.
* **`dicom_to_parquet` multi-value behaviour**: its README says VM>1 is split into rows, but under pydicom 3.x the `MultiValue` is not a `list`/`tuple`, so the tool writes one row with the text `"[0.20, 0.20]"` (`vm=2`). The ETL's SQL splits that text (and also accepts per-value rows if the tool is fixed). The submodule is not modified.
* **Visit link**: no tolerance before the visit start (an ED registration may be stamped after the image); 19,432 occurrences get no visit. See [docs/visit_link.md](docs/visit_link.md).
* `measurement` uses CDM 5.4 columns, although the base CDM is 5.3.

## Repository layout

```
run_etl.py            step runner (ddl, config, src, snapshot, clean, concept, mapped, cdm, qa, vocab)
extract/              bronze -> silver (DICOM headers to parquet)
sql/                  src_ / lk_ / cdm_ SQL steps
ddl/                  extension table DDL
mappings/             tag_spec.csv (attribute list), modality_profile.csv
custom_mapping_csv/   raw DICOM value -> standard concept tables
vocabulary/           DICOM vocabulary (concept_ADD …) builder
export/               CSV export with exact id check
qa/, tests/           structural checks, build comparison
docs/                 visit-link rule and comparison
log/                  decision records
third_party/          dicom_to_parquet (submodule)
```

## Related

* [OHDSI/MIMIC](https://github.com/OHDSI/MIMIC) - MIMIC-IV to OMOP ETL; this repository follows its five logic steps
* [paulnagy/DICOM2OMOP](https://github.com/paulnagy/DICOM2OMOP) - DICOM vocabulary and DICOM-to-MI-CDM ETL examples
* [ImageWG Medical Imaging Extension Conventions](https://github.com/OHDSI/ImageWG/wiki/Medical-Imaging-Extension-Conventions) - MI-CDM ETL conventions and guideline
* [MIMIC-CXR on PhysioNet](https://physionet.org/content/mimic-cxr/2.1.0/)

## Citation

<!-- CHECK: confirm each reference and add the paper of this work -->

* Johnson AEW, Pollard TJ, Berkowitz SJ, et al. MIMIC-CXR, a de-identified publicly available database of chest radiographs with free-text reports. *Sci Data* 2019;6:317.
* Johnson AEW, Bulgarelli L, Shen L, et al. MIMIC-IV, a freely accessible electronic health record dataset. *Sci Data* 2023;10:1.
* Goldberger AL, Amaral LAN, Glass L, et al. PhysioBank, PhysioToolkit, and PhysioNet. *Circulation* 2000;101(23):e215-e220.
* Development of Medical Imaging Data Standardization for Imaging-Based Observational Research: OMOP Common Data Model Extension. [PubMed 38315345](https://pubmed.ncbi.nlm.nih.gov/38315345/)

## License

Apache-2.0, as OHDSI/MIMIC and DICOM2OMOP. <!-- CHECK: add the LICENSE file once confirmed -->
