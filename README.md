# CAP5619 Assignment 2: SEC product-launch analysis

Python analysis of original product launches in SEC Form 8-K filings using LLM inference and source review.

Repository: [CAP5619-Assignment2-SEC-Product-Launches](https://github.com/zackjarmstrong/CAP5619-Assignment2-SEC-Product-Launches)

## Completed results

The final dataset contains **100 source-checked products from 62 companies**, supported by 85 product-source filings. Preserved logs record **187 successfully LLM-analyzed filings**. Of 135 candidate products, 26 were rejected and nine remain uncertain; both groups are excluded. The request ledger contains **153 completed requests**, with a historical ceiling of 180. Collection stopped at the 100-product target. This publication used no additional OpenAI requests.

`source_checked` means an AI assistant inspected the SEC source and recorded a decision; it is not independent human verification. Issuer efficacy and performance statements are not independently validated. The sample is purposive and does not establish exhaustive originality, precision, or recall.

## Deliverables

- `products_final.csv`: the sole final dataset, with exactly `company_name,stock_name,filing_time,new_product,product_description`; descriptions contain fewer than 180 characters.
- `output/pdf/methodology_report.pdf`: two-page methodology and actual results; `METHODOLOGY.md` is its editable text.
- `submission.zip`: supported source, dependencies, dataset, report, tests, and evidence, with `MANIFEST_SHA256.json` inside.
- `submission.zip.sha256` and `submission_verification.json`: package checksum and verification results.
- `product_evidence.csv`, `review_decisions.csv`, and `audit/sources/`: product provenance, review status, and 115 public SEC source packets.
- `human_review_queue.csv`: excluded uncertain cases; `products_batch_test.csv` is a candidate checkpoint, not another final dataset.
- `publication_manifest.json`: the explicit public-file allowlist and frozen dataset/ledger checksums.
- `SUBMISSION_GUIDE.md`: artifact map and remaining personal submission steps.

## Offline reproduction

Use Python 3.13 from this repository folder. No credentials, SEC requests, or OpenAI calls are needed for these commands:

```powershell
python -m pip install -r requirements.txt -r requirements-report.txt
python -B -m unittest discover -s tests -v
python -B run_pipeline.py --mode validate
python -B build_report.py
python -B build_submission.py
```

Dependency installation needs internet if packages are not installed; validation, tests, and artifact generation run offline. Validation may refresh materialized checkpoints and the validation timestamp, but must preserve the final CSV and request ledger checksums. The package builder checks both frozen hashes before writing a new ZIP. It records SHA-256 hashes for every included file. Regeneration changes report/package hashes and requires a fresh visual review of the PDF and verification of the ZIP. Git attributes preserve file bytes across checkouts.

The 31 included tests cover validation, grounding, deduplication, recovery behavior using synthetic fixtures, request limits, locks, and stopping at the reviewed goal. Legacy experimental scripts and their separate entry-point test are not exported. This repository begins with a new initial commit; no prior Git objects, private course materials, recovery bundles, or personal commit metadata were imported.

## Method and course alignment

The written Assignment 2 handout and course examples were reviewed privately and are not redistributed. The course approach is Python SEC text collection, contextual prompting, Named Entity Recognition (NER), and structured extraction. The LLM identifies company names as ORGANIZATION entities and newly announced products as PRODUCT entities, then returns `company_name` and `new_product` within structured fields. These are semantic roles, not separately emitted BIO tags. No separate NER model was trained. Issuer names are normalized to SEC metadata. API inference is permitted by the handout; local Ollama examples illustrate another execution method.

The configured historical extraction model is `gpt-6-luna`, using strict JSON Schema and a 179-character description limit. Prompts request literal evidence, a source URL, date, confidence, and rationale, and exclude historical recaps, future plans, financing, rebrands, and channel expansions. Python supplies SEC acceptance timestamps, checks quotes against source text, and deduplicates normalized product names. Source review remains necessary even when model confidence is high.

Budget accounting, atomic recovery journals, writer locks, source hashes, preservation baselines, and package manifests are additional implementation decisions, not professor-required techniques. This is inference rather than model training. The written handout does not require Weights & Biases; none is integrated.

## Supported code and retained safeguards

- `run_pipeline.py`: primary CLI; default mode `plan` is read-only.
- `assignment2.py`: SEC retrieval, extraction schema, validation, and duplicates.
- `pipeline_store.py`: durable storage, request ledger, cumulative ceiling, and writer lock.
- `analyze_launch_candidates.py`, `screen_launch_candidates.py`, `sec_launch_discovery.py`: document discovery, screening, and discovery helpers; their CLIs delegate to the supported workflow.
- `build_report.py` and `build_submission.py`: offline artifact generators.

The 153-record request ledger and historical authorizations are retained so copying this export cannot reset request accounting. The cumulative ceiling remains 180; reservations and failures consume slots, SDK retries are disabled, and paid analysis checks the reviewed 100-product goal before credential access. These historical authorizations do not instruct readers to run new collection. Existing data and evidence are sufficient for submission. Credentials are not included; the original workflow uses `keyring` and Windows Credential Manager. No API key is needed for offline reproduction.

Complete raw model responses, recovery journals, older snapshots, and development history are preserved in a separate private archive. They are not in this public repository or ZIP. Public evidence and checkpoints support offline validation; replay of original raw-response recovery requires that private archive. Source packets reproduce public SEC issuer statements, including public business information, and are not private account data.

## Limitations and personal review

Genius retains `VRSSD` with explicit historical uncertainty. SEC exhibits support VRSSD's March 2025 adoption and April 17 use, while the April 30 launch release lists VRSSF; they do not conclusively resolve the effective symbol at the May 2 acceptance time. See `audit/genius_ticker_review.json`. No accepted product value was changed for publication.

The nine uncertain candidates remain excluded. Review the dataset, source decisions, report, and disclosed AI assistance before submission. Add the full repository URL to the top of the student's CV and upload the requested deliverables through the course system.

References: [SEC EDGAR developer resources](https://www.sec.gov/about/developer-resources), [OpenAI Python SDK](https://developers.openai.com/api/reference/python), [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses). Filing-specific source URLs are retained in the evidence CSV and source packets.
