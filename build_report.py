"""Generate the two-page methodology PDF from actual validated project results."""
import csv
import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                               TableStyle, PageBreak)


def rows(path):
    with open(path, encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    summary = json.loads(Path("audit/validation_summary.json").read_text(encoding="utf-8"))
    ledger = json.loads(Path("audit/api_requests.json").read_text(encoding="utf-8"))
    candidates, final = rows("sec_launch_candidates.csv"), rows("products_final.csv")
    logs = rows("filing_review_log.csv")
    companies = summary["llm_analyzed_companies_by_cik"]
    ticker_labels = summary["llm_analyzed_ticker_labels"]
    final_filings = len({(r["stock_name"], r["filing_time"]) for r in final})
    attempted = len(ledger)
    authorization = summary["authorization_limit"]
    discovery_start = min(r["filing_date"] for r in candidates)
    discovery_end = max(r["filing_date"] for r in candidates)
    input_tokens = sum(r.get("usage", {}).get("input_tokens", 0) for r in ledger)
    output_tokens = sum(r.get("usage", {}).get("output_tokens", 0) for r in ledger)
    statuses = summary["review_status_counts"]
    model_ids = ", ".join(sorted({r.get("model", "gpt-6-luna") for r in ledger}))
    sections = [
        ("Research question and scope",
         "This project identifies original announcements of completed product or distinct new service launches "
         "in SEC Form 8-K filings. The output has exactly company_name, stock_name, filing_time, new_product, "
         "and product_description; descriptions contain fewer than 180 characters. The written Assignment 2 "
         "handout and course examples guide the Python, SEC collection, LLM extraction, and reporting approach. "
         f"The discovery pool spans {discovery_start} through {discovery_end}. "
         "The sample is purposive rather than representative."),
        ("Data collection and model specifications",
         f"The merged discovery pool contains {len(candidates)} unique filing URLs. SEC full-text searches "
         "used launch and availability phrases, including announced the launch, today launched, introduces/new "
         "products, and launches/now available. Pagination limits and retrieved document-hit counts are logged; "
         "document hits are deduplicated to filing URLs. The main 8-K and readable EX-99 exhibits are fetched "
         "with an identified User-Agent, sequential pacing, local caching, and limited transient-error retries. "
         f"The request ledger records {attempted} new model attempts. The configured model is gpt-6-luna "
         f"through OpenAI's Responses API (recorded identifiers: {model_ids}). Each call uses strict JSON Schema, "
         "at most 60,000 source-text characters and 10,000 output tokens. No fine-tuning or explicit temperature "
         "setting is used. Model weights and training details were not independently available. Actual token "
         f"usage retained for these attempts totals {input_tokens:,} input and {output_tokens:,} output tokens; "
         "the report does not infer a dollar charge."),
        ("Extraction and review method",
         "Free screening ranks launch language near exhibit openings and penalizes earnings, financing, rebrand, "
         "website, and other non-product headlines. Selected filings are analyzed one per model request. "
         "Named Entity Recognition (NER) is performed by the LLM: it identifies company names as ORGANIZATION "
         "entities and newly announced products as PRODUCT entities, returning company_name and new_product "
         "within structured fields. These are semantic entity roles, not separately emitted BIO tags. No separate "
         "NER model was trained; issuer names are subsequently normalized to SEC metadata. The prompt "
         "excludes historical mentions, planned developments, prototypes, acquisitions, issuer financing, and "
         "channel expansions. It requests the source URL, a contiguous launch quote, announcement date, confidence, "
         "and rationale alongside the five data fields. Python supplies SEC's acceptance timestamp, validates "
         "the ticker and field types, rejects long descriptions, and checks the quote against supplied text. "
         "Names are deduplicated within a ticker using normalization and close-spelling comparison. An AI assistant "
         "groups strengths, configurations and suite variants rather than expanding them into extra rows, "
         "reads the original exhibit, checks the product description and current-launch context, and records "
         "an explicit source-review decision. Only source-checked or human-verified rows can enter the final CSV. "
         "The source_checked label explicitly denotes AI-assisted source review, not independent human verification."),
        ("Observed problems and corrections",
         "Search terms also retrieved past launches in earnings summaries and unrelated corporate announcements. "
         "High model confidence was insufficient: later paragraphs sometimes revealed beta status or future "
         "commercial availability despite a launch headline. Source review excluded these and historical recaps. "
         "Six earlier uncertain cases were reassessed; four were rejected and two remain excluded. "
         "Genius retains VRSSD: SEC exhibits document its March 2025 adoption and April 17 use, but the April 30 "
         "launch release lists VRSSF. The effective symbol on May 2 is unresolved; no current-ticker inference "
         "was used. Details and source references are in audit/genius_ticker_review.json. "
         "SEC inline HTML added spaces around punctuation; quote comparison normalizes this "
         "without changing words. Some model quotes omitted intervening text and some descriptions were too "
         "long. Documented source-based corrections preserve raw responses and require another offline check. "
         "An attached launch release may report initial shipments before SEC acceptance; historical recaps are excluded."),
        ("Results and completion status",
         f"The project retains {summary['candidate_product_rows']} candidate product rows, including the "
         f"unchanged 11-row legacy baseline. The final export contains {len(final)} source-checked product rows "
         f"from {summary['final_companies']} companies and {final_filings} distinct issuer/acceptance-time pairs. "
         f"Across preserved history and this collection, {summary['unique_llm_analyzed_filings_including_history']} "
         f"unique filings from {companies} SEC CIKs ({ticker_labels} ticker labels) have successful LLM analysis logs. "
         f"{summary['unique_successfully_screened_filings']} filings have successful free screening records; "
         f"{summary['unique_filings_screened_or_llm_analyzed']} distinct filings were screened or LLM-analyzed "
         "in total. These categories overlap and must not be added. Historical logs include filings outside the "
         "current discovery pool. "
         f"Review outcomes are {statuses.get('source_checked', 0)} source_checked, "
         f"{statuses.get('uncertain', 0)} uncertain, {statuses.get('rejected', 0)} rejected, and "
         f"{statuses.get('needs_manual_review', 0) + statuses.get('legacy_review_pending', 0)} pending. "
         f"The 100-entry objective is {'met' if summary['meets_100_entries'] else 'not met'}, and the "
         f"100-LLM-filing objective is {'met' if summary['meets_100_llm_filings'] else 'not met'}. "
         f"The product shortfall is {max(0, 100 - len(final))} rows. No rows were invented or duplicated to "
         "satisfy either target."),
        ("Reproducibility, limitations, and AI assistance",
         "Course methods include SEC text collection, contextual prompting, entity extraction, and structured "
         "output. Concrete budget limits, journals, locks, hashes, and preservation checks are additional "
         "engineering decisions, not techniques specifically required by the professor. This is LLM inference, "
         "not model training; the written handout does not require Weights & Biases, and none is integrated. "
         "Complete raw outputs, recovery journals, and development history remain in a private archive. "
         "This public export retains checkpoints, SEC source packets, decisions, and hashes for offline validation. "
         "The original workflow used atomic journals for recovery. Its ledger reserves requests before sending, "
         "disables SDK retries, and enforces "
         f"the user's cumulative {authorization}-attempt ceiling across restarts; failures consume a slot. "
         f"This batch used {summary['additional_batch_api_attempts']} attempts. The initial "
         "60-attempt grant was increased twice by explicit 60-attempt approvals. Paid extraction stops once "
         "100 source-supported products pass review. All 73 previously source-checked rows and prior audit "
         "history were preserved. Windows Credential Manager "
         "holds the API key. The README documents execution and offline tests. The attached CSV and report state "
         "actual progress and remaining requirements. Screening may miss launches in financial releases or beyond "
         "the first exhibits, and truncated inputs need review. No labeled benchmark was available, so precision, "
         "recall, and exhaustive originality are not claimed. Announcements are issuer statements, not independent "
         "verification of efficacy or performance. Codex assisted code development, tests, extraction design, "
         "source review, and report preparation. The student should review the source, decisions, and instructor "
         "AI-use rules before submission."),
    ]
    repository = "https://github.com/zackjarmstrong/CAP5619-Assignment2-SEC-Product-Launches"
    reference = (f"GitHub repository: {repository}. "
                 "Sources: Assignment 2 handout and course examples reviewed privately (not redistributed); "
                 "SEC EDGAR filing/exhibit URLs are recorded per product in product_evidence.csv. "
                 "API documentation: developers.openai.com/api/reference/python; "
                 "developers.openai.com/api/docs/guides/structured-outputs; "
                 "developers.openai.com/api/docs/models/gpt-6-luna. Accessed November 1, 2026.")
    markdown = "# CAP5619 Assignment 2 - Methodology and Results\n\nFinalized: November 2, 2026\n\n"
    markdown += "\n\n".join(f"## {heading}\n\n{body}" for heading, body in sections)
    markdown += "\n\n" + reference + "\n"
    Path("METHODOLOGY.md").write_text(markdown, encoding="utf-8")
    out = Path("output/pdf/methodology_report.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", fontName="Helvetica-Bold", fontSize=22,
                              leading=26, textColor=colors.HexColor("#102E46"), spaceAfter=10))
    styles.add(ParagraphStyle(name="Deck", fontName="Helvetica", fontSize=9, leading=12,
                              textColor=colors.HexColor("#516879"), spaceAfter=15))
    styles.add(ParagraphStyle(name="SectionLabel", fontName="Helvetica-Bold", fontSize=11,
                              leading=14, textColor=colors.HexColor("#126D7A"), spaceBefore=9,
                              spaceAfter=5))
    styles.add(ParagraphStyle(name="ReportBody", fontName="Helvetica", fontSize=9.6,
                              leading=13.2, spaceAfter=7, alignment=TA_LEFT))
    styles.add(ParagraphStyle(name="References", fontName="Helvetica", fontSize=7.7,
                              leading=10.3, textColor=colors.HexColor("#516879"), spaceBefore=7))
    story = [Paragraph("Finding product launches<br/>in SEC filings", styles["ReportTitle"]),
             Paragraph("CAP5619 - Artificial Intelligence and Finance | Assignment 2<br/>"
                       "Methodology and results | November 2, 2026", styles["Deck"])]
    metrics = [["SOURCE-CHECKED PRODUCTS", "LLM-ANALYZED FILINGS", "NEW API ATTEMPTS"],
               [str(len(final)), str(summary["unique_llm_analyzed_filings_including_history"]), f"{attempted} / {authorization}"]]
    table = Table(metrics, colWidths=[170, 170, 170], rowHeights=[22, 40])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EAF2F5")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#102E46")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7), ("FONTSIZE", (0, 1), (-1, 1), 22),
        ("LEADING", (0, 0), (-1, 0), 9), ("LEADING", (0, 1), (-1, 1), 26),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.extend([table, Spacer(1, 9)])
    for index, (heading, body) in enumerate(sections):
        if index == 3:
            story.append(PageBreak())
            story.append(Paragraph("Quality, results, and limitations", styles["ReportTitle"]))
        story.append(Paragraph(escape(heading), styles["SectionLabel"]))
        story.append(Paragraph(escape(body), styles["ReportBody"]))
    story.append(Paragraph(escape(reference), styles["References"]))

    def footer(canvas, doc):
        canvas.setStrokeColor(colors.HexColor("#C9D9DF"))
        canvas.line(51, 43, 561, 43)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#516879"))
        canvas.drawString(51, 29, "CAP5619 | LLM Document Analysis | Results are a dated snapshot")
        canvas.drawRightString(561, 29, str(doc.page))

    SimpleDocTemplate(str(out), pagesize=(612, 792), leftMargin=51, rightMargin=51,
                      topMargin=43, bottomMargin=55, title="CAP5619 Assignment 2 - Methodology",
                      author="CAP5619 student project").build(story, onFirstPage=footer, onLaterPages=footer)
    print(out.resolve())


if __name__ == "__main__":
    main()
