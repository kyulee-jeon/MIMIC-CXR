"""Reproducibility check: compare this ETL's output with an already published Extension (loaded in the CDM schema).

Ids are positional bands, so rows are compared by CONTENT (multiset of all columns except the ids), per
(study_uid, series_uid) that exists in the ETL output.  local_path: the published value is a file, ours the series
folder, so the published path is compared without its file name.  visit_occurrence_id is reported separately because a few
percent of images fall into several overlapping visits and the published pick is arbitrary.

    ETL_SCHEMA=micdm_etl python -m qa.compare_published
"""
import argparse
import os
import sys

import pandas as pd
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

MEAS = ("person_id, measurement_concept_id, measurement_date, measurement_type_concept_id, operator_concept_id, value_as_number, "
        "value_as_concept_id, unit_concept_id, range_low, range_high, provider_id, measurement_source_value, "
        "measurement_source_concept_id, unit_source_value, value_source_value")


def main():
    ap = argparse.ArgumentParser()
    ap.parse_args()
    prof = pd.read_csv(os.path.join(config.REPO_DIR, "mappings", "modality_profile.csv"), dtype=str).set_index("modality_group").loc[config.DATASET]
    io0, io1 = int(prof.io_id_base), int(prof.io_id_base) + 99_999_999
    f0, f1 = int(prof.feature_id_base), int(prof.feature_id_base) + 99_999_999
    m0, m1 = int(prof.measurement_id_base), int(prof.measurement_id_base) + 99_999_999
    E, C = config.ETL_SCHEMA, config.CDM_SCHEMA
    cur = psycopg2.connect(config.dsn()).cursor()

    def one(sql):
        cur.execute(sql)
        return cur.fetchall()

    cur.execute(f"""CREATE TEMP TABLE pub_io AS SELECT * FROM {C}.image_occurrence o WHERE image_occurrence_id BETWEEN {io0} AND {io1}
                    AND EXISTS (SELECT 1 FROM {E}.cdm_image_occurrence n WHERE n.image_study_uid = o.image_study_uid AND n.image_series_uid = o.image_series_uid)""")
    # measurement rows of each side with their occurrence key and image_feature columns
    cur.execute(f"""CREATE TEMP TABLE pub_m AS SELECT o.image_study_uid su, o.image_series_uid se, f.image_feature_value_order vo,
                    f.image_feature_type_concept_id ft, f.image_finding_concept_id fi, f.anatomic_site_concept_id site, f.image_instance_uid iu,
                    m.visit_occurrence_id vis, {', '.join('m.' + c.strip() for c in MEAS.split(','))}
                    FROM pub_io o JOIN {C}.image_feature f ON f.image_occurrence_id = o.image_occurrence_id AND f.image_feature_event_field_concept_id = 1147330
                    JOIN {C}.measurement m ON m.measurement_id = f.image_feature_event_id
                    WHERE f.image_feature_id BETWEEN {f0} AND {f1} AND m.measurement_id BETWEEN {m0} AND {m1}""")
    cur.execute(f"""CREATE TEMP TABLE new_m AS SELECT o.image_study_uid su, o.image_series_uid se, f.image_feature_value_order vo,
                    f.image_feature_type_concept_id ft, f.image_finding_concept_id fi, f.anatomic_site_concept_id site, f.image_instance_uid iu,
                    m.visit_occurrence_id vis, {', '.join('m.' + c.strip() for c in MEAS.split(','))}
                    FROM {E}.cdm_image_occurrence o JOIN {E}.cdm_image_feature f ON f.image_occurrence_id = o.image_occurrence_id AND f.image_feature_event_field_concept_id = 1147330
                    JOIN {E}.cdm_measurement m ON m.measurement_id = f.image_feature_event_id
                    WHERE o.image_occurrence_id BETWEEN {io0} AND {io1}""")
    all_cols = "su, se, vo, ft, fi, site, iu, vis, " + MEAS
    no_vis = all_cols.replace("vis, ", "")
    n_pub, n_new = one("SELECT (SELECT count(*) FROM pub_m), (SELECT count(*) FROM new_m)")[0]
    new_only, pub_only = one(f"SELECT (SELECT count(*) FROM (SELECT {all_cols} FROM new_m EXCEPT ALL SELECT {all_cols} FROM pub_m) x), "
                             f"(SELECT count(*) FROM (SELECT {all_cols} FROM pub_m EXCEPT ALL SELECT {all_cols} FROM new_m) x)")[0]
    new_only_nv = one(f"SELECT count(*) FROM (SELECT {no_vis} FROM new_m EXCEPT ALL SELECT {no_vis} FROM pub_m) x")[0][0]
    print(f"[{config.DATASET}] measurement+image_feature rows: published={n_pub} new={n_new}")
    print(f"  rows differing in any column            : new-only={new_only} published-only={pub_only}")
    print(f"  rows differing besides visit_occurrence : {new_only_nv}   <- 0 means content is fully reproduced")

    r = one(f"""SELECT count(*), count(b.image_occurrence_id),
        sum((a.person_id = b.person_id)::int), sum((a.image_occurrence_date = b.image_occurrence_date)::int),
        sum((a.modality_concept_id = b.modality_concept_id)::int), sum((a.anatomic_site_concept_id IS NOT DISTINCT FROM b.anatomic_site_concept_id)::int),
        sum((a.procedure_occurrence_id IS NOT DISTINCT FROM b.procedure_occurrence_id)::int), sum((a.local_path IS NOT DISTINCT FROM regexp_replace(b.local_path, '/[^/]*$', ''))::int),
        sum((a.visit_occurrence_id IS NOT DISTINCT FROM b.visit_occurrence_id)::int)
        FROM {E}.cdm_image_occurrence a LEFT JOIN pub_io b ON b.image_study_uid = a.image_study_uid AND b.image_series_uid = a.image_series_uid""")[0]
    n, matched, *eq = r
    print(f"[{config.DATASET}] image_occurrence: new={n} found in published={matched}")
    for name, v in zip(["person", "date", "modality", "anatomic_site", "procedure", "local_path(dir)", "visit"], eq):
        print(f"  {name:14s} equal {v}/{matched}")


if __name__ == "__main__":
    main()
