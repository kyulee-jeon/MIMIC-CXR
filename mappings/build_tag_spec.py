"""Generate mappings/tag_spec.csv (and the derived custom-mapping CSVs) -- run once, commit the output.

tag_spec.csv is the single place that says *which* DICOM attribute becomes *which* CDM row.
It replaces the xlsx field lists (cxr-metadata-field_*.xlsx, mimic-ecg-metadata_*.xlsx) used in the
earlier notebooks.  attribute_concept_id comes from DICOM2OMOP's omop_table_staging_v5.csv
(concept_code = 8-hex-digit DICOM tag, concept_class_id = 'DICOM Attributes').

Usage:
    python mappings/build_tag_spec.py \
        --staging  <DICOM2OMOP>/files/"OMOP CDM Staging"/omop_table_staging_v5.csv \
        --cxr-xlsx <path>/cxr-metadata-field_260709.xlsx
"""
import argparse
import csv
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ZWSP = "​"

COLS = ["modality_group", "block", "k_scope", "row_seq", "tag", "keyword", "vr", "target_table",
        "value_field", "attribute_concept_id", "value_map", "const_source_value", "const_concept_id"]

# CXR CS tags, matched to the published Extension CSV (user decision: "same as the existing final CSV"):
#   ViewPosition / DetectorType / ImageLaterality  -> mapped by custom_mapping_csv/<name>.csv
#   ExposureControlMode / PhotometricInterpretation / LossyImageCompression -> row kept, value_as_concept_id = 0
#                                          (no concept mapping; raw code stays in value_source_value)
#   BodyPartExamined / PatientPosition / Modality  -> not loaded as measurements
CXR_CS_KEEP = {"00185101": "cxr_view_position", "00187004": "cxr_detector_type", "00200062": "cxr_image_laterality",
               "00187060": "", "00280004": "", "00282110": ""}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--staging", required=True)
    ap.add_argument("--cxr-xlsx", required=True)
    a = ap.parse_args()

    stg = pd.read_csv(a.staging, dtype=str)
    attr = stg[stg.concept_class_id == "DICOM Attributes"].set_index("concept_code")["concept_id"]

    rows = []
    x = pd.read_excel(a.cxr_xlsx, dtype=str)
    seq = 0
    for _, r in x.iterrows():
        tag = r["Tag"].zfill(8)
        kw = r["Keyword"].replace(ZWSP, "")
        table = r["event_table"].strip().lower()
        vf = r["event_value_field"].strip()
        if vr_is_cs := (r["VR"] == "CS"):
            if tag not in CXR_CS_KEEP:
                continue
        if table != "measurement":  # free-text attributes (Manufacturer ...) are not loaded: no observation_ADD
            continue
        vmap = CXR_CS_KEEP.get(tag, "")
        rows.append(["CXR", "pre", "instance", seq, tag, kw, r["VR"], table, vf, attr[tag], vmap, "", ""])
        seq += 1

    out = os.path.join(HERE, "tag_spec.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        w.writerows(rows)
    print(f"wrote {out}: {len(rows)} rows")


if __name__ == "__main__":
    main()
