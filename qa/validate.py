"""QA after the cdm step.  Hard failures raise AssertionError; informational numbers are printed.

Run standalone:  python -m qa.validate
"""
import psycopg2

import config

E = config.ETL_SCHEMA


def q(cur, sql):
    cur.execute(sql.replace("@etl", E))
    return cur.fetchall()


def main(conn=None):
    own = conn is None
    conn = conn or psycopg2.connect(config.dsn())
    cur = conn.cursor()
    fails = []

    def check(name, ok, detail=""):
        print(f"  {'PASS' if ok else 'FAIL'}  {name} {detail}")
        if not ok:
            fails.append(name)

    n_io, = q(cur, "SELECT count(*) FROM @etl.cdm_image_occurrence")[0]
    n_if, = q(cur, "SELECT count(*) FROM @etl.cdm_image_feature")[0]
    n_m, = q(cur, "SELECT count(*) FROM @etl.cdm_measurement")[0]
    print(f"  rows: image_occurrence={n_io} image_feature={n_if} measurement={n_m}")
    check("image_feature = measurement", n_if == n_m)

    check("ids unique (io/feature/measurement)", all(
        q(cur, f"SELECT count(*) = count(DISTINCT {c}) FROM @etl.{t}")[0][0]
        for t, c in [("cdm_image_occurrence", "image_occurrence_id"), ("cdm_image_feature", "image_feature_id"),
                     ("cdm_measurement", "measurement_id")]))
    check("one (study, series) per image_occurrence",
          q(cur, "SELECT count(*) = count(DISTINCT (image_study_uid, image_series_uid)) FROM @etl.cdm_image_occurrence")[0][0])
    check("image_feature -> image_occurrence has no orphan",
          q(cur, "SELECT count(*) FROM @etl.cdm_image_feature f LEFT JOIN @etl.cdm_image_occurrence o USING (image_occurrence_id) "
                 "WHERE o.image_occurrence_id IS NULL")[0][0] == 0)
    check("image_feature_event_id -> measurement has no orphan", q(cur, """
        SELECT count(*) FROM @etl.cdm_image_feature f
        LEFT JOIN @etl.cdm_measurement m ON f.image_feature_event_field_concept_id = 1147330 AND m.measurement_id = f.image_feature_event_id
        WHERE m.measurement_id IS NULL""")[0][0] == 0)
    check("measurement person agrees with image_occurrence; date = its instance StudyDate", q(cur, """
        SELECT count(*) FROM @etl.cdm_image_feature f
        JOIN @etl.cdm_measurement m ON f.image_feature_event_field_concept_id = 1147330 AND m.measurement_id = f.image_feature_event_id
        JOIN @etl.cdm_image_occurrence o USING (image_occurrence_id)
        LEFT JOIN @etl.lk_img_file_clean fc ON fc.instance_uid = f.image_instance_uid
        WHERE m.person_id <> o.person_id
           OR m.measurement_date <> COALESCE(fc.image_date, o.image_occurrence_date)""")[0][0] == 0)
    check("image_feature_concept_id = measurement_concept_id", q(cur, """
        SELECT count(*) FROM @etl.cdm_image_feature f JOIN @etl.cdm_measurement m
          ON f.image_feature_event_field_concept_id = 1147330 AND m.measurement_id = f.image_feature_event_id
        WHERE m.measurement_concept_id <> f.image_feature_concept_id""")[0][0] == 0)

    print("  --- mapping review list (lk_img_unmapped) ---")
    for r in q(cur, "SELECT kind, modality_group, tag, source_code, n_rows, target_concept_id, in_vocab FROM @etl.lk_img_unmapped "
                    "ORDER BY n_rows DESC LIMIT 30"):
        print("   ", r)
    print("  --- visit link: rule that decided the visit of each image_occurrence ---")
    tot = q(cur, "SELECT count(*) FROM @etl.lk_img_occurrence_mapped")[0][0]
    L = q(cur, """SELECT count(*), count(*) FILTER (WHERE rule = 'stay_datetime'), count(*) FILTER (WHERE rule = 'clinic_date'),
                         count(*) FILTER (WHERE n_stay >= 2), count(*) FILTER (WHERE rule = 'clinic_date' AND n_clinic >= 2)
                  FROM @etl.lk_img_visit_link""")[0]
    linked, by_stay, by_clinic, stay_multi, clinic_multi = L
    print(f"    image_occurrence total {tot}: no visit {tot - linked}, stay by datetime {by_stay}, clinic by date {by_clinic}")
    print(f"    ties resolved by earliest start / lowest id: stay {stay_multi} (>=2 stays contain the datetime), clinic {clinic_multi} (>=2 clinic records that day)")
    print("  --- link coverage (occurrences, with visit, with procedure) ---")
    for r in q(cur, """SELECT count(*), count(visit_occurrence_id) visit, count(procedure_occurrence_id) proc FROM @etl.cdm_image_occurrence"""):
        print("   ", r)

    if own:
        conn.close()
    assert not fails, f"QA failed: {fails}"


if __name__ == "__main__":
    main()
