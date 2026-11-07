"""Unload step: write the cdm_* tables as the published Extension/*.csv files (header row, ISO dates, NULL = empty).

    python export/export_csv.py --out work/export              # local files only
    python export/export_csv.py --out work/export --upload_to s3://bucket/prefix/    # optional: also aws s3 cp them there

Files: image_occurrence.csv, image_feature.csv, measurement_ADD.csv
       + vocabulary ADD files copied from vocabulary/out/ (concept_ADD.csv, vocabulary_ADD.csv, concept_class_ADD.csv)
"""
import argparse
import csv
import os
import shutil
import subprocess
import sys

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

ID_COLS = {  # 64-bit hashed / banded ids: anything that is not an exact int in the file is a float64 round-trip accident
    "image_occurrence.csv": ["image_occurrence_id", "person_id", "visit_occurrence_id", "procedure_occurrence_id"],
    "image_feature.csv": ["image_feature_id", "person_id", "image_occurrence_id", "image_feature_event_id"],
    "measurement_ADD.csv": ["measurement_id", "person_id", "visit_occurrence_id"],
}
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLES = [("cdm_image_occurrence", "image_occurrence.csv"), ("cdm_image_feature", "image_feature.csv"),
          ("cdm_measurement", "measurement_ADD.csv")]


def verify_ids(cur, tbl, path, cols):
    """Re-read the written CSV as plain text and compare count / non-null count / exact sum of every id column with the table.
    int() raises on '1.2E+18' or '123.0', so a float round-trip (pandas default for a nullable bigint) cannot pass."""
    with open(path, newline="") as fh:
        rd = csv.DictReader(fh)
        n, nn, sm = 0, {c: 0 for c in cols}, {c: 0 for c in cols}
        for r in rd:
            n += 1
            for c in cols:
                if r[c] != "":
                    nn[c] += 1
                    sm[c] += int(r[c])
    cur.execute(f"SELECT count(*), " + ", ".join(f"count({c}), COALESCE(sum({c}::numeric), 0)" for c in cols) + f" FROM {config.ETL_SCHEMA}.{tbl}")
    row = cur.fetchone()
    ok = row[0] == n
    for i, c in enumerate(cols):
        ok &= row[1 + 2 * i] == nn[c] and int(row[2 + 2 * i]) == sm[c]
    print(f"  verify {os.path.basename(path)}: {'OK' if ok else 'MISMATCH'} ({n} rows, ids {', '.join(cols)})")
    if not ok:
        sys.exit(f"{path}: id columns differ from {tbl} (float64 round-trip?)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(config.WORK_DIR, "export"))
    ap.add_argument("--no-verify", action="store_true", help="skip the exact id round-trip check (slow on the 280M-row measurement file)")
    ap.add_argument("--upload_to", help="optional destination, e.g. s3://bucket/prefix/ : the files are copied there with aws s3 cp (outward-facing: opt-in)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    conn = psycopg2.connect(config.dsn())
    cur = conn.cursor()
    for tbl, fn in TABLES:
        with open(os.path.join(a.out, fn), "w") as fh:
            cur.copy_expert(f"COPY {config.ETL_SCHEMA}.{tbl} TO STDOUT WITH (FORMAT csv, HEADER true)", fh)
        print("wrote", fn)
        if not a.no_verify:
            verify_ids(cur, tbl, os.path.join(a.out, fn), ID_COLS[fn])
    for fn in ("concept_ADD.csv", "vocabulary_ADD.csv", "concept_class_ADD.csv"):
        src = os.path.join(REPO, "vocabulary", "out", fn)
        if os.path.exists(src):
            shutil.copy(src, a.out)
    if a.upload_to:
        subprocess.run(["aws", "s3", "cp", a.out, a.upload_to, "--recursive"], check=True)


if __name__ == "__main__":
    main()
