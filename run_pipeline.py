"""CAP5619 Assignment 2: resumable SEC 8-K product-launch pipeline.

This script reuses the SEC extraction and LLM functions from the tested
assignment2.py, with optional free screening and larger controlled API batches.
Results are candidate announcements until reviewed against original SEC filings.

Examples:
    python run_pipeline.py --mode plan
    python run_pipeline.py --mode all --max-new-screens 160 --max-api-calls 30
    python run_pipeline.py --mode analyze --max-api-calls 30 --min-score 5
"""
import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import keyring
import pandas as pd
from openai import OpenAI

from assignment2 import (
    MODEL,
    SecAccessError,
    LOG_CSV,
    PRODUCT_CSV,
    REQUIRED_FIELDS,
    extract_document_text,
    extract_products,
    get_filing_metadata,
    is_duplicate,
    validate_product,
)
from analyze_launch_candidates import get_launch_documents, ticker_from_company
from screen_launch_candidates import score_release
from pipeline_store import (
    AUTHORIZATION_LIMIT, AUDIT_DIR, atomic_json, exclusive_run, filing_id,
    finish_request, journal_path, load_json, reserve_request, request_history,
    utc_now,
    read_rows, save_rows,
)

CANDIDATES_CSV = "sec_launch_candidates.csv"
SCREEN_CSV = "sec_launch_screened.csv"
EVIDENCE_CSV = "product_evidence.csv"
SCREEN_COLUMNS = [
    "company", "filing_date", "filing_url", "screen_score", "priority",
    "release_preview", "screen_notes", "screen_status",
]
LOG_COLUMNS = [
    "ticker", "filing_url", "accepted", "status", "new_products",
    "duplicates", "invalid_products", "notes",
]
EVIDENCE_COLUMNS = [
    "company_name", "stock_name", "filing_time", "new_product",
    "filing_url", "source_document_urls", "screen_score",
    "review_status", "review_notes",
    "evidence_quote", "announcement_date", "model_confidence", "source_sha256",
    "reviewer", "reviewed_utc",
]
FINAL_CSV = "products_final.csv"
DECISIONS_CSV = "review_decisions.csv"
SUMMARY_JSON = AUDIT_DIR / "validation_summary.json"
FINAL_STATUSES = {"source_checked", "human_verified"}


def product_identity(row):
    """Identify a product row for provenance, including its filing timestamp."""
    return (
        row.get("stock_name", ""),
        row.get("new_product", "").strip().casefold(),
        row.get("filing_time", ""),
    )


def prepare_evidence(products, logs, evidence):
    """Carry forward previously reviewed rows with best-known SEC filing URLs."""
    known = {product_identity(row) for row in evidence}
    indexed_logs = {
        (row.get("ticker"), row.get("accepted")): row.get("filing_url", "")
        for row in logs if row.get("accepted")
    }
    for product in products:
        identity = product_identity(product)
        if identity in known:
            continue
        evidence.append({
            "company_name": product["company_name"],
            "stock_name": product["stock_name"],
            "filing_time": product["filing_time"],
            "new_product": product["new_product"],
            "filing_url": indexed_logs.get(
                (product["stock_name"], product["filing_time"]), ""
            ),
            "source_document_urls": "",
            "screen_score": "",
            "review_status": "legacy_review_pending",
            "review_notes": "Imported from preexisting product CSV; confirm SEC source",
        })
        known.add(identity)


def save_progress(products, logs, evidence, screened):
    save_rows(PRODUCT_CSV, products, REQUIRED_FIELDS)
    save_rows(LOG_CSV, logs, LOG_COLUMNS)
    save_rows(EVIDENCE_CSV, evidence, EVIDENCE_COLUMNS)
    save_rows(SCREEN_CSV, screened, SCREEN_COLUMNS)


def replay_journals(products, logs, evidence):
    """Repair exports from completed per-filing transactions after interruption."""
    # Journal attempts are also recorded in notes for compatibility with old log columns.
    for path in sorted((AUDIT_DIR / "filings").glob("*.json")):
        journal = load_json(path)
        row = journal["log"]
        if not any(all(str(r.get(k, "")) == str(v) for k, v in row.items()) for r in logs):
            logs.append(row)
        known = {product_identity(r) for r in products}
        for product in journal["products"]:
            if product_identity(product) not in known:
                products.append(product)
                known.add(product_identity(product))
        known_evidence = {product_identity(r) for r in evidence}
        for item in journal["evidence"]:
            if product_identity(item) not in known_evidence:
                evidence.append(item)
                known_evidence.add(product_identity(item))


def company_from_display(name):
    return re.sub(r"\s*\([^()]*\)\s*\(CIK\s+\d+\)\s*$", "", name).strip()


def compact(text):
    text = re.sub(r"\s+", " ", text).strip()
    # HTML text nodes introduce artificial spaces around inline punctuation.
    text = re.sub(r"\s+([,.;:!?\)\]])", r"\1", text)
    return re.sub(r"([\(\[])\s+", r"\1", text)


def check_grounding(item, sources):
    """A literal quotation is necessary, never sufficient, for verification."""
    url, quote = item.get("source_document_url", ""), item.get("evidence_quote", "")
    if url not in sources or not isinstance(quote, str) or len(compact(quote)) < 25:
        return False
    return compact(quote) in compact(sources[url])


def download_sources(url, headers):
    metadata = get_filing_metadata(url, headers)
    accepted = metadata.get("Accepted", "")
    datetime.strptime(accepted, "%Y-%m-%d %H:%M:%S")
    documents = get_launch_documents(url, headers)
    sources = {doc_url: extract_document_text(doc_url, headers)
               for _, doc_url in documents}
    if not sources or not any(text.strip() for text in sources.values()):
        raise ValueError("No readable filing documents")
    packet = {"filing_url": url, "accepted": accepted, "documents": documents,
              "sources": sources, "retrieved_utc": utc_now()}
    atomic_json(AUDIT_DIR / "sources" / (filing_id(url) + ".json"), packet)
    return packet


def build_input(packet, limit):
    parts, supplied, used = [], {}, 0
    for doc_type, url in sorted(packet["documents"], key=lambda d: not d[0].startswith("EX-99")):
        header = f"\n\n{doc_type} DOCUMENT URL: {url}\n"
        available = limit - used - len(header)
        if available <= 0:
            break
        text = packet["sources"][url][:available]
        parts.append(header + text)
        supplied[url] = text
        used += len(header) + len(text)
    truncated = (len(supplied) < len(packet["sources"]) or any(
        len(text) < len(packet["sources"][url]) for url, text in supplied.items()))
    return "".join(parts), supplied, truncated


def collect_candidates(extracted, packet, candidate, score, products, notes, supplied):
    new_products, new_evidence, duplicates, invalid = [], [], 0, 0
    ticker = ticker_from_company(candidate["company"])
    corrections = {product_identity(r): r for r in read_rows("extraction_corrections.csv")}
    for item in extracted:
        item = item.copy()
        identity = (ticker, item.get("new_product", "").strip().casefold(), packet["accepted"])
        correction = corrections.get(identity, {})
        for key in ("evidence_quote", "product_description", "source_document_url"):
            if correction.get(key):
                item[key] = correction[key]
        valid = validate_product(item, ticker, packet["accepted"])
        if valid is None or not check_grounding(item, supplied):
            invalid += 1
            continue
        valid["company_name"] = company_from_display(candidate["company"])
        if valid["stock_name"] == "GOAI":
            valid["company_name"] = "Eva Live Inc."
        if is_duplicate(valid, products + new_products):
            duplicates += 1
            continue
        new_products.append(valid)
        source_url = item["source_document_url"]
        new_evidence.append({**{k: valid[k] for k in REQUIRED_FIELDS if k != "product_description"},
            "filing_url": candidate["filing_url"], "source_document_urls": source_url,
            "screen_score": score, "review_status": "needs_manual_review",
            "review_notes": compact(notes + "; " + item.get("reason", "")
                                    + "; " + correction.get("correction_notes", "")),
            "evidence_quote": item["evidence_quote"],
            "announcement_date": item.get("announcement_date", ""),
            "model_confidence": item.get("confidence", "uncertain"),
            "source_sha256": hashlib.sha256(packet["sources"][source_url].encode()).hexdigest()})
    return new_products, new_evidence, duplicates, invalid


def recover_completed_responses(candidates, products, logs, evidence, *, recheck=False):
    """A crash after receipt but before CSV/journal saves must not lose paid work."""
    by_url = {r["filing_url"]: r for r in candidates}
    for attempt in request_history():
        url = attempt["filing_url"]
        old_journal = load_json(journal_path(url))
        if (old_journal and not recheck) or url not in by_url:
            continue
        response = load_json(AUDIT_DIR / "responses" / (filing_id(url) + ".json"))
        packet = load_json(AUDIT_DIR / "sources" / (filing_id(url) + ".json"))
        if not response or response.get("status") != "completed" or not packet:
            continue
        try:
            items = json.loads(response["output_text"])["products"]
            if not isinstance(items, list):
                continue
        except (ValueError, KeyError, TypeError):
            continue
        notes = f"Recovered durable API response; API attempt {attempt['attempt']}"
        rows, proofs, duplicates, invalid = collect_candidates(
            items, packet, by_url[url], "", products, notes, packet["sources"])
        if old_journal and not rows:
            continue
        log = {"ticker": ticker_from_company(by_url[url]["company"]) or "",
               "filing_url": url, "accepted": packet["accepted"], "status": "processed",
               "new_products": str(len(rows)), "duplicates": str(duplicates),
               "invalid_products": str(invalid), "notes": notes}
        atomic_json(journal_path(url), {"log": log,
            "products": (old_journal or {}).get("products", []) + rows,
            "evidence": (old_journal or {}).get("evidence", []) + proofs})
        finish_request(attempt["attempt"], status="completed", response_id=response.get("response_id", ""),
                       usage=response.get("usage", {}))
        products.extend(rows)
        evidence.extend(proofs)
        logs.append(log)


def export_validated(products, logs, evidence, screened, *, quiet=False):
    """Only explicit source-review decisions can reach the final CSV."""
    by_id = {product_identity(r): r for r in evidence}
    decisions = {product_identity(r): r for r in read_rows(DECISIONS_CSV)}
    issues, final = [], []
    for index, product in enumerate(products, 2):
        identity = product_identity(product)
        item = by_id.get(identity)
        valid = validate_product(product, product.get("stock_name"), product.get("filing_time"))
        if not valid:
            issues.append({"csv_line": index, "issue": "Invalid five-column record"})
            continue
        if is_duplicate(valid, [p for p in products[:index - 2]]):
            issues.append({"csv_line": index, "issue": "Duplicate/near duplicate product"})
        decision = decisions.get(identity)
        if decision and item:
            item.update({key: decision[key] for key in (
                "review_status", "review_notes", "evidence_quote", "reviewer", "reviewed_utc"
            ) if key in decision})
            if decision.get("source_document_url"):
                item["source_document_urls"] = decision["source_document_url"]
        if not item or item.get("review_status") not in FINAL_STATUSES:
            continue
        packet = load_json(AUDIT_DIR / "sources" / (filing_id(item["filing_url"]) + ".json"))
        proof = {"source_document_url": item.get("source_document_urls", ""),
                 "evidence_quote": item.get("evidence_quote", "")}
        if (not packet or packet["accepted"] != valid["filing_time"]
                or not check_grounding(proof, packet["sources"])
                or not item.get("reviewer") or not item.get("reviewed_utc")):
            issues.append({"csv_line": index, "issue": "Review lacks matching SEC metadata/quote/reviewer"})
            continue
        item["source_sha256"] = hashlib.sha256(
            packet["sources"][proof["source_document_url"]].encode()).hexdigest()
        if not is_duplicate(valid, final):
            final.append(valid)
    # Canonical issuer labels from the preserved baseline; retain SEC spelling otherwise.
    canonical = {}
    for row in read_rows("products_reviewed_11.csv") + products:
        canonical.setdefault(row["stock_name"], row["company_name"])
    for row in final:
        row["company_name"] = canonical[row["stock_name"]]
    final.sort(key=lambda r: (r["filing_time"], r["stock_name"], r["new_product"]))
    preserved = {tuple(r[k] for k in REQUIRED_FIELDS): r
                 for path in (AUDIT_DIR / "baselines").glob("*_products_final.csv")
                 for r in read_rows(path)}.values()
    final_values = {tuple(r[k] for k in REQUIRED_FIELDS) for r in final}
    if any(tuple(r[k] for k in REQUIRED_FIELDS) not in final_values for r in preserved):
        raise ValueError("A preserved source-checked baseline would change; export refused")
    save_rows(FINAL_CSV, final, REQUIRED_FIELDS)
    # Candidate exports remain immutable relative to the reviewed baseline.
    save_rows(EVIDENCE_CSV, evidence, EVIDENCE_COLUMNS)
    save_rows("human_review_queue.csv", [r for r in evidence if r.get("review_status") == "uncertain"],
              EVIDENCE_COLUMNS)
    unique_analyzed = {r["filing_url"] for r in logs if r["status"] == "processed"}
    screen_ok = {r["filing_url"] for r in screened if r["screen_status"] == "screened"}
    summary = {"generated_utc": utc_now(), "model": MODEL,
               "legacy_baseline_rows": len(read_rows("products_reviewed_11.csv")),
               "candidate_product_rows": len(products), "final_product_rows": len(final),
               "final_companies": len({r["stock_name"] for r in final}),
               "discovered_filings": len(read_rows(CANDIDATES_CSV)),
               "llm_analyzed_ticker_labels": len({r["ticker"] for r in logs if r["status"] == "processed"}),
               "llm_analyzed_companies_by_cik": len({re.search(r"/data/(\d+)/", url).group(1)
                                                     for url in unique_analyzed
                                                     if re.search(r"/data/(\d+)/", url)}),
               "final_source_filings": len({(r["stock_name"], r["filing_time"]) for r in final}),
               "unique_llm_analyzed_filings_including_history": len(unique_analyzed),
               "unique_successfully_screened_filings": len(screen_ok),
               "unique_filings_screened_or_llm_analyzed": len(screen_ok | unique_analyzed),
               "new_api_attempts": len(request_history()),
               "authorization_limit": AUTHORIZATION_LIMIT,
               "preserved_source_checked_baseline_rows": len(preserved),
               "additional_batch_api_attempts": max(0, len(request_history()) - max((
                   grant.get("starting_attempts", grant["cumulative_limit"] - grant["additional_requests"])
                   for grant in load_json(AUDIT_DIR / "authorizations.json", [])), default=0)),
               "remaining_authorized_attempts": AUTHORIZATION_LIMIT - len(request_history()),
               "review_status_counts": dict(pd.Series([r.get("review_status", "") for r in evidence]).value_counts().items()),
               "issues": issues,
               "meets_100_entries": len(final) >= 100,
               "meets_100_llm_filings": len(unique_analyzed) >= 100}
    # Convert pandas integer counts before JSON serialization.
    summary["review_status_counts"] = {k: int(v) for k, v in summary["review_status_counts"].items()}
    atomic_json(SUMMARY_JSON, summary)
    if not quiet:
        print(json.dumps(summary, indent=2))
    return summary


def list_candidates():
    if not Path(CANDIDATES_CSV).is_file():
        raise FileNotFoundError(
            f"Missing {CANDIDATES_CSV}. Run sec_launch_discovery.py first."
        )
    candidates = read_rows(CANDIDATES_CSV)
    if not candidates or not {"company", "filing_date", "filing_url"}.issubset(
        candidates[0]
    ):
        raise ValueError("SEC candidate CSV is empty or missing required columns")
    unique = {}
    for row in candidates:
        url = row.get("filing_url", "")
        if url:
            unique[url] = row
    return list(unique.values())


def sec_headers(email=None):
    email = email or os.environ.get("SEC_CONTACT_EMAIL")
    if not email:
        email = input("Enter your contact email for SEC requests: ").strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("A contact email is required by SEC identification policy")
    return {"User-Agent": f"CAP5619 Student Research {email}"}


def headline_adjustment(preview):
    """Penalize obvious non-product press releases, without treating scores as facts."""
    lead = re.sub(r"\s+", " ", preview).lower()[:270]
    excluded = (
        "financial results", "fourth quarter", "third quarter",
        "second quarter", "first quarter", "proposed public offering",
        "convertible senior notes offering", "national tour",
        "investor relations", "corporate rebrand", "rebrands to",
        "announces acquisition", "announces merger",
        "redesigned website", "rebuilt website", "secondary offering", "enterprise identity",
        "affiliate program", "new subsidiary", "broker expansion",
        "announces monthly business update", "announces roi strategy", "earnings press release",
        "appoints", "appointment of", "manufacturing agreement", "manufacturing partnership",
        "secures tri-state distribution", "capital allocation framework", "share repurchase",
        "completes acquisition", "planned entry", "planned commercial launch",
        "initiates additional clinical", "commercial manufacturing and supply agreement",
        "distribution rights", "sale on schedule",
    )
    financing = re.search(r"\b(?:proposed|underwritten|notes?|stock|securities)\b.{0,65}\boffering\b|"
                          r"\boffering\b.{0,65}\b(?:notes?|stock|securities)\b", lead)
    future = re.search(r"ahead of.{0,45}(?:commercial )?launch|pre-orders? ahead", lead)
    return -6 if future or financing or any(phrase in lead for phrase in excluded) else 0


def screen_candidates(candidates, processed_urls, screened, headers, limit, *, press_only=False):
    existing = {row.get("filing_url") for row in screened if row.get("screen_status") != "error"}
    pending = [
        row for row in candidates
        if row["filing_url"] not in existing
        and row["filing_url"] not in processed_urls
        and (not press_only or "EX-99" in row.get("matching_document_types", ""))
    ]
    pending.sort(key=lambda row: (row.get("filing_date", ""), row["filing_url"]))
    batch = pending[:limit]
    print(f"Unscreened pending filings: {len(pending)}; screening now: {len(batch)}")

    for i, candidate in enumerate(batch, 1):
        url = candidate["filing_url"]
        score, priority, preview, notes, status = 0, "Lower", "", "", "screened"
        try:
            documents = get_launch_documents(url, headers)
            exhibits = [
                document_url for doc_type, document_url in documents
                if doc_type.startswith("EX-99")
            ][:2]
            if not exhibits:
                status, notes = "no_text_exhibit", "No readable EX-99 exhibit found"
            else:
                results = []
                for exhibit_url in exhibits:
                    text = extract_document_text(exhibit_url, headers)
                    if not text.strip():
                        continue
                    points, tier, detail = score_release(text)
                    short = re.sub(r"\s+", " ", text)[:300]
                    points += headline_adjustment(short)
                    tier = "Higher" if points >= 5 else (
                        "Medium" if points >= 2 else "Lower"
                    )
                    results.append((points, tier, short, detail))
                if results:
                    score, priority, preview, notes = max(
                        results, key=lambda result: result[0]
                    )
                else:
                    status, notes = "empty_exhibit", "No text from EX-99 exhibits"
        except SecAccessError:
            raise
        except Exception as exc:
            status, notes = "error", str(exc)[:250]

        screened.append({
            "company": candidate["company"],
            "filing_date": candidate["filing_date"],
            "filing_url": url,
            "screen_score": score,
            "priority": priority,
            "release_preview": preview,
            "screen_notes": notes,
            "screen_status": status,
        })
        save_rows(SCREEN_CSV, screened, SCREEN_COLUMNS)
        print(
            f"Screen {i}/{len(batch)}: {score:>2} {priority:<6} "
            f"{candidate['filing_date']} {candidate['company'][:44]} [{status}]", flush=True
        )


def prioritize(candidates, screened, processed_urls, minimum):
    screened_by_url = {row.get("filing_url"): row for row in screened}
    selections = {r["filing_url"]: r for r in read_rows(AUDIT_DIR / "selection_decisions.csv")}
    queue = []
    for candidate in candidates:
        url = candidate["filing_url"]
        if url in processed_urls:
            continue
        selection = selections.get(url, {})
        if selection.get("decision") == "exclude":
            continue
        details = screened_by_url.get(url)
        if not details or details.get("screen_status") != "screened":
            continue
        try:
            score = int(float(details.get("screen_score", 0)))
        except (TypeError, ValueError):
            score = 0
        # Re-evaluate the headline so incidental financial commentary deeper in
        # a launch release does not bury a strong current announcement.
        preview = details.get("release_preview", "")
        score = max(score, score_release(preview)[0])
        penalty = headline_adjustment(preview)
        score = min(score, 0) + penalty if penalty else score
        if selection.get("decision") == "include":
            score = max(score, minimum, 10)
        if score < minimum:
            continue
        queue.append((score, candidate, details))
    # High-confidence launches first; older filings first at equal scores.
    queue.sort(key=lambda item: (
        -item[0], item[1].get("filing_date", ""), item[1]["filing_url"]
    ))
    return queue



def analyze_queue(queue, products, logs, evidence, screened, headers,
                  max_api_calls, max_characters, goal):
    if not queue or max_api_calls <= 0:
        return 0
    if export_validated(products, logs, evidence, screened, quiet=True)["final_product_rows"] >= goal:
        print("Source-checked product target reached; no paid requests sent.")
        return 0
    remaining = AUTHORIZATION_LIMIT - len(request_history())
    if remaining <= 0:
        print("Cumulative authorization exhausted; no requests sent.")
        return 0
    key = keyring.get_password("CAP5619_Assignment2", "OPENAI_API_KEY")
    if not key:
        raise ValueError("API key unavailable in Credential Manager; see README local command")
    client = OpenAI(api_key=key, max_retries=0, timeout=90.0)
    calls = 0
    attempted_urls = {r["filing_url"] for r in request_history()}
    for score, candidate, _ in queue:
        if calls >= min(max_api_calls, remaining):
            break
        if calls and export_validated(products, logs, evidence, screened, quiet=True)["final_product_rows"] >= goal:
            print("Source-checked product target reached; paid extraction stopped.")
            break
        url = candidate["filing_url"]
        if url in attempted_urls:
            continue  # Failed/uncertain attempts require explicit investigation, never rebill silently.
        ticker = ticker_from_company(candidate["company"])
        accepted, notes = "", ""
        count_new = count_dup = count_bad = 0
        new_products, new_evidence = [], []
        status, attempt = "processed", None
        if not ticker:
            status, notes = "skipped_no_ticker", "SEC display name has no primary ticker"
        else:
            print(f"Analyzing {ticker}: {url} (score {score})", flush=True)
            try:
                packet = download_sources(url, headers)
                accepted = packet["accepted"]
                text, supplied, truncated = build_input(packet, max_characters)
                if truncated:
                    notes = "Input truncated; completeness requires review"
                response_path = AUDIT_DIR / "responses" / (filing_id(url) + ".json")
                # Reserve durably before the only network request; no SDK retries.
                attempt = reserve_request(url, MODEL)
                calls += 1
                attempted_urls.add(url)
                extracted = extract_products(text, accepted[:10], client, response_path=response_path,
                                             issuer_name=company_from_display(candidate["company"]), ticker=ticker)
                response = load_json(response_path, {})
                finish_request(attempt, status="completed", response_id=response.get("response_id", ""),
                               usage=response.get("usage", {}))
                new_products, new_evidence, count_dup, count_bad = collect_candidates(
                    extracted, packet, candidate, score, products, notes, supplied)
                count_new = len(new_products)
            except SecAccessError:
                raise
            except Exception as error:
                status = "error"
                # Do not persist arbitrary SDK bodies or exception text that might expose credentials.
                detail = type(error).__name__
                if getattr(error, "status_code", None):
                    detail += f" HTTP {error.status_code}"
                notes = compact(notes + "; " + detail + "; inspect retained response/source checkpoint")
                if attempt:
                    finish_request(attempt, status="error", error_type=detail)
                print("Filing failed:", detail, flush=True)
        if attempt:
            notes = compact(notes + f"; API attempt {attempt}")
        log = {"ticker": ticker or "", "filing_url": url, "accepted": accepted,
               "status": status, "new_products": str(count_new), "duplicates": str(count_dup),
               "invalid_products": str(count_bad), "notes": notes}
        # A single atomic transaction precedes the multi-CSV materialized exports.
        atomic_json(journal_path(url), {"log": log, "products": new_products,
                                       "evidence": new_evidence})
        products.extend(new_products)
        evidence.extend(new_evidence)
        logs.append(log)
        save_progress(products, logs, evidence, screened)
        print(f"Checkpoint: {len(products)} candidates; {calls} requests this run", flush=True)
        # Credential/rate/quota errors are systemic; do not spend the rest of the cap.
        if status == "error" and attempt:
            break
    return calls


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("all", "discover", "screen", "analyze", "plan",
                                         "review-sources", "recheck", "validate", "export"), default="plan")
    parser.add_argument("--sec-email", help="SEC contact; alternatively SEC_CONTACT_EMAIL")
    parser.add_argument("--max-new-screens", type=int, default=160)
    parser.add_argument("--screen-press-matches-only", action="store_true",
                        help="Screen only discovery hits matching EX-99 press-release exhibits")
    parser.add_argument("--max-api-calls", type=int, default=30)
    parser.add_argument("--min-score", type=int, default=5)
    parser.add_argument("--max-input-chars", type=int, default=60000)
    parser.add_argument("--goal", type=int, default=100, help="Reporting target; never pads output")
    parser.add_argument("--start-date", default="2026-01-01")
    parser.add_argument("--end-date", default="2026-10-31")
    parser.add_argument("--query", action="append", help="Repeat for multiple SEC full-text queries")
    parser.add_argument("--max-discovery-pages", type=int, default=3)
    args = parser.parse_args(argv)
    if min(args.max_api_calls, args.max_new_screens) < 0:
        parser.error("Limits cannot be negative")
    if args.max_input_chars < 1000 or args.goal < 1 or args.max_discovery_pages < 1:
        parser.error("Input cap must be >=1000; goal and discovery pages must be positive")
    try:
        start = datetime.strptime(args.start_date, "%Y-%m-%d")
        end = datetime.strptime(args.end_date, "%Y-%m-%d")
        if start > end:
            raise ValueError()
    except ValueError:
        parser.error("Discovery dates must be YYYY-MM-DD in chronological order")
    if args.mode == "discover":
        from sec_launch_discovery import discover
        with exclusive_run():
            discover(sec_headers(args.sec_email), start=args.start_date, end=args.end_date,
                     queries=args.query, max_pages=args.max_discovery_pages)
        return
    candidates = list_candidates()
    products, logs = read_rows(PRODUCT_CSV), read_rows(LOG_CSV)
    evidence, screened = read_rows(EVIDENCE_CSV), read_rows(SCREEN_CSV)
    replay_journals(products, logs, evidence)
    prepare_evidence(products, logs, evidence)
    processed = {r.get("filing_url") for r in logs
                 if r.get("status") in ("processed", "skipped_no_ticker")}
    attempted = {r["filing_url"] for r in request_history()}
    print(f"Discovered filings: {len(candidates)}; saved candidates: {len(products)}; "
          f"handled filings: {len(processed)}; new API attempts: {len(attempted)}/{AUTHORIZATION_LIMIT}")
    queue = prioritize(candidates, screened, processed | attempted, args.min_score)
    if args.mode == "plan":
        print(f"Eligible screened filings at score >= {args.min_score}: {len(queue)}")
        for score, candidate, details in queue[:15]:
            print(f"{score:>2} {candidate['filing_date']} {candidate['company']} "
                  f"{details.get('release_preview', '')[:120]}")
        return  # Read-only: no credential access, lock, network, or data writes.
    with exclusive_run():
        recover_completed_responses(candidates, products, logs, evidence, recheck=args.mode == "recheck")
        processed.update(r["filing_url"] for r in logs if r["status"] == "processed")
        headers = None
        if args.mode in ("all", "screen", "analyze", "review-sources"):
            headers = sec_headers(args.sec_email)
        if args.mode in ("all", "screen"):
            screen_candidates(candidates, processed, screened, headers, args.max_new_screens,
                              press_only=args.screen_press_matches_only)
        queue = prioritize(candidates, screened, processed | attempted, args.min_score)
        if args.mode in ("all", "analyze") and args.max_api_calls:
            calls = analyze_queue(queue, products, logs, evidence, screened, headers,
                                  args.max_api_calls, args.max_input_chars, args.goal)
            print(f"Requests attempted this run: {calls}")
        if args.mode == "review-sources":
            for url in sorted({r.get("filing_url") for r in evidence if r.get("filing_url")}):
                download_sources(url, headers)
                print("Source packet ready:", url, flush=True)
        save_progress(products, logs, evidence, screened)
        summary = export_validated(products, logs, evidence, screened)
        if args.mode == "validate" and summary["issues"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
