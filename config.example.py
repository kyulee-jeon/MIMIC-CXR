"""Connection / path settings.  Copy this file to config.py (not tracked by git) and/or set the environment variables.
The database values have no defaults on purpose: never commit credentials."""
import os

# ----------------------------------------------------------------- PostgreSQL
DB_USER = os.getenv("DB_USER", "")              # required
DB_PASSWORD = os.getenv("DB_PASSWORD", "")      # required
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "")              # required

# Schemas.  CDM_SCHEMA holds the finished MIMIC-IV -> OMOP CDM (OHDSI/MIMIC output): person,
# visit_occurrence, procedure_occurrence, concept ...  ETL_SCHEMA holds everything this repo creates.
CDM_SCHEMA = os.getenv("CDM_SCHEMA", "public")
VOC_SCHEMA = os.getenv("VOC_SCHEMA", "public")
ETL_SCHEMA = os.getenv("ETL_SCHEMA", "micdm_etl")

# --------------------------------------------------------------------- Medallion layers
# bronze = DICOM files in DICOM_DIR (read-only; any folder: local disk, NAS, an s3fs mount ...)
# silver = tag-exploded parquet written by third_party/dicom_to_parquet, partitioned modality=*/tag=*/
#          (point SILVER_DIR of MIMIC-ECG and MIMIC-CXR at the SAME folder: modality=ECG, modality=DX, modality=CR ...)
# gold   = OMOP CDM imaging extension tables (cdm_* in ETL_SCHEMA, exported as *_ADD.csv)
DATASET = "CXR"                                                       # modality_group in mappings/
DICOM_DIR = os.getenv("DICOM_DIR", "").rstrip("/")   # folder holding the DICOM files (p10/p10000032/s.../x.dcm below it); required; the series folders below it become image_occurrence.local_path

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.getenv("WORK_DIR", os.path.join(REPO_DIR, "work"))
SILVER_DIR = os.getenv("SILVER_DIR", os.path.join(WORK_DIR, "silver"))


def dsn() -> str:
    return f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASSWORD}"


def sql_params() -> dict:
    """Placeholders substituted into sql/*.sql ( @etl, @cdm, @voc, @dicom_dir )."""
    return {"@etl": ETL_SCHEMA, "@cdm": CDM_SCHEMA, "@voc": VOC_SCHEMA, "@dicom_dir": DICOM_DIR}
