"""Build the public submission from an explicit allowlist; no network or API calls."""
import csv
import hashlib
import json
from pathlib import Path
import zipfile


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    publication = json.loads(Path("publication_manifest.json").read_text(encoding="utf-8"))
    names = publication["files"]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate publication paths")
    forbidden = (".git/", "course_references/", "tmp/", "cache/", "audit/responses/", "audit/filings/")
    for name in names:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or name.startswith(forbidden):
            raise ValueError("Unsafe publication path")
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(name)
    if digest("products_final.csv") != publication["final_csv_sha256"]:
        raise ValueError("Validated product dataset changed; packaging refused")
    if digest("audit/api_requests.json") != publication["api_ledger_sha256"]:
        raise ValueError("Request ledger changed; packaging refused")
    summary = json.loads(Path("audit/validation_summary.json").read_text(encoding="utf-8"))
    if summary["issues"] or summary["final_product_rows"] != publication["expected_products"]:
        raise ValueError("Fix validation issues before packaging")
    manifest = {name: digest(name) for name in names}
    with zipfile.ZipFile("submission.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.write(name, name)
        archive.writestr("MANIFEST_SHA256.json", json.dumps(manifest, indent=2) + "\n")
    with zipfile.ZipFile("submission.zip") as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP integrity check failed")
        for name, expected in manifest.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise ValueError("ZIP hash mismatch: " + name)
    checksum = digest("submission.zip")
    Path("submission.zip.sha256").write_text(checksum + "  submission.zip\n", encoding="utf-8", newline="\n")
    verification = {"repository": publication["repository"], "final_products": summary["final_product_rows"],
                    "llm_analyzed_filings": summary["unique_llm_analyzed_filings_including_history"],
                    "api_requests": summary["new_api_attempts"], "new_openai_requests": 0,
                    "final_csv_sha256": publication["final_csv_sha256"], "api_ledger_sha256": publication["api_ledger_sha256"],
                    "manifest_entries": len(manifest), "total_entries": len(manifest) + 1,
                    "source_packets": publication["source_packets"], "sha256": checksum,
                    "bytes": Path("submission.zip").stat().st_size, "zip_crc_check": "passed",
                    "manifest_hashes_match_archive_and_workspace": True}
    Path("submission_verification.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(verification, indent=2))


if __name__ == "__main__":
    main()
