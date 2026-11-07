"""Build vocabulary/out/{concept,vocabulary,concept_class}_ADD.csv -- the DICOM vocabulary extension.

Source: DICOM2OMOP omop_table_staging_v5.csv (8,811 concepts, ids 2128000010+, vocabulary_id = 'DICOM').
DICOM2OMOP does not ship the three Metadata concepts that vocabulary / concept_class rows point at
(2128000000-2128000002), so they are added here -- same as the published concept_ADD.csv.

    python vocabulary/build_vocabulary_add.py --staging <.../OMOP CDM Staging/omop_table_staging_v5.csv>
"""
import argparse
import csv
import os

import pandas as pd

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
CONCEPT_COLS = ["concept_id", "concept_name", "domain_id", "vocabulary_id", "concept_class_id", "standard_concept",
                "concept_code", "valid_start_date", "valid_end_date", "invalid_reason"]

META = [  # concept_id, name, domain, vocabulary, class
    (2128000000, "DICOM", "Metadata", "Vocabulary", "Vocabulary"),
    (2128000001, "DICOM Attributes", "Metadata", "Concept Class", "Concept Class"),
    (2128000002, "DICOM Value Sets", "Metadata", "Concept Class", "Concept Class"),
]


def iso(d):  # staging uses 19930101
    d = str(d)
    return f"{d[:4]}-{d[4:6]}-{d[6:]}" if d.isdigit() and len(d) == 8 else d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--staging", required=True)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    s = pd.read_csv(a.staging, dtype=str, keep_default_na=False)
    s["valid_start_date"] = s["valid_start_date"].map(iso)
    s["valid_end_date"] = s["valid_end_date"].map(iso)
    meta = pd.DataFrame([[str(i), n, d, v, c, "", "OMOP generated", "1993-01-01", "2099-12-31", ""] for i, n, d, v, c in META],
                        columns=CONCEPT_COLS)
    pd.concat([meta, s[CONCEPT_COLS]]).to_csv(os.path.join(OUT, "concept_ADD.csv"), index=False, quoting=csv.QUOTE_NONNUMERIC)

    pd.DataFrame([["DICOM", "Digital Imaging and Communications in Medicine (National Electrical Manufacturers Association)",
                   "https://www.dicomstandard.org/current", "NEMA Standard PS3", "2128000000"]],
                 columns=["vocabulary_id", "vocabulary_name", "vocabulary_reference", "vocabulary_version", "vocabulary_concept_id"]
                 ).to_csv(os.path.join(OUT, "vocabulary_ADD.csv"), index=False)
    pd.DataFrame([["DICOM Attributes", "DICOM Attributes", "2128000001"], ["DICOM Value Sets", "DICOM Value Sets", "2128000002"]],
                 columns=["concept_class_id", "concept_class_name", "concept_class_concept_id"]
                 ).to_csv(os.path.join(OUT, "concept_class_ADD.csv"), index=False)
    print(f"concept_ADD rows: {len(meta) + len(s)}")


if __name__ == "__main__":
    main()
