"""Import-safe SEC full-text discovery; invoked by the consolidated CLI."""
from assignment2 import sec_get
from pipeline_store import read_rows, save_rows, atomic_json, load_json, utc_now

COLUMNS = ["company", "filing_date", "filing_url", "filing_items",
           "matching_document_types", "matching_document_count"]
QUERIES = ['"announced the launch"', '"now available" AND "new product"',
           '"today launched"', '"introduces" AND "new"']


def discover(headers, output="sec_launch_candidates.csv", *, start="2026-01-01",
             end="2026-10-31", queries=None, max_pages=3):
    existing = {r["filing_url"]: r for r in read_rows(output)}
    search_log = []
    for query in queries or QUERIES:
        examined = 0
        total = 0
        for page in range(max_pages):
            result = sec_get("https://efts.sec.gov/LATEST/search-index", headers, {
                "q": query, "forms": "8-K", "startdt": start, "enddt": end,
                "from": page * 100, "size": 100,
            }).json()["hits"]
            total_value = result.get("total", 0)
            total = total_value.get("value", 0) if isinstance(total_value, dict) else total_value
            hits = result["hits"]
            examined += len(hits)
            for hit in hits:
                source = hit["_source"]
                if source.get("form") != "8-K" or not source.get("ciks"):
                    continue
                accession = source["adsh"]
                url = ("https://www.sec.gov/Archives/edgar/data/"
                       f"{int(source['ciks'][0])}/{accession.replace('-', '')}/{accession}-index.htm")
                if url not in existing:
                    existing[url] = {
                        "company": source["display_names"][0], "filing_date": source["file_date"],
                        "filing_url": url, "filing_items": ", ".join(source.get("items", [])),
                        "matching_document_types": source.get("file_type", ""),
                        "matching_document_count": "1",
                    }
            # Preserve discovery progress after each page without replacing historical rows.
            save_rows(output, sorted(existing.values(), key=lambda r: (r["filing_date"], r["filing_url"])), COLUMNS)
            if not hits or examined >= total or len(hits) < 100:
                break
        search_log.append({"query": query, "reported_document_hits": total,
                           "examined_document_hits": examined, "start": start, "end": end,
                           "retrieved_utc": utc_now(), "page_cap": max_pages})
        print(f"Discovery: {query}: {examined}/{total} document hits; {len(existing)} unique filings", flush=True)
    atomic_json("audit/discovery_latest.json", search_log)
    history = load_json("audit/discovery_history.json", [])
    atomic_json("audit/discovery_history.json", history + search_log)
    return list(existing.values())


if __name__ == "__main__":
    import sys
    from run_pipeline import main
    main(["--mode", "discover", *sys.argv[1:]])
