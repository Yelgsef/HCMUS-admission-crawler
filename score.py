import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

import requests
from requests.adapters import HTTPAdapter, Retry

import dask.bag as db
from dask.diagnostics import ProgressBar


API_TEMPLATE = "https://s6.tuoitre.vn/api/diem-thi-thpt.htm"
OUTPUT_DIR = Path("Output")
SCORE_DIR = OUTPUT_DIR / "out_score"

# Map API fields -> human-friendly Vietnamese subject names
SUBJECT_NAME_MAP = {
    "TOAN": "Toán",
    "VAN": "Ngữ văn",
    "NGOAI_NGU": "Ngoại ngữ",
    "LI": "Vật lí",
    "HOA": "Hóa học",
    "SINH": "Sinh học",
    "SU": "Lịch sử",
    "DIA": "Địa lí",
    "GDKT_PL": "Kinh tế & Pháp luật",
    "GIAO_DUC_CONG_DAN": "Giáo dục công dân",
    "TIN_HOC": "Tin học",
    "CN_CONG_NGHIEP": "Công nghệ (Công nghiệp)",
    "CN_NONG_NGHIEP": "Công nghệ (Nông nghiệp)",
}

# Priority order for selecting up to 4 subjects (scores != -1)
SUBJECT_PRIORITY = [
    "TOAN",
    "VAN",
    "NGOAI_NGU",
    "LI",
    "HOA",
    "SINH",
    "SU",
    "DIA",
    "GIAO_DUC_CONG_DAN",
    "GDKT_PL",
    "TIN_HOC",
    "CN_CONG_NGHIEP",
    "CN_NONG_NGHIEP",
]

SCORE_COLUMNS = [
    "SBD",
    "TONGDIEM",
    "Môn A",
    "Môn A - Điểm",
    "Môn B",
    "Môn B - Điểm",
    "Môn C",
    "Môn C - Điểm",
    "Môn D",
    "Môn D - Điểm",
]


def build_session(max_pool: int = 64, total_retries: int = 5, backoff: float = 0.3) -> requests.Session:
    sess = requests.Session()
    retries = Retry(
        total=total_retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"])
    )
    adapter = HTTPAdapter(pool_connections=max_pool, pool_maxsize=max_pool, max_retries=retries)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; diemthi-crawler/1.1)"
    })
    return sess


def fetch_one(session: requests.Session, sbd: str, year: int, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
    params = {"sbd": sbd, "year": year}
    try:
        r = session.get(API_TEMPLATE, params=params, timeout=timeout)
        r.raise_for_status()
        payload = r.json()
    except Exception:
        return None

    if not isinstance(payload, dict) or not payload.get("success") or not payload.get("data"):
        return None

    row = payload["data"][0]
    sbd_api = str(row.get("SBD") or row.get("Id") or "")
    if sbd_api != str(sbd):
        return None
    return row


def extract_record(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "SBD": str(row.get("SBD") or row.get("Id") or ""),
        "TONGDIEM": row.get("TONGDIEM"),
    }

    subjects_available = []
    for key in SUBJECT_PRIORITY:
        score = row.get(key, -1)
        if isinstance(score, (int, float)) and score != -1:
            subjects_available.append((key, float(score)))

    top4 = subjects_available[:4]
    label_map = {1: "Môn A", 2: "Môn B", 3: "Môn C", 4: "Môn D"}

    for idx, (k, score) in enumerate(top4, start=1):
        pretty = SUBJECT_NAME_MAP.get(k, k)
        out[label_map[idx]] = {"name": pretty, "score": score}

    return out


def normalize_sbd(s: str) -> Optional[str]:
    s = "".join(ch for ch in s if ch.isdigit())
    if not s:
        return None
    # Commonly 8 digits; pad left if shorter (but keep <= 12 safeguard)
    if len(s) <= 8:
        s = f"{int(s):08d}"
    return s


def load_sbd_txt(path: str) -> List[str]:
    sbds = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            val = normalize_sbd(line.strip())
            if val:
                sbds.append(val)
    return sbds


def detect_sbd_column(headers: List[str]) -> Optional[int]:
    # Prefer headers containing 'sbd' (case-insensitive)
    for i, h in enumerate(headers):
        if "sbd" in (h or "").lower():
            return i
    return None


def score_numeric_like(value: str) -> bool:
    v = "".join(ch for ch in (value or "") if ch.isdigit())
    return v.isdigit() and 6 <= len(v) <= 12  # generous bounds


def load_sbd_csv(path: str) -> List[str]:
    sbds: List[str] = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration:
            return sbds

        idx = detect_sbd_column(headers)
        if idx is not None:
            # Directly read from chosen column
            for row in reader:
                if idx < len(row):
                    val = normalize_sbd(row[idx])
                    if val:
                        sbds.append(val)
            return sbds

        # Fallback: pick the column with MOST numeric-like values
        counts: List[int] = [0] * len(headers)
        cache_rows: List[List[str]] = []
        for row in reader:
            cache_rows.append(row)
            for i, cell in enumerate(row):
                if score_numeric_like(cell):
                    counts[i] += 1

        if not counts or max(counts) == 0:
            # Last-resort: scan all cells for numeric-like
            for row in cache_rows:
                for cell in row:
                    val = normalize_sbd(cell)
                    if val:
                        sbds.append(val)
            return sbds

        best_idx = counts.index(max(counts))
        for row in cache_rows:
            if best_idx < len(row):
                val = normalize_sbd(row[best_idx])
                if val:
                    sbds.append(val)
        return sbds


def load_sbd_file(path: str) -> List[str]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return load_sbd_csv(path)
    return load_sbd_txt(path)


def gen_sbd_range(start: int, end: int) -> List[str]:
    if end < start:
        start, end = end, start
    return [f"{i:08d}" for i in range(start, end + 1)]


def resolve_output_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == OUTPUT_DIR.name:
        return path
    return OUTPUT_DIR / path


def flatten_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "SBD": rec.get("SBD", ""),
        "TONGDIEM": rec.get("TONGDIEM", ""),
    }
    for label in ("Môn A", "Môn B", "Môn C", "Môn D"):
        subj = rec.get(label)
        if isinstance(subj, dict):
            out[label] = subj.get("name", "")
            out[f"{label} - Điểm"] = subj.get("score", "")
        else:
            out[label] = ""
            out[f"{label} - Điểm"] = ""
    return out


def main():
    parser = argparse.ArgumentParser(description="Crawl điểm thi THPT từ Tuổi Trẻ API bằng Dask.")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--sbd-file", type=str, help="Path to TXT/CSV (CSV from main.py is supported).")
    g.add_argument("--start-sbd", type=int, help="Start SBD (inclusive), integer.")
    parser.add_argument("--end-sbd", type=int, help="End SBD (inclusive), integer (required if --start-sbd is set).")
    parser.add_argument("--year", type=int, required=True, help="Exam year (e.g., 2025).")

    parser.add_argument(
        "--out",
        type=str,
        default=str(SCORE_DIR / "out_scores.jsonl"),
        help="Output NDJSON file path (default: Output/out_score/out_scores.jsonl).",
    )
    parser.add_argument(
        "--out-csv",
        type=str,
        default=str(SCORE_DIR / "out_scores.csv"),
        help="Output CSV file path (default: Output/out_score/out_scores.csv).",
    )
    parser.add_argument("--workers", type=int, default=32, help="Number of Dask threads (default: 32).")
    parser.add_argument("--chunk", type=int, default=200, help="Partition size for Dask bag (default: 200).")
    parser.add_argument("--sleep", type=float, default=0.0, help="Optional sleep seconds between requests.")
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-request timeout seconds.")

    args = parser.parse_args()

    out_path = resolve_output_path(Path(args.out))
    out_csv_path = resolve_output_path(Path(args.out_csv))

    # Build SBD list
    if args.sbd_file:
        if not os.path.exists(args.sbd_file):
            print(f"SBD file not found: {args.sbd_file}", file=sys.stderr)
            sys.exit(1)
        sbd_list = load_sbd_file(args.sbd_file)
    else:
        if args.end_sbd is None:
            parser.error("--end-sbd is required when using --start-sbd")
        sbd_list = gen_sbd_range(args.start_sbd, args.end_sbd)

    if not sbd_list:
        print("No SBDs detected from input. Please check your file/arguments.", file=sys.stderr)
        sys.exit(1)

    session = build_session(max_pool=max(64, args.workers * 2))

    def work_unit(sbd: str) -> Optional[Dict[str, Any]]:
        if args.sleep > 0:
            time.sleep(args.sleep)
        row = fetch_one(session, sbd, args.year, timeout=args.timeout)
        if not row:
            return None
        return extract_record(row)

    bag = db.from_sequence(sbd_list, partition_size=args.chunk).map(work_unit).filter(lambda x: x is not None)

    with ProgressBar():
        results: List[Dict[str, Any]] = bag.compute(num_workers=args.workers, scheduler="threads")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cnt = 0
    with out_path.open("w", encoding="utf-8") as fo:
        for rec in results:
            fo.write(json.dumps(rec, ensure_ascii=False))
            fo.write("\n")
            cnt += 1

    array_path = out_path.with_suffix(".json")
    with array_path.open("w", encoding="utf-8") as fa:
        json.dump(results, fa, ensure_ascii=False, indent=2)

    with out_csv_path.open("w", encoding="utf-8-sig", newline="") as fc:
        writer = csv.DictWriter(fc, fieldnames=SCORE_COLUMNS)
        writer.writeheader()
        for rec in results:
            writer.writerow(flatten_record(rec))

    print(f"Done. Wrote {cnt} records to:\n - {out_path}\n - {array_path}\n - {out_csv_path}")


if __name__ == "__main__":
    main()
