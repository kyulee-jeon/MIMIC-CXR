"""Bronze (DICOM) -> silver (parquet) with third_party/dicom_to_parquet.

dicom_to_parquet.py is a single-process tool that writes  <out_dir>/modality=<DICOM Modality>/tag=<8 hex>/part-b<N>-<i>.parquet
with columns  file_path, study_uid, series_uid, instance_uid, sop_class_uid, modality, tag, vr, vm, path, value
(path = nested-sequence trail such as 54000100[0]/003A0200[3]/003A0203[0]/ ; multi-valued tags are one row per value).

This wrapper only adds what a 1M-file run needs:
  * one dicom_to_parquet process per top-level sub-folder (p10, p1000 ...), N in parallel
  * each process writes to a private temp dir, results are then moved into the shared silver dir with a
    sub-folder-unique file name (dicom_to_parquet's own names part-b0-0.parquet would collide / be overwritten)
  * resumable: finished sub-folders are recorded in <silver>/_done/ and skipped on re-run
MIMIC-ECG and MIMIC-CXR write to the same silver dir when SILVER_DIR is shared (they differ by the modality partition).

    python extract/build_silver.py --workers 16
    python extract/build_silver.py --workers 2 --limit_dirs 1 --max_files 100     # smoke test
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

TOOL = os.path.join(config.REPO_DIR, "third_party", "dicom_to_parquet", "dicom_to_parquet.py")
SOURCE = config.DATASET


def run_one(root, sub, silver, max_files):
    done = os.path.join(silver, "_done", f"{SOURCE}_{sub}.json")
    if os.path.exists(done):
        return sub, "skipped", 0
    tmp = os.path.join(silver, "_tmp", f"{SOURCE}_{sub}")
    shutil.rmtree(tmp, ignore_errors=True)
    cmd = [sys.executable, TOOL, "--dicom_root", os.path.join(root, sub), "--out_dir", tmp,
           "--skip_pixel_data", "--verbose_every", "0"]
    if max_files:
        cmd += ["--max_files", str(max_files)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return sub, "FAILED: " + r.stderr[-300:], 0
    n = 0
    for dp, _, fns in os.walk(tmp):
        for fn in fns:
            if not fn.endswith(".parquet"):
                continue
            rel = os.path.relpath(dp, tmp)  # modality=X/tag=Y
            dst_dir = os.path.join(silver, rel)
            os.makedirs(dst_dir, exist_ok=True)
            shutil.move(os.path.join(dp, fn), os.path.join(dst_dir, f"part-{SOURCE}-{sub}-{fn[5:]}"))
            n += 1
    summ = os.path.join(tmp, "_build_summary.json")
    os.makedirs(os.path.dirname(done), exist_ok=True)
    if os.path.exists(summ):
        shutil.copy(summ, done)
    else:
        with open(done, "w") as fh:
            json.dump({}, fh)
    shutil.rmtree(tmp, ignore_errors=True)
    return sub, "ok", n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dicom_dir", help="folder that holds the DICOM files (or env DICOM_DIR); the same value goes to run_etl.py --dicom_dir")
    ap.add_argument("--silver", default=config.SILVER_DIR)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit_dirs", type=int, help="first N sub-folders only (smoke test)")
    ap.add_argument("--max_files", type=int, help="per sub-folder file limit (smoke test)")
    a = ap.parse_args()
    root = a.dicom_dir or config.DICOM_DIR
    if not root:
        sys.exit("DICOM source folder missing: pass --dicom_dir <folder> or set env DICOM_DIR")
    subs = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    if a.limit_dirs:
        subs = subs[:a.limit_dirs]
    os.makedirs(a.silver, exist_ok=True)
    print(f"{SOURCE}: {len(subs)} sub-folders under {root} -> {a.silver}", flush=True)
    bad = 0
    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(run_one, root, s, a.silver, a.max_files) for s in subs]
        for i, f in enumerate(as_completed(futs), 1):
            sub, status, n = f.result()
            bad += status.startswith("FAILED")
            print(f"[{i}/{len(subs)}] {sub}: {status} ({n} files moved)", flush=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
