#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Multi-threaded Selenium crawler that:
- Reads SBDs from a CSV
- Normalizes each SBD to 8 digits
- Queries the HCMUS results page
- Extracts DOB (Ngày sinh) from the hidden `notice_html` of accepted rows
- Saves a single CSV: dob_results.csv (columns: SBD, DOB)

Run:
  python dob_crawler_selenium_mt.py --csv hcmus.csv --out out_dir --workers 4 --headed
"""

import argparse, os, re, time, json
import pandas as pd
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

BASE_URL = "https://tsdh.hcmus.edu.vn/ketqua-xettuyen"
OUTPUT_DIR = "Output"

# ---------- Helpers ----------
def slug_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")

def normalize_sbd(val) -> Optional[str]:
    if pd.isna(val):
        return None
    s = str(val).strip()
    s = re.sub(r"\.0+$", "", s)        # "2002745.0" -> "2002745"
    s = slug_digits(s)                  # keep digits only
    if not s:
        return None
    if len(s) > 8:
        return None                     # too long to be SBD, likely CCCD
    return s.zfill(8)

def read_sbd_list(csv_path: str) -> List[str]:
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    if "SBD" not in df.columns:
        raise KeyError("CSV must contain column 'SBD'.")
    sbd = (df["SBD"].dropna().astype(str)
           .map(normalize_sbd)
           .dropna()
           .unique()
           .tolist())
    return list(sbd)

def setup_driver(headless: bool = True) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,1600")
    opts.add_argument("--lang=vi-VN")
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
    drv = webdriver.Chrome(options=opts)
    drv.set_page_load_timeout(45)
    return drv

DOB_REGEX = re.compile(r"Ngày\s*sinh:\s*<strong>\s*([\d]{1,2}/[\d]{1,2}/[\d]{4})\s*</strong>", re.IGNORECASE)

def extract_dob_from_notice_html(html_fragment: str) -> Optional[str]:
    m = DOB_REGEX.search(html_fragment)
    return m.group(1) if m else None

def query_and_get_dob(driver: webdriver.Chrome, wait: WebDriverWait, sbd: str) -> Optional[str]:
    """
    Returns the first DOB found (string like '29/11/2007') for this SBD,
    or None if nothing printable / no DOB present.
    """
    driver.get(BASE_URL)
    q = wait.until(EC.presence_of_element_located((By.ID, "Query")))
    q.clear()
    q.send_keys(sbd)

    driver.find_element(By.CSS_SELECTOR, "input[type='submit'], input.btn.btn-primary").click()
    # Wait for any table row (the results)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table tr")))
    time.sleep(0.2)

    # Look for hidden notice_html inputs (they only exist for rows that have the print icon)
    rows = driver.find_elements(By.CSS_SELECTOR, "table tr")
    for tr in rows:
        try:
            notice = tr.find_element(By.CSS_SELECTOR, "input[name='notice_html']")
        except Exception:
            continue
        html_fragment = notice.get_attribute("value") or ""
        if not html_fragment.strip():
            continue
        dob = extract_dob_from_notice_html(html_fragment)
        if dob:
            return dob
    return None

# ---------- Thread Worker ----------
def worker_chunk(sbd_chunk: List[str], headless: bool, delay: float) -> List[Tuple[str, Optional[str]]]:
    """
    Each worker creates its own driver, processes a chunk of SBDs, then quits.
    Returns list of (SBD, DOB_or_None)
    """
    results: List[Tuple[str, Optional[str]]] = []
    driver = setup_driver(headless=headless)
    wait = WebDriverWait(driver, 25)
    try:
        for sbd in sbd_chunk:
            try:
                dob = query_and_get_dob(driver, wait, sbd)
                results.append((sbd, dob))
                print(f"[{sbd}] DOB: {dob or '—'}")
            except Exception as e:
                print(f"[{sbd}] ERROR: {e}")
                results.append((sbd, None))
            time.sleep(delay)  # politeness
    finally:
        driver.quit()
    return results

# ---------- Main ----------
def chunkify(lst: List[str], n: int) -> List[List[str]]:
    """Split list into n approximately-equal chunks (n >= 1)."""
    n = max(1, n)
    k, m = divmod(len(lst), n)
    return [lst[i*k + min(i, m):(i+1)*k + min(i+1, m)] for i in range(n)]

def main():
    ap = argparse.ArgumentParser(description="Multi-threaded DOB crawler (Selenium).")
    ap.add_argument("--csv", required=True, help="Path to CSV having 'SBD' column.")
    ap.add_argument(
        "--out", default=os.path.join(OUTPUT_DIR, "out_dob"), help="Output folder (default: Output/out_dob)"
    )
    ap.add_argument("--workers", type=int, default=4, help="Number of threads (each runs its own Chrome).")
    ap.add_argument("--headed", action="store_true", help="Show Chrome windows (default headless).")
    ap.add_argument("--delay", type=float, default=0.6, help="Delay between requests per thread (sec).")
    args = ap.parse_args()

    if (
        not os.path.isabs(args.out)
        and args.out != OUTPUT_DIR
        and not args.out.startswith(f"{OUTPUT_DIR}{os.sep}")
    ):
        args.out = os.path.join(OUTPUT_DIR, args.out)
    os.makedirs(args.out, exist_ok=True)
    sbd_list = read_sbd_list(args.csv)
    print(f"Loaded {len(sbd_list)} SBDs")

    # Split SBDs into as many chunks as workers
    chunks = chunkify(sbd_list, args.workers)

    all_results: List[Tuple[str, Optional[str]]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(worker_chunk, ch, not args.headed, args.delay) for ch in chunks]
        for fut in as_completed(futures):
            all_results.extend(fut.result())

    # Save CSV: one row per SBD
    out_csv = os.path.join(args.out, "dob_results.csv")
    pd.DataFrame(all_results, columns=["SBD", "DOB"]).to_csv(out_csv, index=False, encoding="utf-8")
    print(f"\nSaved DOBs → {out_csv}")

    # Also save JSON summary
    out_json = os.path.join(args.out, "dob_results.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump([{"SBD": s, "DOB": d} for s, d in all_results], f, ensure_ascii=False, indent=2)
    print(f"Saved JSON  → {out_json}")

if __name__ == "__main__":
    main()
