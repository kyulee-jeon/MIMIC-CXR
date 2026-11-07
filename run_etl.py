"""Orchestrator.  Runs the five OHDSI/MIMIC logic steps for the imaging extension, in order.

    python run_etl.py --list                       # show steps
    python run_etl.py --steps ddl,config,src,snapshot,clean,concept,mapped,cdm,qa
    python run_etl.py --steps clean,concept,mapped,cdm   # rerun from the cleaning step
    python run_etl.py --steps vocab                # one-off: load DICOM vocabulary into @voc (concept / vocabulary / concept_class)

Steps (OHDSI/MIMIC logic step in brackets)
    ddl       create cdm_* target tables
    config    load mappings/*.csv + custom_mapping_csv/*.csv into src_tag_spec / src_modality_profile / src_custom_map
    src       [1 snapshot] load the silver parquet (extract/build_silver.py) into src_dicom_header (needed tags only)
    snapshot  [1 snapshot] freeze person / visit_occurrence / procedure_occurrence of the finished MIMIC-IV CDM
    clean     [2 clean]    lk_img_*_clean   (needs --dicom_dir: the DICOM source folder -> image_occurrence.local_path = series folder)
    concept   [3 map]      lk_img_*_concept + lk_img_unmapped (review list)
    mapped    [4 join]     lk_img_*_mapped (ids, person / visit / procedure links)
    cdm       [5 load]     cdm_image_occurrence / measurement / image_feature
    qa        run qa/validate.py checks
"""
import argparse
import glob
import io
import os
import sys

import pandas as pd
import psycopg2

import config

REPO = os.path.dirname(os.path.abspath(__file__))
SQL = lambda *p: os.path.join(REPO, "sql", *p)  # noqa: E731


def sql_text(path):
    t = open(path).read()
    for k, v in config.sql_params().items():
        if k == "@dicom_dir":
            t = t.replace(k, v.replace("'", "''"))  # literal, inside SQL string quotes
        else:
            t = t.replace(k + ".", v + ".")  # @etl.table -> schema.table
    return t


def run_sql_file(cur, path):
    print(f"  sql  {os.path.relpath(path, REPO)}", flush=True)
    cur.execute(sql_text(path))
    cur.connection.commit()


def copy_df(cur, df, table, cols=None):
    cols = cols or list(df.columns)
    buf = io.StringIO()
    df[cols].to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    cur.copy_expert(f"COPY {config.ETL_SCHEMA}.{table} ({','.join(cols)}) FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


def create_text_table(cur, table, cols):
    cur.execute(f"DROP TABLE IF EXISTS {config.ETL_SCHEMA}.{table}")
    cur.execute(f"CREATE TABLE {config.ETL_SCHEMA}.{table} ({', '.join(c + ' text' for c in cols)})")


# ------------------------------------------------------------------------ steps
def step_ddl(cur):
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {config.ETL_SCHEMA}")
    run_sql_file(cur, os.path.join(REPO, "ddl", "01_micdm_tables.sql"))


def step_config(cur):
    for name, path in [("src_tag_spec", "mappings/tag_spec.csv"), ("src_modality_profile", "mappings/modality_profile.csv")]:
        df = pd.read_csv(os.path.join(REPO, path), dtype=str, keep_default_na=False)
        create_text_table(cur, name, list(df.columns))
        copy_df(cur, df, name)
        print(f"  cfg  {name}: {len(df)} rows")
    maps = []
    for f in sorted(glob.glob(os.path.join(REPO, "custom_mapping_csv", "*.csv"))):
        d = pd.read_csv(f, dtype=str, keep_default_na=False)
        d.insert(0, "map_name", os.path.splitext(os.path.basename(f))[0])
        maps.append(d)
    m = pd.concat(maps, ignore_index=True)
    create_text_table(cur, "src_custom_map", list(m.columns))
    copy_df(cur, m, "src_custom_map")
    print(f"  cfg  src_custom_map: {len(m)} rows from {len(maps)} files")


def step_src(cur, silver):
    """Logic step 1: snapshot of the silver layer (only the tags that tag_spec needs, plus StudyDate 00080020 and StudyTime 00080030)."""
    import pyarrow.csv as pacsv
    import pyarrow.dataset as pads

    spec = pd.read_csv(os.path.join(REPO, "mappings", "tag_spec.csv"), dtype=str, keep_default_na=False)
    wanted = sorted(set(spec.tag) | {"00080020", "00080030"})  # StudyDate, StudyTime
    if not silver.startswith("s3://") and not os.path.isdir(silver):
        sys.exit(f"silver dir {silver} not found; run extract/build_silver.py first")
    dset = pads.dataset(silver, format="parquet", partitioning="hive", exclude_invalid_files=False)  # local dir or s3://bucket/prefix
    cols = ["file_path", "study_uid", "series_uid", "instance_uid", "sop_class_uid", "modality", "tag", "vr", "vm", "path", "value"]
    create_text_table(cur, "src_dicom_header", cols)
    n = 0
    for batch in dset.scanner(columns=cols, filter=pads.field("tag").isin(wanted), batch_size=500_000).to_batches():
        buf = io.BytesIO()
        pacsv.write_csv(batch, buf, write_options=pacsv.WriteOptions(include_header=False))
        buf.seek(0)
        cur.copy_expert(f"COPY {config.ETL_SCHEMA}.src_dicom_header ({','.join(cols)}) FROM STDIN WITH (FORMAT csv)", buf)
        n += batch.num_rows
    cur.execute(f"CREATE INDEX ix_src_hdr ON {config.ETL_SCHEMA}.src_dicom_header (modality, tag, instance_uid)")
    print(f"  src  src_dicom_header={n} rows from {silver}")


def step_vocab(cur):
    """Load the DICOM vocabulary (concept_ADD / vocabulary_ADD / concept_class_ADD) into the vocabulary schema; idempotent."""
    vdir = os.path.join(REPO, "vocabulary", "out")
    voc = config.VOC_SCHEMA
    for tbl, fn, key in [("concept", "concept_ADD.csv", "concept_id"), ("vocabulary", "vocabulary_ADD.csv", "vocabulary_id"),
                         ("concept_class", "concept_class_ADD.csv", "concept_class_id")]:
        df = pd.read_csv(os.path.join(vdir, fn), dtype=str, keep_default_na=False).replace({"": None})
        tmp = f"tmp_{tbl}_add"
        cur.execute(f"DROP TABLE IF EXISTS {config.ETL_SCHEMA}.{tmp}")
        cur.execute(f"CREATE TABLE {config.ETL_SCHEMA}.{tmp} AS SELECT * FROM {voc}.{tbl} WHERE false")
        copy_df(cur, df, tmp)
        # concept first: vocabulary / concept_class carry FKs into it
        cur.execute(f"INSERT INTO {voc}.{tbl} SELECT t.* FROM {config.ETL_SCHEMA}.{tmp} t "
                    f"WHERE NOT EXISTS (SELECT 1 FROM {voc}.{tbl} x WHERE x.{key}::text = t.{key}::text)")
        print(f"  voc  {tbl}: +{cur.rowcount}")
        cur.execute(f"DROP TABLE {config.ETL_SCHEMA}.{tmp}")


GROUPS = {
    "snapshot": [SQL("st_01_src_cdm_snapshot.sql")],
    "clean": [SQL("lk_10_img_clean.sql"), SQL("lk_11_feature_clean.sql")],
    "concept": [SQL("lk_20_img_concept.sql")],
    "mapped": [SQL("lk_30_img_mapped.sql")],
    "cdm": [SQL("cdm_10_image_occurrence.sql"), SQL("cdm_20_measurement.sql"),
            SQL("cdm_40_image_feature.sql")],
}
ORDER = ["ddl", "config", "src", "snapshot", "clean", "concept", "mapped", "cdm", "qa"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", default=",".join(ORDER))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--silver", default=config.SILVER_DIR)
    ap.add_argument("--dicom_dir", default=None, help="folder that holds the DICOM files (bronze); series folders below it become image_occurrence.local_path. Or env DICOM_DIR")
    a = ap.parse_args()
    if a.dicom_dir:
        config.DICOM_DIR = a.dicom_dir.rstrip("/")
    if "clean" in a.steps.split(",") and not config.DICOM_DIR:
        sys.exit("DICOM source folder missing: pass --dicom_dir <folder> or set env DICOM_DIR (it becomes image_occurrence.local_path)")
    if a.list:
        print(__doc__)
        return
    conn = psycopg2.connect(config.dsn())
    cur = conn.cursor()
    for s in a.steps.split(","):
        print(f"== {s}", flush=True)
        if s == "ddl":
            step_ddl(cur)
        elif s == "config":
            step_config(cur)
        elif s == "src":
            step_src(cur, a.silver)
        elif s == "vocab":
            step_vocab(cur)
        elif s in GROUPS:
            for p in GROUPS[s]:
                run_sql_file(cur, p)
        elif s == "qa":
            import qa.validate as v
            v.main(conn)
        else:
            sys.exit(f"unknown step {s}")
        conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
