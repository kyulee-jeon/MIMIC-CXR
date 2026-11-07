"""Static checks on the mapping files (no database / S3 needed).  pytest tests/"""
import os

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = pd.read_csv(os.path.join(REPO, "mappings", "tag_spec.csv"), dtype=str, keep_default_na=False)
prof = pd.read_csv(os.path.join(REPO, "mappings", "modality_profile.csv"), dtype=str, keep_default_na=False)


def test_tags_are_8_hex_and_unique_per_modality():
    assert spec.tag.str.fullmatch(r"[0-9A-F]{8}").all()
    assert not spec.duplicated(["modality_group", "tag"]).any()


OHDSI_MAP_COLS = ("concept_name,source_concept_id,source_vocabulary_id,source_domain_id,source_concept_class_id,standard_concept,"
                  "concept_code,valid_start_date,valid_end_date,invalid_reason,target_concept_id,target_concept_name,relationship_id,"
                  "reverse_relationship_id,relationship_valid_start_date,relationship_end_date,invalid_reason_cr").split(",")


def test_every_value_map_has_a_file():
    for m in set(spec.value_map) - {""}:
        assert os.path.exists(os.path.join(REPO, "custom_mapping_csv", m + ".csv")), m


def test_custom_maps_have_unique_source_codes():
    d = os.path.join(REPO, "custom_mapping_csv")
    for f in sorted(x for x in os.listdir(d) if x.endswith(".csv")):
        m = pd.read_csv(os.path.join(d, f), dtype=str)
        assert list(m.columns) == OHDSI_MAP_COLS, f
        assert not m.concept_code.duplicated().any(), f
        assert (m.relationship_id == "Maps to").all(), f
        assert m.source_concept_id.astype("int64").between(2129000000, 2129999999).all(), f


def test_source_concept_ids_unique_across_maps():
    d = os.path.join(REPO, "custom_mapping_csv")
    ids = pd.concat([pd.read_csv(os.path.join(d, f), dtype=str).source_concept_id for f in os.listdir(d) if f.endswith(".csv")])
    assert ids.is_unique


def test_id_bands_do_not_overlap():
    for col in ("io_id_base", "feature_id_base", "measurement_id_base"):
        assert prof[col].astype("int64").is_unique, col


def test_profile_maps_every_group_to_dicom_modalities():
    assert (prof.dicom_modality_values != "").all()
    assert set(prof.modality_group) == set(spec.modality_group)


def test_no_float_path_for_ids():
    """ids are 64-bit hashes (> 2**53): pandas default parsing of a nullable bigint column is float64 and silently rounds them.
    Code outside tests must read tables/CSVs as text (dtype=str) and write the CDM tables with COPY, never via pandas numbers."""
    import re
    bad = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in ("third_party", "tests", ".git", "work")]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            src = open(os.path.join(root, fn)).read()
            if re.search(r"read_sql|read_parquet|\.to_pandas\(", src):
                bad.append(fn + ": read_sql/read_parquet/to_pandas")
            for m in re.finditer(r"read_csv\((?:[^()]|\([^()]*\))*\)", src):
                if "dtype=str" not in m.group(0):
                    bad.append(fn + ": read_csv without dtype=str")
    assert not bad, bad
