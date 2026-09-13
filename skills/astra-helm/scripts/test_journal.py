#!/usr/bin/env python3

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest


MODULE_PATH = Path(__file__).with_name("journal.py")
SPEC = importlib.util.spec_from_file_location("astra_helm_journal", MODULE_PATH)
journal = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(journal)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.skill = self.base / "skill"
        self.skill.mkdir()
        (self.skill / "SKILL.md").write_text("# test\n", encoding="utf-8")
        (self.skill / "policy.json").write_text('{"version":"test"}\n', encoding="utf-8")
        self.old_skill_root = journal.SKILL_ROOT
        journal.SKILL_ROOT = self.skill
        self.root = self.base / "logs"

    def tearDown(self):
        journal.SKILL_ROOT = self.old_skill_root
        self.temporary.cleanup()

    def start(self, root=None, kind="execution"):
        return journal.start_run(root or self.root, {
            "project": "project", "task_summary": "task", "task_type": "feature",
            "risk": "low", "kind": kind,
        })

    def dispatch(self, run_id, root=None):
        journal.append_event(root or self.root, run_id, "dispatch", {
            "assignment_id": "worker-1", "model": "requested-model",
            "effort": "medium", "reason": "bounded work",
        })

    def runtime(self, **updates):
        data = {
            "assignment_id": "worker-1", "source": "runtime result",
            "actual_model": "actual-model", "actual_effort": "high",
            "usage": {
                "measurement_id": "measure-1", "scope": "worker_turn",
                "source": "runtime result", "input_tokens": 10,
                "cached_input_tokens": 0, "output_tokens": 0,
                "reasoning_output_tokens": 0,
            },
        }
        data.update(updates)
        return data

    def test_register_root_and_missing_registered_root(self):
        missing = self.base / "missing"
        first = journal.register_root(self.root, missing)
        second = journal.register_root(self.root, missing / ".." / "missing")
        self.assertEqual(first["roots"], second["roots"])
        report = journal.summary(self.root, None, 30, [self.root, missing])
        self.assertEqual(report["log_roots"], [str(self.root.resolve()), str(missing.resolve())])
        self.assertTrue(any("registered root missing" in warning for warning in report["warnings"]))

    def test_identical_logs_are_deduplicated_across_roots(self):
        record = self.start()
        self.dispatch(record["run_id"])
        journal.append_event(self.root, record["run_id"], "finish", {"outcome": "completed"})
        other = self.base / "other"
        other.mkdir()
        shutil.copy2(self.root / f'{record["run_id"]}.jsonl', other)
        journal.register_root(self.root, other)
        report = journal.summary(self.root, None, 30)
        self.assertEqual(len(report["runs"]), 1)
        self.assertEqual(len(report["runs"][0]["duplicate_sources"]), 1)
        self.assertEqual(report["runs"][0]["source_path"], str((self.root / f'{record["run_id"]}.jsonl').resolve()))
        self.assertEqual(report["groups"][0]["dispatch_count"], 1)

    def test_conflicting_same_run_histories_are_visible_and_not_aggregated(self):
        record = self.start()
        self.dispatch(record["run_id"])
        other = self.base / "other"
        other.mkdir()
        copied = other / f'{record["run_id"]}.jsonl'
        shutil.copy2(self.root / copied.name, copied)
        with copied.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "schema_version": 1, "run_id": record["run_id"],
                "timestamp": journal.utc_now(), "event": "finish",
                "data": {"outcome": "completed"},
            }) + "\n")
        report = journal.summary(self.root, None, 30, [other])
        self.assertEqual(len(report["runs"]), 1)
        self.assertEqual(report["runs"][0]["outcome"], "conflict")
        self.assertTrue(report["runs"][0]["history_conflict"])
        self.assertEqual(len(report["runs"][0]["conflicting_sources"]), 2)
        self.assertEqual(report["groups"], [])
        self.assertTrue(any("conflicting histories" in warning for warning in report["warnings"]))

    def test_malformed_log_remains_visible_as_corrupt(self):
        record = self.start()
        path = self.root / f'{record["run_id"]}.jsonl'
        with path.open("a", encoding="utf-8") as handle:
            handle.write("not-json\n")
        report = journal.summary(self.root, None, 30)
        self.assertEqual(report["runs"][0]["outcome"], "corrupt")
        self.assertTrue(report["warnings"])

    def test_runtime_schema_validation_and_sourced_route(self):
        for invalid in (
            {**self.runtime(), "coordinator": True},
            {**self.runtime(), "assignment_id": None, "coordinator": None},
            {key: value for key, value in self.runtime().items() if key != "source"},
            {**self.runtime(), "actual_model": 1},
            {**self.runtime(), "usage": {"measurement_id": "x", "scope": "turn", "source": "r"}},
            {**self.runtime(), "usage": {"measurement_id": "x", "scope": "turn", "source": "r", "input_tokens": -1}},
            {**self.runtime(), "usage": {"measurement_id": "x", "scope": "turn", "source": "r", "input_tokens": 1, "cached_input_tokens": 2}},
            {**self.runtime(), "usage": {"measurement_id": "x", "scope": "turn", "source": "r", "output_tokens": 1, "reasoning_output_tokens": 2}},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(journal.JournalError):
                journal.validate_event("runtime", invalid)

        record = self.start()
        self.dispatch(record["run_id"])
        journal.append_event(self.root, record["run_id"], "runtime", self.runtime())
        journal.append_event(self.root, record["run_id"], "finish", {"outcome": "completed"})
        coordinator = {
            "coordinator": True, "source": "host runtime", "actual_model": None,
            "actual_effort": None, "usage": {
                "measurement_id": "coordinator-zero", "scope": "coordinator_turn",
                "source": "host runtime", "input_tokens": 0, "output_tokens": 0,
            },
        }
        journal.append_event(self.root, record["run_id"], "runtime", coordinator)
        row = journal.summary(self.root, None, 30)["runs"][0]
        route = row["routes"][0]
        self.assertEqual(route["settings_status"], "sourced")
        self.assertEqual(route["actual_model"], "actual-model")
        self.assertEqual(route["runtime_sources"], ["runtime result"])
        self.assertEqual(route["usage_evidence"][0]["output_tokens"], 0)
        self.assertEqual(row["usage_coverage"]["measurement_count"], 2)
        self.assertEqual(row["usage_coverage"]["targets_without_usage"], [])
        self.assertFalse(row["usage_coverage"]["overlapping_measurements_summed"])

    def test_unknown_runtime_values_and_usage_gap(self):
        record = self.start()
        self.dispatch(record["run_id"])
        unknown = self.runtime(actual_model=None, actual_effort=None, usage=None)
        journal.append_event(self.root, record["run_id"], "runtime", unknown)
        row = journal.summary(self.root, None, 30)["runs"][0]
        self.assertEqual(row["routes"][0]["settings_status"], "partial")
        self.assertIsNone(row["routes"][0]["actual_model"])
        self.assertEqual(row["usage_coverage"]["targets_without_usage"], ["coordinator", "worker-1"])

    def test_repeated_measurement_id_is_rejected_and_existing_duplicate_is_corrupt(self):
        record = self.start()
        journal.append_event(self.root, record["run_id"], "runtime", self.runtime())
        with self.assertRaisesRegex(journal.JournalError, "already exists"):
            journal.append_event(self.root, record["run_id"], "runtime", self.runtime(actual_model=None))
        path = self.root / f'{record["run_id"]}.jsonl'
        existing = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(existing) + "\n")
        row = journal.summary(self.root, None, 30)["runs"][0]
        self.assertEqual(row["outcome"], "corrupt")
        self.assertEqual(row["usage_coverage"]["measurement_count"], 1)

    def test_legacy_report_runtime_and_finish_usage_remain_readable(self):
        record = self.start()
        self.dispatch(record["run_id"])
        journal.append_event(self.root, record["run_id"], "report", {
            "assignment_id": "worker-1", "summary": "done",
            "actual_model": "legacy-model", "actual_effort": "low",
            "runtime_source": "legacy runtime result",
            "usage": {"scope": "worker_turn", "source": "legacy runtime result", "input_tokens": 0},
        })
        journal.append_event(self.root, record["run_id"], "finish", {
            "outcome": "completed", "usage": {"scope": "run", "source": "legacy", "input_tokens": 0},
        })
        row = journal.summary(self.root, None, 30)["runs"][0]
        self.assertEqual(row["routes"][0]["settings_status"], "sourced")
        self.assertEqual(row["routes"][0]["usage_evidence"][0]["input_tokens"], 0)
        self.assertEqual(row["usage"]["input_tokens"], 0)
        self.assertTrue(row["usage_coverage"]["legacy_finish_usage_present"])
        self.assertEqual(row["usage_coverage"]["targets_without_usage"], ["coordinator"])

    def test_malformed_legacy_report_usage_is_not_evidence(self):
        record = self.start()
        self.dispatch(record["run_id"])
        journal.append_event(self.root, record["run_id"], "report", {
            "assignment_id": "worker-1", "summary": "done",
            "actual_model": "legacy-model", "actual_effort": "low",
            "runtime_source": "legacy runtime result",
            "usage": {"scope": "worker_turn", "source": "legacy runtime result", "input_tokens": -1},
        })
        report = journal.summary(self.root, None, 30)
        row = report["runs"][0]
        self.assertEqual(row["routes"][0]["settings_status"], "sourced")
        self.assertEqual(row["routes"][0]["usage_evidence"], [])
        self.assertIn("worker-1", row["usage_coverage"]["targets_without_usage"])
        self.assertTrue(any("ignored malformed legacy report usage" in item for item in report["warnings"]))

    def test_finish_outcome_metadata_is_validated_and_exposed(self):
        record = self.start()
        journal.append_event(self.root, record["run_id"], "finish", {
            "outcome": "blocked",
            "blocker_reasons": ["pending_decision", "verification_gap"],
            "delivered_work_status": "changes_requested",
        })
        row = journal.summary(self.root, None, 30)["runs"][0]
        self.assertEqual(row["blocker_reasons"], ["pending_decision", "verification_gap"])
        self.assertEqual(row["delivered_work_status"], "changes_requested")

        for data in (
            {"outcome": "blocked", "blocker_reasons": "verification_gap"},
            {"outcome": "blocked", "blocker_reasons": ["private free text"]},
            {"outcome": "blocked", "blocker_reasons": ["verification_gap", "verification_gap"]},
            {"outcome": "completed", "blocker_reasons": ["verification_gap"]},
            {"outcome": "completed", "delivered_work_status": "private free text"},
            {"outcome": "completed", "delivered_work_status": {}},
        ):
            with self.subTest(data=data), self.assertRaises(journal.JournalError):
                journal.validate_event("finish", data)

        journal.validate_event("finish", {"outcome": "completed", "blocker_reasons": []})

    def test_legacy_finish_summary_omits_outcome_metadata(self):
        record = self.start()
        journal.append_event(self.root, record["run_id"], "finish", {"outcome": "completed"})
        row = journal.summary(self.root, None, 30)["runs"][0]
        self.assertNotIn("blocker_reasons", row)
        self.assertNotIn("delivered_work_status", row)

    def test_summary_audits_latest_review_at_accepted_closure(self):
        record = self.start()
        self.dispatch(record["run_id"])
        journal.append_event(self.root, record["run_id"], "review", {
            "assignment_id": "worker-1", "verdict": "accepted", "findings": [],
        })
        journal.append_event(self.root, record["run_id"], "review", {
            "assignment_id": "worker-1", "verdict": "changes_requested", "findings": ["regression"],
        })
        journal.append_event(self.root, record["run_id"], "finish", {
            "outcome": "completed", "delivered_work_status": "accepted",
        })
        report = journal.summary(self.root, None, 30)
        route = report["runs"][0]["routes"][0]
        self.assertEqual(route["latest_review"]["verdict"], "changes_requested")
        self.assertIsNone(route["assignment_disposition"])
        self.assertTrue(any("accepted closure has unresolved assignment worker-1" in warning
                            for warning in report["warnings"]))

    def test_explicit_assignment_disposition_resolves_closure_without_inventing_review(self):
        record = self.start()
        self.dispatch(record["run_id"])
        journal.append_event(self.root, record["run_id"], "finish", {
            "outcome": "completed", "delivered_work_status": "accepted",
            "assignment_dispositions": {"worker-1": "superseded"},
        })
        report = journal.summary(self.root, None, 30)
        route = report["runs"][0]["routes"][0]
        self.assertIsNone(route["latest_review"])
        self.assertEqual(route["assignment_disposition"], "superseded")
        self.assertEqual(report["runs"][0]["assignment_dispositions"], {"worker-1": "superseded"})
        self.assertFalse(any("unresolved assignment" in warning for warning in report["warnings"]))

    def test_assignment_dispositions_are_validated_and_unknown_ids_are_warned(self):
        for value in (
            [], {"": "cancelled"}, {"worker-1": "accepted"},
            {f"worker-{index}": "cancelled" for index in range(journal.MAX_ASSIGNMENT_DISPOSITIONS + 1)},
        ):
            with self.subTest(value=value), self.assertRaises(journal.JournalError):
                journal.validate_event("finish", {
                    "outcome": "cancelled", "assignment_dispositions": value,
                })

        record = self.start()
        journal.append_event(self.root, record["run_id"], "finish", {
            "outcome": "cancelled", "assignment_dispositions": {"unknown-worker": "cancelled"},
        })
        report = journal.summary(self.root, None, 30)
        self.assertTrue(any("unknown assignment: unknown-worker" in warning
                            for warning in report["warnings"]))


if __name__ == "__main__":
    unittest.main()
