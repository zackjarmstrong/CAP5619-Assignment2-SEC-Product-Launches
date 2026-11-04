# Finding product launches in SEC filings

For CAP5619 Assignment 2, I built a Python workflow that uses a large language model to find new product announcements in SEC Form 8-K filings and turn them into a structured dataset. The final CSV contains **100 products from 62 companies**. The saved analysis logs cover **187 filings analyzed with an LLM**.

## How it works

I searched SEC filings for launch and availability phrases, then used Python `requests` and BeautifulSoup to retrieve and clean the filings and their attached press releases, often EX-99 exhibits. A screening step ranked likely launch announcements so the LLM could focus on relevant documents.

The extraction step used OpenAI's Responses API with `gpt-6-luna`. The LLM identified company names as ORGANIZATION entities and newly announced products as PRODUCT entities, then returned structured JSON with the required fields and supporting quotes. This was inference; I did not train a separate entity-recognition model or fine-tune the LLM.

Python checked field types, description lengths, supporting quotes, and duplicate product names. Filing timestamps came from SEC metadata. AI-assisted source review checked whether each announcement described a current launch rather than an older product, future plan, or unrelated corporate event. The `source_checked` label records that AI-assisted review; it does not mean every entry was independently verified by a person.

The final file, `products_final.csv`, has five columns:

```text
company_name,stock_name,filing_time,new_product,product_description
```

Descriptions are shorter than 180 characters; the longest is 169. Nine uncertain candidates and 26 rejected candidates were left out. The API request ledger contains 153 requests, and collection stopped when the 100-product target was reached.

## Main files

| File | Purpose |
| --- | --- |
| `run_pipeline.py` | Main command-line workflow |
| `assignment2.py` | SEC retrieval, extraction schema, field checks, and duplicate detection |
| `screen_launch_candidates.py`, `sec_launch_discovery.py`, `analyze_launch_candidates.py` | Screening, discovery, and extraction helpers |
| `pipeline_store.py` | Saved results, request accounting, and recovery safeguards |
| `products_final.csv` | Final 100-product dataset |
| `output/pdf/methodology_report.pdf` | Approved two-page methodology report |
| `METHODOLOGY.md`, `build_report.py` | Editable report text and offline PDF builder |
| `product_evidence.csv`, `review_decisions.csv`, `audit/sources/` | Source references, review decisions, and 115 SEC source packets |
| `human_review_queue.csv` | Uncertain candidates excluded from the final dataset |
| `audit/validation_summary.json`, `audit/api_requests.json` | Validation results and API request ledger |
| `tests/` | Offline tests for validation, source checks, recovery, and spending safeguards |
| `build_submission.py`, `publication_manifest.json` | ZIP builder and list of files to include |
| `submission.zip`, `submission.zip.sha256`, `submission_verification.json` | Final package, checksum, and package verification results |

Other CSVs are intermediate results or review checkpoints. Use `products_final.csv` for the completed assignment.

## Install and run

Use Python 3.13. These commands are for PowerShell:

```powershell
git clone https://github.com/zackjarmstrong/CAP5619-Assignment2-SEC-Product-Launches.git
cd CAP5619-Assignment2-SEC-Product-Launches
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-report.txt
```

From the repository folder, inspect the current plan, run the tests, validate the saved results, and rebuild the submission package:

```powershell
.\.venv\Scripts\python.exe -B run_pipeline.py --mode plan
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B run_pipeline.py --mode validate
.\.venv\Scripts\python.exe -B build_submission.py
```

Installation needs internet access unless the dependencies are already available. The four commands above run offline and need no API key. Plan mode is read-only. Validation can refresh saved checkpoints and the validation timestamp, but the final CSV and request ledger must retain their checksums. The package builder checks those frozen checksums and creates `MANIFEST_SHA256.json` inside the ZIP, plus a checksum for the ZIP itself.

The approved PDF is already included. If you edit the report text, rebuild it with:

```powershell
.\.venv\Scripts\python.exe -B build_report.py
```

The builder reads `METHODOLOGY.md` without rewriting it. A rebuild preserves the report text and two-page section split, but may change typography and PDF bytes. Review the PDF and rebuild the ZIP after any report changes.

No new collection is needed to use or validate these results. Discovery and screening modes access the SEC, and analysis modes can make paid OpenAI requests. The code retains a cumulative request ceiling of 180, counts failed attempts, disables automatic SDK retries, and stops paid analysis once 100 reviewed products are available. These safeguards remain in place; the offline commands do not use the remaining allowance.

## Limitations and AI assistance

This is a selected sample, not a complete inventory of public-company product launches. Searches and screening may miss announcements, and an issuer's press release does not independently establish a product's performance. I did not measure precision or recall against a labeled benchmark.

The Genius/VERSES AI entry retains `VRSSD` because the historical SEC exhibits contain conflicting ticker information. The uncertainty is documented in `audit/genius_ticker_review.json`.

I used ChatGPT/Codex to help develop and test the Python code, review entries against SEC sources, and draft and revise the documentation. Source review was AI-assisted, as described above.
