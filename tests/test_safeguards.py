"""Offline behavioral checks: cost ceilings, recovery, grounding and final export."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import assignment2 as core
import pipeline_store as store
import run_pipeline as pipeline

URL = "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/0000000001-26-000001-index.htm"
DOC = "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/ex99.htm"
STAMP = "2026-10-01 09:00:00"
QUOTE = "Example Inc. today launched Widget, its new productivity application."
PRODUCT = dict(company_name="Example Inc.", stock_name="EX", filing_time=STAMP,
               new_product="Widget", product_description="A productivity application.")
ITEM = {**PRODUCT, "source_document_url": DOC, "evidence_quote": QUOTE,
        "announcement_date": "2026-10-01", "confidence": "high", "reason": "Current launch."}
PACKET = {"filing_url": URL, "accepted": STAMP, "documents": [("EX-99.1", DOC)],
          "sources": {DOC: QUOTE}}
CANDIDATE = {"company": "Example Inc. (EX) (CIK 0000000001)",
             "filing_date": "2026-10-01", "filing_url": URL}


class Isolated(unittest.TestCase):
    def setUp(self):
        self.old_cwd = Path.cwd()
        self.temp = tempfile.TemporaryDirectory(dir=self.old_cwd)
        os.chdir(self.temp.name)
        self.stdout = contextlib.redirect_stdout(io.StringIO())
        self.stdout.__enter__()

    def tearDown(self):
        self.stdout.__exit__(None, None, None)
        os.chdir(self.old_cwd)
        self.temp.cleanup()


class Safeguards(Isolated):
    def test_transient_windows_checkpoint_lock_retries_without_rewriting(self):
        temporary = Mock()
        temporary.replace.side_effect = [PermissionError("reader lock"), None]
        with patch.object(store.time, "sleep") as sleep:
            store.replace_checkpoint(temporary, "checkpoint.csv")
        self.assertEqual(temporary.replace.call_count, 2)
        sleep.assert_called_once_with(0.1)
        temporary.replace.side_effect = PermissionError("persistent lock")
        with patch.object(store.time, "sleep"), self.assertRaises(PermissionError):
            store.replace_checkpoint(temporary, "checkpoint.csv")

    def test_press_only_screening_skips_contract_hits(self):
        press = {**CANDIDATE, "matching_document_types": "EX-99.1"}
        contract = {**CANDIDATE, "filing_url": URL + "contract",
                    "matching_document_types": "EX-10.1"}
        screened = []
        with patch.object(pipeline, "get_launch_documents", return_value=[("EX-99.1", DOC)]) as get, \
             patch.object(pipeline, "extract_document_text", return_value=QUOTE):
            pipeline.screen_candidates([contract, press], set(), screened, {}, 10, press_only=True)
        get.assert_called_once_with(URL, {})
        self.assertEqual([r["filing_url"] for r in screened], [URL])

    def test_audited_selection_avoids_known_nonlaunch_requests(self):
        store.save_rows(store.AUDIT_DIR / "selection_decisions.csv", [
            {"filing_url": URL, "decision": "exclude", "reason": "Future development only"}],
            ["filing_url", "decision", "reason"])
        self.assertEqual(pipeline.prioritize([CANDIDATE], [{
            "filing_url": URL, "screen_score": "9", "screen_status": "screened"}], set(), 5), [])

    def test_expanded_authorization_stops_at_180_without_resetting_history(self):
        prior = [{"attempt": i, "filing_url": URL + str(i), "status": "completed"}
                 for i in range(1, 180)]
        store.atomic_json(store.LEDGER, prior)
        self.assertEqual(store.reserve_request(URL, core.MODEL), 180)
        with self.assertRaises(RuntimeError):
            store.reserve_request(URL + "over-limit", core.MODEL)
        self.assertEqual(store.request_history()[:179], prior)

    def test_reviewed_goal_stops_before_credential_or_request(self):
        evidence = {**PRODUCT, "filing_url": URL, "source_document_urls": DOC,
                    "evidence_quote": QUOTE, "review_status": "source_checked",
                    "reviewer": "Test reviewer", "reviewed_utc": store.utc_now()}
        store.atomic_json(store.AUDIT_DIR / "sources" / (store.filing_id(URL) + ".json"), PACKET)
        with patch.object(pipeline.keyring, "get_password") as credential, \
             patch.object(pipeline, "OpenAI") as api:
            count = pipeline.analyze_queue([(9, CANDIDATE, {})], [PRODUCT], [],
                                           [evidence], [], {}, 60, 60000, 1)
        self.assertEqual(count, 0)
        self.assertEqual(store.request_history(), [])
        credential.assert_not_called()
        api.assert_not_called()

    def test_preserved_source_checked_baseline_cannot_be_dropped(self):
        store.save_rows(store.AUDIT_DIR / "baselines" / "before_additional_60_products_final.csv",
                        [PRODUCT], core.REQUIRED_FIELDS)
        with self.assertRaises(ValueError):
            pipeline.export_validated([], [], [], [])
        self.assertFalse(Path(pipeline.FINAL_CSV).exists())

    def test_cumulative_budget_counts_reservations_and_errors(self):
        with patch.object(store, "AUTHORIZATION_LIMIT", 2):
            self.assertEqual(store.reserve_request(URL, core.MODEL), 1)
            store.finish_request(1, status="error")
            self.assertEqual(store.reserve_request(URL + "2", core.MODEL), 2)
            with self.assertRaises(RuntimeError):
                store.reserve_request(URL + "3", core.MODEL)
        self.assertEqual(len(store.request_history()), 2)

    def test_corrupt_ledger_refuses_calls(self):
        store.atomic_json(store.LEDGER, [{"attempt": 7, "filing_url": URL}])
        with self.assertRaises(ValueError):
            store.reserve_request(URL, core.MODEL)

    def test_missing_ledger_with_existing_response_refuses_calls(self):
        store.atomic_json(store.AUDIT_DIR / "responses" / "existing.json", {})
        with self.assertRaises(ValueError):
            store.reserve_request(URL, core.MODEL)

    def test_curated_package_cannot_reset_budget_by_losing_ledger(self):
        store.atomic_json(store.AUDIT_DIR / "authorizations.json", [{
            "cumulative_limit": 180, "additional_requests": 60, "starting_attempts": 120}])
        with self.assertRaises(ValueError):
            store.reserve_request(URL, core.MODEL)

    def test_concurrent_writer_cannot_enter(self):
        with store.exclusive_run():
            with self.assertRaises(RuntimeError):
                with store.exclusive_run():
                    pass
        self.assertFalse(Path(".pipeline.lock").exists())

    def test_journal_replay_is_idempotent_after_partial_csv_save(self):
        log = dict(ticker="EX", filing_url=URL, accepted=STAMP, status="processed",
                   new_products="1", duplicates="0", invalid_products="0", notes="API attempt 1")
        evidence = {**PRODUCT, "filing_url": URL, "review_status": "needs_manual_review"}
        store.atomic_json(store.journal_path(URL), {"log": log, "products": [PRODUCT],
                                                   "evidence": [evidence]})
        products, logs, proofs = [], [], []
        pipeline.replay_journals(products, logs, proofs)
        pipeline.replay_journals(products, logs, proofs)
        self.assertEqual((len(products), len(logs), len(proofs)), (1, 1, 1))

    def test_final_export_excludes_model_confidence_alone(self):
        evidence = {**PRODUCT, "filing_url": URL, "source_document_urls": DOC,
                    "evidence_quote": QUOTE, "model_confidence": "high",
                    "review_status": "needs_manual_review"}
        summary = pipeline.export_validated([PRODUCT], [], [evidence], [])
        self.assertEqual(summary["final_product_rows"], 0)
        self.assertEqual(store.read_rows(pipeline.FINAL_CSV), [])
        self.assertEqual(store.read_rows("human_review_queue.csv"), [])
        evidence["review_status"] = "uncertain"
        pipeline.export_validated([PRODUCT], [], [evidence], [])
        self.assertEqual(len(store.read_rows("human_review_queue.csv")), 1)

    def test_final_export_requires_matching_metadata_and_quote(self):
        evidence = {**PRODUCT, "filing_url": URL, "source_document_urls": DOC,
                    "evidence_quote": QUOTE, "review_status": "source_checked",
                    "reviewer": "Test source reviewer", "reviewed_utc": store.utc_now()}
        store.atomic_json(store.AUDIT_DIR / "sources" / (store.filing_id(URL) + ".json"), PACKET)
        result = pipeline.export_validated([PRODUCT], [], [evidence], [])
        self.assertEqual(result["final_product_rows"], 1)
        packet = copy.deepcopy(PACKET)
        packet["accepted"] = "2026-09-30 09:00:00"
        store.atomic_json(store.AUDIT_DIR / "sources" / (store.filing_id(URL) + ".json"), packet)
        result = pipeline.export_validated([PRODUCT], [], [evidence], [])
        self.assertEqual(result["final_product_rows"], 0)
        self.assertTrue(result["issues"])

    def test_unverifiable_quote_cannot_pass(self):
        self.assertTrue(pipeline.check_grounding(ITEM, PACKET["sources"]))
        self.assertFalse(pipeline.check_grounding({**ITEM, "evidence_quote": "Invented launch sentence describing a nonexistent new product."}, PACKET["sources"]))
        self.assertFalse(pipeline.check_grounding({**ITEM, "source_document_url": "https://example.com"}, PACKET["sources"]))
        # HTML inline-node spacing is not a change in the quoted wording.
        self.assertTrue(pipeline.check_grounding(ITEM, {DOC: QUOTE.replace("Widget,", "Widget ,")}))

    def test_truncation_tracks_omitted_documents_and_limit(self):
        packet = copy.deepcopy(PACKET)
        packet["sources"][DOC] = QUOTE * 1000
        text, sources, truncated = pipeline.build_input(packet, 1000)
        self.assertLessEqual(len(text), 1000)
        self.assertTrue(truncated)
        self.assertLess(len(sources[DOC]), len(packet["sources"][DOC]))

    def test_analysis_budget_reserved_before_call_and_retries_disabled(self):
        def extract(*args, **kwargs):
            self.assertEqual(store.request_history()[0]["status"], "reserved")
            store.atomic_json(kwargs["response_path"], {"response_id": "test", "usage": {}})
            return [ITEM]
        with patch.object(pipeline.keyring, "get_password", return_value="test-placeholder"), \
             patch.object(pipeline, "OpenAI") as client, \
             patch.object(pipeline, "download_sources", return_value=PACKET), \
             patch.object(pipeline, "extract_products", side_effect=extract):
            products, logs, evidence = [], [], []
            count = pipeline.analyze_queue([(9, CANDIDATE, {})], products, logs, evidence,
                                           [], {}, 1, 60000, 100)
            self.assertEqual(count, 1)
            self.assertEqual(client.call_args.kwargs["max_retries"], 0)
            self.assertEqual(evidence[0]["review_status"], "needs_manual_review")
            self.assertEqual(len(products), 1)
            # A second process/run with the same URL must not bill again.
            self.assertEqual(pipeline.analyze_queue([(9, CANDIDATE, {})], products, logs,
                                                    evidence, [], {}, 1, 60000, 100), 0)

    def test_error_stops_paid_batch_and_consumes_slot(self):
        queue = [(9, CANDIDATE, {}), (8, {**CANDIDATE, "filing_url": URL + "2"}, {})]
        with patch.object(pipeline.keyring, "get_password", return_value="test-placeholder"), \
             patch.object(pipeline, "OpenAI"), \
             patch.object(pipeline, "download_sources", return_value=PACKET), \
             patch.object(pipeline, "extract_products", side_effect=RuntimeError("failure")) as extract:
            self.assertEqual(pipeline.analyze_queue(queue, [], [], [], [], {}, 5, 60000, 100), 1)
            self.assertEqual(extract.call_count, 1)
        self.assertEqual(store.request_history()[0]["status"], "error")

    def test_empty_queue_does_not_require_credential(self):
        with patch.object(pipeline.keyring, "get_password") as credential:
            self.assertEqual(pipeline.analyze_queue([], [], [], [], [], {}, 10, 60000, 100), 0)
            credential.assert_not_called()

    def test_recover_response_saved_before_journal_without_api(self):
        store.reserve_request(URL, core.MODEL)
        store.atomic_json(store.AUDIT_DIR / "sources" / (store.filing_id(URL) + ".json"), PACKET)
        store.atomic_json(store.AUDIT_DIR / "responses" / (store.filing_id(URL) + ".json"),
                          {"status": "completed", "output_text": json.dumps({"products": [ITEM]})})
        products, logs, evidence = [], [], []
        with patch.object(pipeline, "OpenAI") as api:
            pipeline.recover_completed_responses([CANDIDATE], products, logs, evidence)
            pipeline.recover_completed_responses([CANDIDATE], products, logs, evidence)
            api.assert_not_called()
        self.assertEqual((len(products), len(logs), len(evidence)), (1, 1, 1))
        self.assertEqual(store.request_history()[0]["status"], "completed")

    def test_reject_overlong_description_and_invalid_timestamp(self):
        self.assertIsNone(core.validate_product({**PRODUCT, "product_description": "x" * 180}, "EX", STAMP))
        self.assertIsNone(core.validate_product(PRODUCT, "EX", "2026-10-01"))
        self.assertIsNotNone(core.validate_product({**PRODUCT, "product_description": "x" * 179}, "EX", STAMP))

    def test_documented_correction_salvages_response_without_weakening_grounding(self):
        item = {**ITEM, "evidence_quote": "A quote ... that is not contiguous."}
        store.save_rows("extraction_corrections.csv", [{
            **PRODUCT, "evidence_quote": QUOTE, "source_document_url": DOC,
            "correction_notes": "Restored original source sentence after inspection."}],
            list(PRODUCT) + ["evidence_quote", "source_document_url", "correction_notes"])
        rows, evidence, _, invalid = pipeline.collect_candidates(
            [item], PACKET, CANDIDATE, 9, [], "", PACKET["sources"])
        self.assertEqual((len(rows), invalid), (1, 0))
        self.assertEqual(evidence[0]["review_status"], "needs_manual_review")
        store.save_rows("extraction_corrections.csv", [{
            **PRODUCT, "evidence_quote": "An invented announcement with no source support."}],
            list(PRODUCT) + ["evidence_quote"])
        rows, _, _, invalid = pipeline.collect_candidates(
            [item], PACKET, CANDIDATE, 9, [], "", PACKET["sources"])
        self.assertEqual((len(rows), invalid), (0, 1))

    def test_cached_sec_response_avoids_network_and_checks_integrity(self):
        response = Mock(status_code=200, text="<html>Original filing</html>", url=URL)
        with patch.object(core.requests, "get", return_value=response) as get, \
             patch.object(core.time, "sleep"):
            headers = {"User-Agent": "Research student@example.com"}
            self.assertEqual(core.sec_get(URL, headers).text, response.text)
            self.assertEqual(core.sec_get(URL, headers).text, response.text)
            self.assertEqual(get.call_count, 1)
            path = next(core.CACHE_DIR.glob("*.json"))
            payload = store.load_json(path)
            payload["text"] = "tampered"
            store.atomic_json(path, payload)
            with self.assertRaises(ValueError):
                core.sec_get(URL, headers)

    def test_plan_is_read_only_and_does_not_access_credentials(self):
        store.save_rows(pipeline.CANDIDATES_CSV, [CANDIDATE], list(CANDIDATE))
        before = {p: p.read_bytes() for p in Path.cwd().rglob("*") if p.is_file()}
        with patch.object(pipeline.keyring, "get_password") as credential:
            pipeline.main(["--mode", "plan"])
            credential.assert_not_called()
        after = {p: p.read_bytes() for p in Path.cwd().rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_prioritization_rescues_current_launch_and_excludes_rebrand(self):
        candidates = [CANDIDATE, {**CANDIDATE, "filing_url": URL + "2"}]
        screens = [
            {"filing_url": URL, "screen_score": "1", "screen_status": "screened",
             "release_preview": "Example launches Widget, a new platform now available to customers."},
            {"filing_url": URL + "2", "screen_score": "8", "screen_status": "screened",
             "release_preview": "Example introduces its new enterprise identity."}]
        queue = pipeline.prioritize(candidates, screens, set(), 5)
        self.assertEqual([row[1]["filing_url"] for row in queue], [URL])


if __name__ == "__main__":
    unittest.main()
