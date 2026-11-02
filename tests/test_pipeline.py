import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile

from run_pipeline import (
    headline_adjustment,
    prioritize,
    product_identity,
    prepare_evidence,
    save_rows,
    read_rows,
)
from assignment2 import is_duplicate, validate_product


class PipelineTests(unittest.TestCase):
    def test_prioritize_uses_screen_score(self):
        candidates = [
            {"company": "A", "filing_date": "2026-01-02", "filing_url": "a"},
            {"company": "B", "filing_date": "2026-01-01", "filing_url": "b"},
        ]
        screens = [
            {"filing_url": "a", "screen_score": 9, "screen_status": "screened"},
            {"filing_url": "b", "screen_score": 6, "screen_status": "screened"},
        ]
        queue = prioritize(candidates, screens, set(), 5)
        self.assertEqual([row[1]["filing_url"] for row in queue], ["a", "b"])
        self.assertEqual(len(prioritize(candidates, screens, {"a"}, 5)), 1)

    def test_headline_penalty(self):
        self.assertEqual(headline_adjustment("FOURTH QUARTER FINANCIAL RESULTS"), -6)
        self.assertEqual(headline_adjustment("Launches a new digital platform"), 0)

    def test_duplicate_detection(self):
        saved = [{"stock_name": "AMBO", "new_product": "HybriU ProjectHub"}]
        self.assertTrue(is_duplicate(
            {"stock_name": "AMBO", "new_product": "HybriU ProjectHub"}, saved
        ))
        self.assertFalse(is_duplicate(
            {"stock_name": "GOAI", "new_product": "HybriU ProjectHub"}, saved
        ))

    def test_validation_overrides_model_timestamp(self):
        product = {
            "company_name": "Eva Live Inc.",
            "stock_name": "GOAI",
            "filing_time": "",
            "new_product": "Example product",
            "product_description": "Example description",
        }
        checked = validate_product(product, "GOAI", "2026-02-18 11:27:26")
        self.assertEqual(checked["filing_time"], "2026-02-18 11:27:26")
        self.assertIsNone(validate_product(product, "AMBO", "2026-02-18"))

    def test_prepare_evidence_existing_products(self):
        product = {
            "company_name": "Eva Live Inc.",
            "stock_name": "GOAI",
            "filing_time": "2026-02-18 11:27:26",
            "new_product": "NeuroServer web application",
            "product_description": "Example",
        }
        log = [{
            "ticker": "GOAI", "accepted": "2026-02-18 11:27:26",
            "filing_url": "https://www.sec.gov/example"
        }]
        evidence = []
        prepare_evidence([product], log, evidence)
        prepare_evidence([product], log, evidence)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["filing_url"], "https://www.sec.gov/example")
        self.assertEqual(evidence[0]["review_status"], "legacy_review_pending")

    def test_atomic_round_trip(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "sample.csv"
            save_rows(path, [{"field": "value"}], ["field"])
            self.assertEqual(read_rows(path), [{"field": "value"}])
            self.assertFalse(path.with_name("sample.csv.tmp").exists())


if __name__ == "__main__":
    unittest.main()
