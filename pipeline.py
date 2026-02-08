#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional


def normalize_output_path(path: Path) -> Path:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        adjusted = path.with_suffix(".csv")
        print(
            f"[!] Output {path} là Excel. Sẽ ghi CSV ra {adjusted}.",
            file=sys.stderr,
        )
        return adjusted
    return path


OUTPUT_DIR = Path("Output")


def resolve_output_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == OUTPUT_DIR.name:
        return path
    return OUTPUT_DIR / path


def normalize_sbd(val: str) -> Optional[str]:
    digits = "".join(ch for ch in (val or "") if ch.isdigit())
    if not digits:
        return None
    if len(digits) <= 8:
        return f"{int(digits):08d}"
    return digits


def load_dob_map(path: Path) -> Dict[str, str]:
    dob_map: Dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return dob_map
        for row in reader:
            key = normalize_sbd(row.get("SBD", ""))
            if not key:
                continue
            dob = (row.get("DOB") or "").strip()
            if dob:
                dob_map[key] = dob
    return dob_map


def load_score_map(path: Path) -> Dict[str, dict]:
    score_map: Dict[str, dict] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = normalize_sbd(str(rec.get("SBD") or rec.get("Id") or ""))
            if key:
                score_map[key] = rec
    return score_map


def combine_results(main_csv: Path, dob_csv: Path, score_jsonl: Path, out_csv: Path) -> None:
    dob_map = load_dob_map(dob_csv)
    score_map = load_score_map(score_jsonl)

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with main_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV rỗng hoặc thiếu header: {main_csv}")
        base_headers = reader.fieldnames
        extra_headers = [
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
        final_headers = base_headers + [h for h in extra_headers if h not in base_headers]

        with out_csv.open("w", encoding="utf-8-sig", newline="") as out_handle:
            writer = csv.DictWriter(out_handle, fieldnames=final_headers)
            writer.writeheader()

            for row in reader:
                sbd_raw = row.get("SBD", "")
                key = normalize_sbd(sbd_raw)
                if key:
                    row["SBD"] = key

                dob = dob_map.get(key)
                if dob and not (row.get("Ngày sinh") or "").strip():
                    row["Ngày sinh"] = dob

                score = score_map.get(key, {})
                if score:
                    row["TONGDIEM"] = score.get("TONGDIEM", "")
                    for label in ("Môn A", "Môn B", "Môn C", "Môn D"):
                        subj = score.get(label)
                        if isinstance(subj, dict):
                            row[label] = subj.get("name", "")
                            row[f"{label} - Điểm"] = subj.get("score", "")

                writer.writerow({h: row.get(h, "") for h in final_headers})



def run_step(label: str, cmd: list[str]) -> None:
    rendered = " ".join(shlex.quote(part) for part in cmd)
    print(f"[>] {label}: {rendered}")
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def build_main_cmd(args: argparse.Namespace, out_csv: Path) -> list[str]:
    cmd = [
        sys.executable,
        "main.py",
        "--sbd-file",
        str(args.sbd_file),
        "--output",
        str(out_csv),
        "--chromedriver",
        str(args.chromedriver),
        "--workers",
        str(args.main_workers),
        "--chunk-size",
        str(args.main_chunk_size),
        "--throttle",
        str(args.main_throttle),
    ]
    if args.main_limit is not None:
        cmd += ["--limit", str(args.main_limit)]
    return cmd


def build_dob_cmd(args: argparse.Namespace, input_csv: Path) -> list[str]:
    cmd = [
        sys.executable,
        "dob.py",
        "--csv",
        str(input_csv),
        "--out",
        str(args.dob_out),
        "--workers",
        str(args.dob_workers),
        "--delay",
        str(args.dob_delay),
    ]
    if args.dob_headed:
        cmd.append("--headed")
    return cmd


def build_score_cmd(args: argparse.Namespace, sbd_csv: Path) -> list[str]:
    cmd = [
        sys.executable,
        "score.py",
        "--sbd-file",
        str(sbd_csv),
        "--year",
        str(args.year),
        "--out",
        str(args.score_out),
        "--out-csv",
        str(args.score_out_csv),
        "--workers",
        str(args.score_workers),
        "--chunk",
        str(args.score_chunk),
        "--sleep",
        str(args.score_sleep),
        "--timeout",
        str(args.score_timeout),
    ]
    return cmd


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run main.py -> score.py -> dob.py sequentially."
    )
    parser.add_argument("--sbd-file", type=Path, required=True, help="TXT file for main.py.")
    parser.add_argument(
        "--chromedriver", type=Path, default=Path("./chromedriver"), help="Path to chromedriver."
    )
    parser.add_argument(
        "--main-out",
        type=Path,
        default=OUTPUT_DIR / "ketqua.csv",
        help="CSV output from main.py.",
    )
    parser.add_argument("--main-limit", type=int, default=None, help="Limit SBDs for main.py.")
    parser.add_argument("--main-workers", type=int, default=1, help="Workers for main.py.")
    parser.add_argument("--main-chunk-size", type=int, default=100, help="Chunk size for main.py.")
    parser.add_argument("--main-throttle", type=float, default=0.3, help="Delay between queries for main.py.")

    parser.add_argument(
        "--dob-out", type=Path, default=OUTPUT_DIR / "out_dob", help="Output folder for dob.py."
    )
    parser.add_argument("--dob-workers", type=int, default=4, help="Workers for dob.py.")
    parser.add_argument("--dob-delay", type=float, default=0.6, help="Delay between queries for dob.py.")
    parser.add_argument("--dob-headed", action="store_true", help="Show Chrome windows for dob.py.")

    parser.add_argument("--year", type=int, required=True, help="Exam year for score.py.")
    parser.add_argument(
        "--score-out",
        type=Path,
        default=OUTPUT_DIR / "out_score" / "out_scores.jsonl",
        help="NDJSON output for score.py.",
    )
    parser.add_argument(
        "--score-out-csv",
        type=Path,
        default=OUTPUT_DIR / "out_score" / "out_scores.csv",
        help="CSV output for score.py (used by dob.py).",
    )
    parser.add_argument("--score-workers", type=int, default=32, help="Workers for score.py.")
    parser.add_argument("--score-chunk", type=int, default=200, help="Partition size for score.py.")
    parser.add_argument("--score-sleep", type=float, default=0.0, help="Sleep seconds for score.py.")
    parser.add_argument("--score-timeout", type=float, default=10.0, help="Timeout seconds for score.py.")
    parser.add_argument(
        "--final-out",
        type=Path,
        default=OUTPUT_DIR / "final_result.csv",
        help="Final combined CSV.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    if not args.sbd_file.exists():
        print(f"[!] Không tìm thấy file {args.sbd_file}", file=sys.stderr)
        return 1
    if not args.chromedriver.exists():
        print(f"[!] Không tìm thấy chromedriver tại {args.chromedriver}", file=sys.stderr)
        return 1

    main_out = resolve_output_path(normalize_output_path(args.main_out))
    args.dob_out = resolve_output_path(args.dob_out)
    args.score_out = resolve_output_path(args.score_out)
    args.score_out_csv = resolve_output_path(args.score_out_csv)
    args.final_out = resolve_output_path(args.final_out)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    run_step("main.py", build_main_cmd(args, main_out))

    run_step("score.py", build_score_cmd(args, main_out))
    if not args.score_out.exists():
        print(f"[!] Không tìm thấy {args.score_out} sau khi chạy score.py", file=sys.stderr)
        return 1
    if not args.score_out_csv.exists():
        print(f"[!] Không tìm thấy {args.score_out_csv} sau khi chạy score.py", file=sys.stderr)
        return 1

    run_step("dob.py", build_dob_cmd(args, args.score_out_csv))
    dob_csv = args.dob_out / "dob_results.csv"
    if not dob_csv.exists():
        print(f"[!] Không tìm thấy {dob_csv} sau khi chạy dob.py", file=sys.stderr)
        return 1

    combine_results(main_out, dob_csv, args.score_out, args.final_out)
    print(f"[✓] Đã tạo {args.final_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
