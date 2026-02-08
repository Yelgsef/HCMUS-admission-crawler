# HCMUS Admission Crawler

Tools to collect HCMUS admission results, exam scores, and DOBs. All outputs go to `Output/` by default.

**Scripts**
- `main.py`: Crawl admission results from the HCMUS results page and write `Output/ketqua.csv`.
- `score.py`: Crawl THPT exam scores from the Tuổi Trẻ API and write `Output/out_score/` (NDJSON, JSON, CSV).
- `dob.py`: Crawl date of birth (DOB) by parsing hidden notice HTML and write `Output/out_dob/` (CSV, JSON).
- `pipeline.py`: Run `main.py → score.py → dob.py` and combine everything into `Output/final_result.csv`.

**Requirements**
- Python 3.9+
- Google Chrome or Chromium
- ChromeDriver that matches your Chrome version (use bundled `chromedriver` or your own)

**Install**
```bash
pip install -r requirements.txt
```

**Quick Start**
```bash
python pipeline.py \
  --sbd-file Input/sample.txt \
  --chromedriver ./chromedriver \
  --main-limit 50 \
  --year 2025
```

## Usage

### 1) Admission results (main.py)
```bash
python main.py \
  --sbd-file sbd.txt \
  --output Output/ketqua.csv \
  --chromedriver ./chromedriver \
  --limit 50 \
  --workers 1 \
  --chunk-size 100 \
  --throttle 0.3
```
Notes:
- `--sbd-file` is a plain text file with one SBD per line.
- Increase `--workers` to run in parallel (each worker opens a Chrome instance).

### 2) Exam scores (score.py)
`score.py` can read the CSV from `main.py` directly.
```bash
python score.py \
  --sbd-file Output/ketqua.csv \
  --year 2025 \
  --out Output/out_score/out_2025.jsonl
```
Outputs:
- `Output/out_score/out_2025.jsonl` (NDJSON)
- `Output/out_score/out_2025.json` (JSON array)
- `Output/out_score/out_scores.csv` (CSV)

### 3) DOBs (dob.py)
`dob.py` expects a CSV with an `SBD` column (the CSV from `score.py` is supported).
```bash
python dob.py \
  --csv Output/out_score/out_scores.csv \
  --out Output/out_dob \
  --workers 4
```
Add `--headed` to show browser windows.

### 4) Full pipeline (main → score → dob)
```bash
python pipeline.py \
  --sbd-file Input/sample.txt \
  --chromedriver ./chromedriver \
  --main-limit 50 \
  --main-workers 1 \
  --main-chunk-size 100 \
  --main-throttle 0.3 \
  --score-out Output/out_score/out_2025.jsonl \
  --score-out-csv Output/out_score/out_scores.csv \
  --score-workers 32 \
  --score-chunk 200 \
  --score-sleep 0.0 \
  --score-timeout 10.0 \
  --dob-workers 4 \
  --dob-delay 0.6 \
  --year 2025 \
  --final-out Output/final_result.csv
```
Notes:
- `pipeline.py` feeds `Output/ketqua.csv` into `score.py`, then feeds `Output/out_score/out_scores.csv` into `dob.py`.
- The combined output is `Output/final_result.csv`.

## Output Columns (main.py)
`main.py` writes the following columns in order:
`MSSV`, `Họ và tên`, `Ngày sinh`, `SBD`, `CCCD`, `Nv`, `Ngành/Nhóm ngành`, `PTXT`, `Kết quả xét tuyển`, `Ghi chú`.

## Tips
- Start with a small `--limit` to validate setup.
- Use a reasonable `--throttle` to avoid rate limits or temporary blocks.
