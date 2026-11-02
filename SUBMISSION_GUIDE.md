# Submission guide

Public repository: https://github.com/zackjarmstrong/CAP5619-Assignment2-SEC-Product-Launches

| Purpose | File |
| --- | --- |
| Final 100-product, five-column dataset | `products_final.csv` |
| Two-page methodology report | `output/pdf/methodology_report.pdf` |
| Editable report text | `METHODOLOGY.md` |
| Main Python workflow and dependencies | `run_pipeline.py`, `requirements.txt` |
| Report/package reproduction | `build_report.py`, `requirements-report.txt`, `build_submission.py` |
| Product source evidence and decisions | `product_evidence.csv`, `review_decisions.csv`, `audit/sources/` |
| Excluded uncertain cases | `human_review_queue.csv` |
| Counts, tests, and current integrity checks | `audit/validation_summary.json`, `audit/offline_test_results.txt`, `audit/final_integrity_checks.json`, `audit/publication_validation.json` |
| Historical Genius ticker review | `audit/genius_ticker_review.json` |
| Explicit publication allowlist | `publication_manifest.json` |
| Package checksum and verification | `submission.zip.sha256`, `submission_verification.json` |

Both targets are met: **100 source-checked products from 62 companies and 187 LLM-analyzed filings**. The ledger retains 153 requests. No new OpenAI calls were made for publication. The final dataset is byte-for-byte unchanged. There are 26 rejected and nine uncertain candidates, all excluded.

The uncertain cases are HybriU Partner Portal (AMBO), RELI Exchange 2.0 (EZRA), InSet I-135RFX (SI), the on-premises Advantage offering (QBTS), kBMS (KULR), NeuCool HyperStart (INV), GENA (AIRE), EARSON (GMTH), and the 50+ qubit platform (QXL). None is needed to meet 100.

The public export includes the supported pipeline, 31 applicable offline tests, current checkpoints, request/authorization history, 115 SEC source packets, and the 73-row baseline used by offline validation. Supporting CSVs are workflow checkpoints, not alternative final datasets. Complete raw responses, crash-recovery journals, older baselines, and development history remain in a separate private archive. The public files support offline validation but cannot replay the original private response archive. Course handouts, slides, notebooks, transcripts, credentials, and prior Git objects are not redistributed.

NER uses the LLM to identify company names as ORGANIZATION entities and products as PRODUCT entities and return structured fields. No separate NER model was trained. Engineering safeguards are additional implementation decisions. The written handout does not require W&B, and none is included.

Genius retains VRSSD with historical uncertainty documented in `audit/genius_ticker_review.json`; no current ticker was substituted for the historical evidence. Source checks were AI-assisted, not independently performed by a human. Issuer clinical/performance claims are not independent validation. Review these limitations and the disclosed AI assistance before submission.

Add https://github.com/zackjarmstrong/CAP5619-Assignment2-SEC-Product-Launches to the top of the student's CV, review the report and dataset, and upload the requested deliverables through the course system. Submit `products_final.csv`, not the larger candidate checkpoint.

Follow the offline reproduction commands in `README.md`. Check that the report remains two pages after regeneration. `MANIFEST_SHA256.json` inside the ZIP lists a hash for every included file. The report and ZIP have new publication hashes because the repository reference and public/private scope changed; the accepted product dataset and request ledger retain their frozen hashes.
