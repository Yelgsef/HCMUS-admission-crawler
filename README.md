# HCMUS Admission Crawler

Python crawlers to collect admission results from HCMUS (tsdh.hcmus.edu.vn) and related exam data. The main script uses headless Selenium to look up SBDs and export an Excel file in the required format.

## What’s in this repo
- `main.py`: Crawl admission results from the HCMUS results page and write `ketqua.xlsx` (or a custom output path). Empty “Kết quả xét tuyển” is written as `XXXX`.
- `dob.py`: Crawl date of birth (DOB) for accepted rows by parsing hidden notice HTML and export CSV/JSON.
- `crawl.py`: Crawl THPT exam scores from the Tuổi Trẻ API and export NDJSON + JSON.
- `chromedriver`: Bundled ChromeDriver (Linux x86_64). Use your own if needed.

## Prerequisites
- Python 3.9+
- Google Chrome or Chromium
- ChromeDriver that matches your Chrome version (use the bundled `chromedriver` or download a compatible one)

## Install dependencies
```bash
pip install -r requirements.txt
```

## Usage

### 1) Crawl admission results (main)
```bash
python main.py \
  --sbd-file sample.txt \
  --output ketqua.xlsx \
  --chromedriver ./chromedriver \
  --limit 50 \
  --workers 1 \
  --chunk-size 100 \
  --throttle 0.3
```
Notes:
- `--sbd-file` expects a plain text file with one SBD per line.
- Increase `--workers` to run in parallel (each worker opens a Chrome instance).

### 2) Crawl DOBs (dob.py)
Prepare a CSV with a `SBD` column (export from Excel if needed), then:
```bash
python dob.py --csv path/to/sbd.csv --out out_dob --workers 4
```
Add `--headed` to show browser windows.

### 3) Crawl THPT scores (crawl.py)
```bash
python crawl.py --sbd-file sample.txt --year 2025 --out out_2025.jsonl
```
This writes:
- `out_2025.jsonl` (NDJSON)
- `out_2025.json` (JSON array)

## Output format (main.py)
`main.py` writes the following columns in order:
`MSSV`, `Họ và tên`, `Giới tính`, `Ngày sinh`, `SBD`, `CCCD`, `Quê quán`, `Nv`, `Ngành/Nhóm ngành`, `PTXT`, `Kết quả xét tuyển`, `Ghi chú`.

## Tips
- Start with `sample.txt` and a small `--limit` to validate setup.
- Use a reasonable `--throttle` to avoid rate limits or temporary blocks.
