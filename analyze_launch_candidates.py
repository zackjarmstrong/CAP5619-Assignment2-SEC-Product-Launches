"""SEC filing-document and primary-ticker helpers for the supported CLI."""
import re
from urllib.parse import urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup
from assignment2 import sec_get


def ticker_from_company(company):
    """Extract first listed ticker from SEC display name, if one is provided."""
    match = re.search(r"\(([^()]*)\)\s*\(CIK\s+\d+\)", str(company))
    if not match:
        return None
    ticker = match.group(1).split(",")[0].strip()
    return ticker if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", ticker) else None


def get_launch_documents(index_url, headers):
    """Retrieve main 8-K plus all HTML/text EX-99 exhibits, not just EX-99.1."""
    response = sec_get(index_url, headers)
    soup = BeautifulSoup(response.text, "html.parser")
    documents = []
    seen_urls = set()

    for table in soup.select("table.tableFile"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            doc_type = cells[3].get_text(strip=True).upper()
            if doc_type != "8-K" and not doc_type.startswith("EX-99"):
                continue

            link = cells[2].find("a", href=True)
            if not link:
                continue
            document_url = urljoin(index_url, link["href"])
            parsed = urlparse(document_url)
            if parsed.path == "/ix":
                doc_path = parse_qs(parsed.query).get("doc", [None])[0]
                if doc_path:
                    document_url = urljoin("https://www.sec.gov", doc_path)

            # The existing text extractor handles HTML/text, not binary PDFs.
            path = urlparse(document_url).path.lower()
            if path.endswith((".pdf", ".jpg", ".png", ".xlsx", ".xml")):
                continue
            if document_url not in seen_urls:
                documents.append((doc_type, document_url))
                seen_urls.add(document_url)

    return documents



def main():
    import sys
    from run_pipeline import main as run
    run(["--mode", "analyze", *sys.argv[1:]])


if __name__ == "__main__":
    main()
