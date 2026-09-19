#!/usr/bin/env python3

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).with_name("cost_receipt.py")
SPEC = importlib.util.spec_from_file_location("astra_helm_cost_receipt", MODULE_PATH)
receipt = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(receipt)


def valid_input(*, complete=True, usage=None):
    if usage is None:
        usage = {
            "source": "host runtime result for call-1", "scope": "atomic_call",
            "input_tokens": 1_000_000, "cached_input_tokens": 200_000,
            "output_tokens": 100_000, "reasoning_output_tokens": 50_000,
        }
    return {
        "schema_version": 1,
        "scope": {"id": "run-1", "description": "one bounded task", "cutoff": "2026-09-19T00:00:00Z",
                  "expected_call_ids": ["call-1"],
                  "completeness_assertion": {"complete": complete, "basis": "host reported all calls before cutoff"}},
        "agent_roster": [{"id": "worker-1", "role": "implementer"}],
        "calls": [{"call_id": "call-1", "agent": {"id": "worker-1", "role": "implementer"},
                   "model": "model-a", "regime": {"mode": "standard", "source": "observed"}, "usage": usage}],
    }


def valid_pricing():
    return {
        "schema_version": 1,
        "snapshot": {"version": "fictional-2026-09", "as_of": "2026-09-19", "source_url": "https://example.invalid/pricing"},
        "models": {"model-a": {"input_usd_per_million": "2", "cached_input_usd_per_million": "0.5", "output_usd_per_million": "10"},
                   "astra-demo": {"input_usd_per_million": "3", "cached_input_usd_per_million": "1", "output_usd_per_million": "12"}},
    }


class CostReceiptTests(unittest.TestCase):
    def test_complete_receipt_uses_decimal_and_does_not_double_count_reasoning(self):
        result = receipt.calculate(valid_input(), valid_pricing())
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["observed_subset"]["cost_usd"], "2.7")
        self.assertEqual(result["full_scope_estimate"]["cost_usd"], "2.7")
        self.assertEqual(result["observed_subset"]["usage"]["reasoning_output_tokens"], 50_000)

    def test_unknown_usage_and_partial_assertion_never_complete_the_scope(self):
        source = valid_input(complete=False)
        source["calls"][0]["usage"] = None
        result = receipt.calculate(source, valid_pricing())
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["scope"]["coverage_complete"])
        self.assertIsNone(result["full_scope_estimate"]["cost_usd"])

        source = valid_input(complete=False)
        result = receipt.calculate(source, valid_pricing())
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["observed_subset"]["cost_usd"], "2.7")
        self.assertEqual(result["full_scope_estimate"]["status"], "unavailable")

    def test_missing_call_and_missing_rate_are_honest_gaps(self):
        source = valid_input()
        source["scope"]["expected_call_ids"].append("call-2")
        result = receipt.calculate(source, valid_pricing())
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["scope"]["unavailable_calls"][0]["reason"], "call_record_missing")
        self.assertIsNone(result["full_scope_estimate"]["cost_usd"])

        prices = valid_pricing()
        del prices["models"]["model-a"]["output_usd_per_million"]
        result = receipt.calculate(valid_input(), prices)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("missing_rates", result["scope"]["unavailable_calls"][0]["reason"])

    def test_duplicate_and_non_atomic_aggregates_are_rejected(self):
        source = valid_input()
        source["calls"].append(dict(source["calls"][0]))
        with self.assertRaisesRegex(receipt.ReceiptError, "duplicate atomic call_id"):
            receipt.calculate(source, valid_pricing())
        source = valid_input()
        source["calls"][0]["usage"]["scope"] = "worker_lifetime"
        with self.assertRaisesRegex(receipt.ReceiptError, "atomic_call"):
            receipt.calculate(source, valid_pricing())
        source = valid_input()
        source["calls"][0]["usage"]["parent_inclusive"] = False
        with self.assertRaisesRegex(receipt.ReceiptError, "parent_inclusive"):
            receipt.calculate(source, valid_pricing())

    def test_counts_and_rates_reject_bool_nan_and_bad_subsets(self):
        source = valid_input()
        source["calls"][0]["usage"]["input_tokens"] = True
        with self.assertRaises(receipt.ReceiptError):
            receipt.calculate(source, valid_pricing())
        source = valid_input()
        source["calls"][0]["usage"]["cached_input_tokens"] = 1_000_001
        with self.assertRaisesRegex(receipt.ReceiptError, "cannot exceed"):
            receipt.calculate(source, valid_pricing())
        source = valid_input()
        source["calls"][0]["usage"]["reasoning_output_tokens"] = 100_001
        with self.assertRaisesRegex(receipt.ReceiptError, "cannot exceed"):
            receipt.calculate(source, valid_pricing())
        prices = valid_pricing()
        prices["models"]["model-a"]["input_usd_per_million"] = "NaN"
        with self.assertRaisesRegex(receipt.ReceiptError, "finite"):
            receipt.calculate(valid_input(), prices)
        source = valid_input()
        source["scope"]["cutoff"] = "sometime later"
        with self.assertRaisesRegex(receipt.ReceiptError, "ISO-8601"):
            receipt.calculate(source, valid_pricing())

    def test_unsupported_regimes_are_rejected(self):
        for regime in ({"mode": "batch"}, {"mode": "standard", "cache_write_tokens": 0},
                       {"mode": "standard", "tier": "priority"}, {"mode": "standard", "context": "long"}):
            source = valid_input()
            source["calls"][0]["regime"] = regime
            with self.subTest(regime=regime), self.assertRaisesRegex(receipt.ReceiptError, "unsupported|standard"):
                receipt.calculate(source, valid_pricing())
        source = valid_input()
        source["calls"][0]["usage"]["cache_write_tokens"] = 0
        with self.assertRaisesRegex(receipt.ReceiptError, "unsupported"):
            receipt.calculate(source, valid_pricing())

    def test_unknown_metadata_and_omitted_regime_are_rejected(self):
        for location, field, value in (
            ("call", "service_tier", "priority"),
            ("call", "aggregation", "parent_inclusive"),
            ("call", "usage_kind", "estimated"),
            ("input", "extension", {"anything": True}),
        ):
            source = valid_input()
            target = source["calls"][0] if location == "call" else source
            target[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(receipt.ReceiptError, "unsupported"):
                receipt.calculate(source, valid_pricing())
        source = valid_input()
        del source["calls"][0]["regime"]
        with self.assertRaisesRegex(receipt.ReceiptError, "is required"):
            receipt.calculate(source, valid_pricing())
        prices = valid_pricing()
        prices["currency"] = "EUR"
        with self.assertRaisesRegex(receipt.ReceiptError, "pricing contains unsupported"):
            receipt.calculate(valid_input(), prices)
        prices = valid_pricing()
        prices["models"]["model-a"]["context"] = "large"
        with self.assertRaisesRegex(receipt.ReceiptError, "unsupported"):
            receipt.calculate(valid_input(), prices)

    def test_roster_coverage_and_duplicate_agent_id_are_not_ignored(self):
        source = valid_input()
        source["agent_roster"].append({"id": "coordinator-1", "role": "reviewer"})
        result = receipt.calculate(source, valid_pricing())
        self.assertFalse(result["scope"]["coverage_complete"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["scope"]["unavailable_agents"], [{
            "id": "coordinator-1", "role": "reviewer", "reason": "agent_has_no_call_record",
        }])
        source = valid_input()
        source["agent_roster"].append({"id": "worker-1", "role": "reviewer"})
        with self.assertRaisesRegex(receipt.ReceiptError, "duplicate agent id"):
            receipt.calculate(source, valid_pricing())

    def test_null_counters_and_rates_are_unknown_while_zero_remains_measured(self):
        source = valid_input()
        del source["calls"][0]["usage"]["cached_input_tokens"]
        result = receipt.calculate(source, valid_pricing())
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("missing_usage", result["scope"]["unavailable_calls"][0]["reason"])
        source = valid_input()
        source["calls"][0]["usage"]["cached_input_tokens"] = None
        result = receipt.calculate(source, valid_pricing())
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("missing_usage", result["scope"]["unavailable_calls"][0]["reason"])
        prices = valid_pricing()
        prices["models"]["model-a"]["cached_input_usd_per_million"] = None
        result = receipt.calculate(valid_input(), prices)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("missing_rates", result["scope"]["unavailable_calls"][0]["reason"])
        source = valid_input()
        source["calls"][0]["usage"].update({
            "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_output_tokens": 0,
        })
        result = receipt.calculate(source, valid_pricing())
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["observed_subset"]["cost_usd"], "0")

    def test_same_token_repricing_requires_complete_coverage_and_never_claims_savings(self):
        source = valid_input()
        source["astra_repricing"] = {"model": "astra-demo"}
        result = receipt.calculate(source, valid_pricing())
        reprice = result["astra_same_token_repricing"]
        self.assertEqual(reprice["status"], "available")
        self.assertEqual(reprice["cost_usd"], "3.8")
        self.assertIn("does not measure all-Astra savings", reprice["limitation"])
        source = valid_input(complete=False)
        source["astra_repricing"] = {"model": "astra-demo"}
        self.assertEqual(receipt.calculate(source, valid_pricing())["astra_same_token_repricing"]["status"], "unavailable")

    def test_assumed_standard_regime_is_retained_in_output(self):
        source = valid_input()
        source["calls"][0]["regime"]["source"] = "assumed"
        result = receipt.calculate(source, valid_pricing())
        self.assertEqual(result["assumptions"], [{
            "call_id": "call-1", "kind": "standard_regime_eligibility", "value": "standard",
        }])

    def test_complete_usage_can_reprice_when_source_rates_are_missing(self):
        source = valid_input()
        source["astra_repricing"] = {"model": "astra-demo"}
        prices = valid_pricing()
        del prices["models"]["model-a"]["output_usd_per_million"]
        result = receipt.calculate(source, prices)
        self.assertTrue(result["scope"]["coverage_complete"])
        self.assertEqual(result["full_scope_estimate"]["status"], "unavailable")
        self.assertEqual(result["astra_same_token_repricing"]["status"], "available")

    def test_cli_returns_json_errors_and_partial_json_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path, pricing_path = root / "input.json", root / "pricing.json"
            input_path.write_text(json.dumps(valid_input(complete=False)), encoding="utf-8")
            pricing_path.write_text(json.dumps(valid_pricing()), encoding="utf-8")
            completed = subprocess.run([sys.executable, str(MODULE_PATH), str(input_path), "--pricing", str(pricing_path)],
                                       text=True, capture_output=True, check=False)
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(json.loads(completed.stdout)["status"], "partial")
            input_path.write_text("[]", encoding="utf-8")
            invalid = subprocess.run([sys.executable, str(MODULE_PATH), str(input_path), "--pricing", str(pricing_path)],
                                     text=True, capture_output=True, check=False)
            self.assertEqual(invalid.returncode, 2)
            self.assertEqual(json.loads(invalid.stdout)["status"], "error")
            malformed = valid_input()
            malformed["calls"][0]["regime"]["source"] = []
            input_path.write_text(json.dumps(malformed), encoding="utf-8")
            invalid_type = subprocess.run(
                [sys.executable, str(MODULE_PATH), str(input_path), "--pricing", str(pricing_path)],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(invalid_type.returncode, 2)
            self.assertEqual(json.loads(invalid_type.stdout)["status"], "error")
            self.assertEqual(invalid_type.stderr, "")


if __name__ == "__main__":
    unittest.main()
