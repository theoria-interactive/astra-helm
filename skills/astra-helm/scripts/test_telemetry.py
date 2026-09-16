#!/usr/bin/env python3
"""Tests for the consent-gated minimized telemetry client."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import uuid

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import telemetry  # noqa: E402


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config_path = self.root / "telemetry-config.json"
        self.state_path = self.root / ".telemetry-state.json"
        self.logs = self.root / "logs"
        self.logs.mkdir()
        self.endpoint = "https://example.test/v1/events"
        self.evidence_path = self.root / "consent-evidence.json"
        self.evidence = {
            "prompt": "May Astra Helm automatically send the disclosed minimized telemetry?",
            "response": "Yes, enable automatic sharing.",
            "source": "explicit user response in this task",
        }
        self.evidence_path.write_text(json.dumps(self.evidence), encoding="utf-8")
        self.write_config(self.endpoint)

    def tearDown(self):
        self.temporary.cleanup()

    def write_config(self, endpoint, disclosure="1", retention=30):
        self.config_path.write_text(json.dumps({
            "schema_version": 1, "endpoint": endpoint,
            "disclosure_version": disclosure, "retention_days": retention,
        }), encoding="utf-8")

    def invoke(self, *arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = telemetry.main(["--config", str(self.config_path), "--state", str(self.state_path), *arguments])
        return code, json.loads(output.getvalue())

    def consent(self, at="2026-01-02T00:00:00Z"):
        state = telemetry.empty_state()
        state["consent"] = {
            "enabled": True, "consented_at": at, "endpoint": self.endpoint,
            "disclosure_version": "1", "retention_days": 30,
            "automatic_sending": True, "evidence": dict(self.evidence),
        }
        telemetry.save_state(self.state_path, state)

    def journal(self, *, started="2026-01-03T00:00:00Z", kind="execution",
                task_type="feature", risk="low", model="gpt-5.6-terra", effort="high",
                depends_on=None, usage=None, coordinator_usage=None, routing=None,
                outcome="completed", blocker_reasons=None, delivered_work_status=None,
                secret="SENTINEL-secret-project-path-prompt-code-url"):
        run_id = str(uuid.uuid4())
        start = {
            "schema_version": 1, "run_id": run_id, "timestamp": started, "event": "start",
            "skill_hash": "a" * 64, "policy": {"version": "1.5.0", "secret": secret},
            "data": {"project": secret, "task_summary": secret, "task_type": task_type,
                     "risk": risk, "kind": kind, "source_path": secret},
        }
        dispatch_data = {"assignment_id": secret, "model": model, "effort": effort,
                         "reason": secret, "depends_on": [] if depends_on is None else depends_on}
        if routing is not None:
            dispatch_data["routing_assessment"] = routing
        records = [start, {
            "schema_version": 1, "run_id": run_id, "timestamp": "2026-01-03T00:00:01Z",
            "event": "dispatch", "data": dispatch_data,
        }]
        if usage is not None:
            records.append({"schema_version": 1, "run_id": run_id, "timestamp": "2026-01-03T00:00:02Z",
                            "event": "runtime", "data": {"assignment_id": secret, "source": secret,
                            "actual_model": model, "actual_effort": effort, "usage": usage}})
        if coordinator_usage is not None:
            records.append({"schema_version": 1, "run_id": run_id, "timestamp": "2026-01-03T00:00:03Z",
                            "event": "runtime", "data": {"coordinator": True, "source": secret,
                            "actual_model": None, "actual_effort": None, "usage": coordinator_usage}})
        finish_data = {"outcome": outcome, "summary": secret}
        if blocker_reasons is not None:
            finish_data["blocker_reasons"] = blocker_reasons
        if delivered_work_status is not None:
            finish_data["delivered_work_status"] = delivered_work_status
        records.extend([{
            "schema_version": 1, "run_id": run_id, "timestamp": "2026-01-03T00:00:04Z",
            "event": "review", "data": {"assignment_id": secret, "verdict": "accepted", "findings": []},
        }, {
            "schema_version": 1, "run_id": run_id, "timestamp": "2026-01-03T00:00:05Z",
            "event": "finish", "data": finish_data,
        }])
        (self.logs / f"{run_id}.jsonl").write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
        return run_id

    def test_no_consent_means_no_network_and_null_endpoint_cannot_opt_in(self):
        run_id = self.journal()
        with mock.patch.object(telemetry, "submit_once") as send:
            code, result = self.invoke("submit", "--log-root", str(self.logs), "--run-id", run_id)
        self.assertEqual(code, 0)
        self.assertFalse(result["ok"])
        self.assertIn("--approve-run", result["reason"])
        send.assert_not_called()
        self.write_config(None)
        code, result = self.invoke(
            "submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run",
        )
        self.assertEqual(code, 0)
        self.assertIn("endpoint", result["reason"])

    def test_one_run_approval_sends_only_the_named_closed_execution_run(self):
        earlier = self.journal(started="2025-12-30T00:00:00Z")
        later = self.journal(task_type="bugfix")
        with mock.patch.object(telemetry, "submit_once", return_value=202) as send:
            code, result = self.invoke(
                "submit", "--log-root", str(self.logs), "--run-id", earlier, "--approve-run",
            )
            code_later, later_result = self.invoke(
                "submit", "--log-root", str(self.logs), "--run-id", later,
            )
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "sent")
        self.assertEqual(code_later, 0)
        self.assertFalse(later_result["ok"])
        self.assertIn("--approve-run", later_result["reason"])
        self.assertEqual(send.call_count, 1)
        state = telemetry.load_state(self.state_path)
        self.assertEqual(state["runs"][earlier]["approval"]["scope"], "one_run")
        self.assertNotIn(later, state["runs"])

    def test_one_run_approval_reuses_frozen_payload_for_retries(self):
        run_id = self.journal()
        current = [dt.datetime(2026, 1, 4, tzinfo=dt.timezone.utc)]
        with mock.patch.object(telemetry, "utc_now", side_effect=lambda: current[0]), \
             mock.patch.object(telemetry, "submit_once", side_effect=[telemetry.TelemetryError("failed"), 202]) as send:
            first = self.invoke(
                "submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run",
            )
            current[0] += dt.timedelta(minutes=2)
            bare_retry = self.invoke("submit", "--log-root", str(self.logs), "--run-id", run_id)
            retry = self.invoke(
                "submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run",
            )
        self.assertEqual(first[1]["status"], "delivery_failed")
        self.assertIn("--approve-run", bare_retry[1]["reason"])
        self.assertEqual(retry[1]["status"], "sent")
        self.assertEqual(send.call_count, 2)
        state = telemetry.load_state(self.state_path)
        self.assertEqual(state["runs"][run_id]["attempts"], 2)
        self.assertIn("payload", state["runs"][run_id])

    def test_one_run_renewal_preserves_delivery_state_and_sent_runs_stay_idempotent(self):
        run_id = self.journal()
        current = [dt.datetime(2026, 1, 4, tzinfo=dt.timezone.utc)]
        with mock.patch.object(telemetry, "utc_now", side_effect=lambda: current[0]), \
             mock.patch.object(telemetry, "submit_once", side_effect=telemetry.TelemetryError("failed")):
            _code, failed = self.invoke("submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run")
        before = telemetry.load_state(self.state_path)["runs"][run_id]
        event_id, frozen_payload = before["event_id"], before["payload"]
        self.write_config(self.endpoint, disclosure="2")
        current[0] += dt.timedelta(minutes=2)
        with mock.patch.object(telemetry, "utc_now", side_effect=lambda: current[0]), \
             mock.patch.object(telemetry, "submit_once", return_value=202) as send:
            _code, blocked = self.invoke("submit", "--log-root", str(self.logs), "--run-id", run_id)
            _code, renewed = self.invoke(
                "submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run",
            )
            self.write_config(self.endpoint, disclosure="3")
            _code, bare_duplicate = self.invoke("submit", "--log-root", str(self.logs), "--run-id", run_id)
            _code, duplicate = self.invoke(
                "submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run",
            )
        self.assertEqual(failed["status"], "delivery_failed")
        self.assertIn("--approve-run", blocked["reason"])
        self.assertEqual(renewed["status"], "sent")
        self.assertEqual(renewed["event_id"], event_id)
        after = telemetry.load_state(self.state_path)["runs"][run_id]
        self.assertEqual(after["attempts"], 2)
        self.assertEqual(after["payload"], frozen_payload)
        self.assertIn("--approve-run", bare_duplicate["reason"])
        self.assertEqual(duplicate["status"], "already_sent")
        send.assert_called_once()

    def test_preview_inspects_an_unapproved_closed_run_without_persisting_consent(self):
        run_id = self.journal()
        with mock.patch.object(telemetry, "submit_once") as send:
            code, preview = self.invoke("preview", "--log-root", str(self.logs), "--run-id", run_id)
        self.assertEqual(code, 0)
        self.assertEqual(preview["status"], "preview")
        self.assertEqual(preview["payload"]["task_type"], "feature")
        send.assert_not_called()
        self.assertFalse(self.state_path.exists())

    def test_preview_reuses_a_known_frozen_payload_after_a_failed_one_run_delivery(self):
        run_id = self.journal(task_type="feature")
        with mock.patch.object(telemetry, "submit_once", side_effect=telemetry.TelemetryError("failed")):
            self.invoke("submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run")
        path = self.logs / f"{run_id}.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        records[0]["data"]["task_type"] = "bugfix"
        path.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
        code, preview = self.invoke("preview", "--log-root", str(self.logs), "--run-id", run_id)
        self.assertEqual(code, 0)
        self.assertEqual(preview["payload"]["task_type"], "feature")

    def test_one_run_approval_rejects_open_or_nonexecution_runs_and_overrides_saved_optout(self):
        open_run = self.journal()
        open_path = self.logs / f"{open_run}.jsonl"
        lines = open_path.read_text(encoding="utf-8").splitlines()
        open_path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
        nonexecution = self.journal(kind="test")
        with mock.patch.object(telemetry, "submit_once", return_value=202) as send:
            _code, open_result = self.invoke(
                "submit", "--log-root", str(self.logs), "--run-id", open_run, "--approve-run",
            )
            _code, test_result = self.invoke(
                "submit", "--log-root", str(self.logs), "--run-id", nonexecution, "--approve-run",
            )
            self.invoke("configure", "--consent", "off")
            declined_run = self.journal()
            _code, declined_result = self.invoke(
                "submit", "--log-root", str(self.logs), "--run-id", declined_run, "--approve-run",
            )
        self.assertIn("incomplete", open_result["reason"])
        self.assertIn("not eligible", test_result["reason"])
        self.assertEqual(declined_result["status"], "sent")
        send.assert_called_once()

    def test_configure_on_and_ask_are_disabled_without_reading_evidence(self):
        for choice in ("on", "ask"):
            with self.subTest(choice=choice):
                code, result = self.invoke("configure", "--consent", choice)
                self.assertEqual(code, 0)
                self.assertFalse(result["ok"])
                self.assertIn("submit --approve-run", result["reason"])
        code, result = self.invoke(
            "configure", "--consent", "on", "--consent-evidence-file", str(self.evidence_path),
        )
        self.assertEqual(code, 0)
        self.assertIn("no longer accepted", result["reason"])
        self.assertFalse(self.state_path.exists())

    def test_legacy_enabled_state_requires_confirmation_and_never_sends(self):
        state = telemetry.empty_state()
        state["consent"] = {
            "enabled": True, "consented_at": "2026-01-02T00:00:00Z", "endpoint": self.endpoint,
            "disclosure_version": "1", "retention_days": 30,
        }
        telemetry.save_state(self.state_path, state)
        code, status = self.invoke("status")
        self.assertEqual(code, 0)
        self.assertEqual(status["decision"], "explicit_only")
        self.assertEqual(status["reason"], "explicit_run_approval_required")
        run_id = self.journal()
        with mock.patch.object(telemetry, "submit_once") as send:
            code, result = self.invoke("submit", "--log-root", str(self.logs), "--run-id", run_id)
        self.assertEqual(code, 0)
        self.assertFalse(result["ok"])
        self.assertIn("--approve-run", result["reason"])
        send.assert_not_called()

    def test_explicit_off_is_declined_and_needs_no_evidence(self):
        code, result = self.invoke("configure", "--consent", "off")
        self.assertEqual(code, 0)
        self.assertEqual(result["decision"], "declined")
        self.assertFalse(result["automatic_sending"])
        code, error = self.invoke(
            "configure", "--consent", "off", "--consent-evidence-file", str(self.evidence_path),
        )
        self.assertEqual(code, 0)
        self.assertFalse(error["ok"])

    def test_ask_mode_cannot_replace_legacy_state(self):
        self.consent()
        before = self.state_path.read_bytes()
        code, result = self.invoke("configure", "--consent", "ask")
        self.assertEqual(code, 0)
        self.assertFalse(result["ok"])
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_preview_has_strict_allowlist_and_no_sentinel_leakage(self):
        self.consent()
        usage = {"measurement_id": "worker-turn-1", "scope": "worker_turn", "source": "secret",
                 "input_tokens": 10, "cached_input_tokens": 5, "output_tokens": 4,
                 "reasoning_output_tokens": 2}
        run_id = self.journal(usage=usage, routing={"contract_clarity": "clear",
                              "cross_component_coupling": "low", "state_and_concurrency": "high"})
        code, result = self.invoke("preview", "--log-root", str(self.logs), "--run-id", run_id)
        self.assertEqual(code, 0)
        encoded = json.dumps(result)
        self.assertNotIn("SENTINEL", encoded)
        self.assertNotIn("assignment_id", encoded)
        payload = result["payload"]
        self.assertEqual(set(payload), {"schema_version", "event_id", "policy_version", "task_type", "risk",
                         "outcome", "worker_count", "dependency_count", "routes", "coordinator_usage",
                         "coordinator_usage_reason", "contract_clarity", "coupling", "state_concurrency"})
        self.assertEqual(payload["routes"][0]["usage"]["input_tokens"], 10)
        self.assertIsNone(payload["coordinator_usage"])
        self.assertEqual(payload["coordinator_usage_reason"], "no_measurements")

    def test_consent_receipt_never_enters_wire_payload(self):
        self.consent()
        run_id = self.journal()
        bodies = []

        def capture(_endpoint, body):
            bodies.append(body.decode("utf-8"))
            return 202

        with mock.patch.object(telemetry, "submit_once", side_effect=capture):
            code, result = self.invoke(
                "submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run",
            )
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "sent")
        encoded = bodies[0]
        for value in self.evidence.values():
            self.assertNotIn(value, encoded)
        self.assertNotIn("authorization_receipt", encoded)
        self.assertNotIn("automatic_sending", encoded)

    def test_legacy_consent_state_is_readable_and_not_rewritten_by_status(self):
        self.consent()
        original = self.state_path.read_bytes()
        for endpoint, disclosure, retention in (("https://other.test/v1/events", "1", 30),
                                                (self.endpoint, "2", 30), (self.endpoint, "1", 31)):
            self.write_config(endpoint, disclosure, retention)
            code, result = self.invoke("status")
            self.assertEqual(code, 0)
            self.assertEqual(result["decision"], "explicit_only")
            self.assertFalse(result["automatic_sending"])
            self.assertEqual(self.state_path.read_bytes(), original)

    def test_legacy_automatic_consent_does_not_authorize_bare_submit(self):
        self.consent()
        before = self.journal(started="2026-01-01T00:00:00Z")
        code, result = self.invoke("submit", "--log-root", str(self.logs), "--run-id", before)
        self.assertEqual(code, 0)
        self.assertIn("--approve-run", result["reason"])
        for kind in ("test", "tuning", "synthetic"):
            run_id = self.journal(kind=kind)
            code, rejected = self.invoke(
                "submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run",
            )
            self.assertEqual(code, 0)
            self.assertIn("not eligible", rejected["reason"])

    def test_one_run_approval_can_cover_a_preautomatic_consent_run(self):
        self.consent()
        before = self.journal(started="2026-01-01T00:00:00Z")
        with mock.patch.object(telemetry, "submit_once", return_value=202) as send:
            _code, result = self.invoke(
                "submit", "--log-root", str(self.logs), "--run-id", before, "--approve-run",
            )
        self.assertEqual(result["status"], "sent")
        send.assert_called_once()

    def test_saved_approval_and_optout_do_not_authorize_bare_retry(self):
        run_id = self.journal()
        with mock.patch.object(telemetry, "submit_once", side_effect=telemetry.TelemetryError("delivery failed")) as send:
            code, result = self.invoke(
                "submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run",
            )
        self.assertEqual(code, 0)
        self.assertEqual(result["attempts"], 1)
        self.invoke("configure", "--consent", "off")
        with mock.patch.object(telemetry, "submit_once") as send_after:
            code, bare = self.invoke("submit", "--log-root", str(self.logs), "--run-id", run_id)
        self.assertEqual(code, 0)
        self.assertIn("--approve-run", bare["reason"])
        send_after.assert_not_called()
        self.assertEqual(send.call_count, 1)

    def test_duplicate_submit_is_idempotent(self):
        self.consent()
        run_id = self.journal()
        with mock.patch.object(telemetry, "submit_once", return_value=202) as send:
            first = self.invoke(
                "submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run",
            )
            second = self.invoke(
                "submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run",
            )
        self.assertEqual(first[1]["status"], "sent")
        self.assertEqual(second[1]["status"], "already_sent")
        self.assertEqual(send.call_count, 1)
        self.assertEqual(first[1]["event_id"], second[1]["event_id"])

    def test_one_valid_legacy_receipt_authorizes_no_bare_runs(self):
        self.consent()
        run_ids = [self.journal(), self.journal(task_type="bugfix")]
        with mock.patch.object(telemetry, "submit_once", return_value=202) as send:
            results = [
                self.invoke("submit", "--log-root", str(self.logs), "--run-id", run_id)[1]
                for run_id in run_ids
            ]
        self.assertTrue(all("--approve-run" in result["reason"] for result in results))
        self.assertEqual(send.call_count, 0)
        status = self.invoke("status")[1]
        self.assertEqual(status["decision"], "explicit_only")
        self.assertFalse(status["automatic_sending"])

    def test_decline_persists_when_endpoint_is_removed(self):
        self.invoke("configure", "--consent", "off")
        self.write_config(None)
        code, result = self.invoke("status")
        self.assertEqual(code, 0)
        self.assertEqual(result["decision"], "declined")
        self.assertEqual(result["reason"], "consent_off")
        self.assertFalse(result["automatic_sending"])

    def test_retry_limit_is_three_and_backoff_is_persisted(self):
        self.consent()
        run_id = self.journal()
        current = [dt.datetime(2026, 1, 4, tzinfo=dt.timezone.utc)]
        with mock.patch.object(telemetry, "utc_now", side_effect=lambda: current[0]), \
             mock.patch.object(telemetry, "submit_once", side_effect=telemetry.TelemetryError("secret body")) as send:
            first = self.invoke("submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run")
            blocked = self.invoke("submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run")
            current[0] += dt.timedelta(minutes=2)
            second = self.invoke("submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run")
            current[0] += dt.timedelta(minutes=10)
            third = self.invoke("submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run")
            fourth = self.invoke("submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run")
        self.assertEqual(blocked[1]["status"], "backoff")
        self.assertEqual(third[1]["status"], "retry_limit_reached")
        self.assertEqual(fourth[1]["status"], "retry_limit_reached")
        self.assertEqual(send.call_count, 3)
        self.assertNotIn("secret body", json.dumps(third))

    def test_usage_overlap_or_incomplete_counters_is_null(self):
        self.consent()
        wrong_scope = {"measurement_id": "whole-worker", "scope": "worker_lifetime", "source": "x",
                       "input_tokens": 10, "cached_input_tokens": 5, "output_tokens": 4,
                       "reasoning_output_tokens": 2}
        run_id = self.journal(usage=wrong_scope)
        code, result = self.invoke("preview", "--log-root", str(self.logs), "--run-id", run_id)
        self.assertEqual(code, 0)
        self.assertIsNone(result["payload"]["routes"][0]["usage"])
        self.assertEqual(result["payload"]["routes"][0]["usage_reason"], "unsupported_scope")
        incomplete = {"measurement_id": "one-turn", "scope": "worker_turn", "source": "x", "input_tokens": 10}
        run_id = self.journal(usage=incomplete)
        code, result = self.invoke("preview", "--log-root", str(self.logs), "--run-id", run_id)
        self.assertEqual(code, 0)
        self.assertIsNone(result["payload"]["routes"][0]["usage"])
        self.assertEqual(result["payload"]["routes"][0]["usage_reason"], "incomplete_counters")

    def test_multiple_or_mixed_missing_usage_is_never_summed(self):
        self.consent()
        one = {"measurement_id": "turn-one", "scope": "worker_turn", "source": "x",
               "input_tokens": 10, "cached_input_tokens": 5, "output_tokens": 4,
               "reasoning_output_tokens": 2}
        run_id = self.journal(usage=one)
        path = self.logs / f"{run_id}.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        runtime = next(item for item in records if item["event"] == "runtime")
        second = json.loads(json.dumps(runtime))
        second["timestamp"] = "2026-01-03T00:00:03Z"
        second["data"]["usage"]["measurement_id"] = "turn-two"
        records.insert(-2, second)
        path.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
        code, result = self.invoke("preview", "--log-root", str(self.logs), "--run-id", run_id)
        self.assertEqual(code, 0)
        route = result["payload"]["routes"][0]
        self.assertIsNone(route["usage"])
        self.assertEqual(route["usage_reason"], "conflicting_measurements")

        records.pop(-3)
        missing = json.loads(json.dumps(runtime))
        missing["timestamp"] = "2026-01-03T00:00:03Z"
        missing["data"]["usage"] = None
        records.insert(-2, missing)
        path.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
        code, result = self.invoke("preview", "--log-root", str(self.logs), "--run-id", run_id)
        self.assertEqual(code, 0)
        route = result["payload"]["routes"][0]
        self.assertIsNone(route["usage"])
        self.assertEqual(route["usage_reason"], "incomplete_counters")

    def test_first_attempt_is_persisted_and_payload_frozen_before_network(self):
        self.consent()
        run_id = self.journal(task_type="feature")
        with mock.patch.object(telemetry, "submit_once", side_effect=RuntimeError("simulated crash")):
            with self.assertRaises(RuntimeError):
                self.invoke(
                    "submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run",
                )
        state = telemetry.load_state(self.state_path)
        frozen = state["runs"][run_id]
        self.assertEqual(frozen["attempts"], 1)
        self.assertEqual(frozen["payload"]["task_type"], "feature")

        path = self.logs / f"{run_id}.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        records[0]["data"]["task_type"] = "bugfix"
        path.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
        sent_bodies = []

        def capture(_endpoint, body):
            sent_bodies.append(json.loads(body))
            return 202

        with mock.patch.object(telemetry, "submit_once", side_effect=capture):
            code, result = self.invoke(
                "submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run",
            )
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "sent")
        self.assertEqual(sent_bodies[0]["task_type"], "feature")
        self.assertEqual(sent_bodies[0]["event_id"], frozen["event_id"])

    def test_invalid_raw_strings_map_to_unknown_without_zero_fabrication(self):
        self.consent()
        run_id = self.journal(task_type="private free text", risk="catastrophic",
                              model="private-model", effort="private-effort")
        code, result = self.invoke("preview", "--log-root", str(self.logs), "--run-id", run_id)
        self.assertEqual(code, 0)
        payload = result["payload"]
        self.assertEqual(payload["task_type"], "unknown")
        self.assertEqual(payload["risk"], "unknown")
        self.assertEqual(payload["routes"][0]["model"], "unknown")
        self.assertEqual(payload["routes"][0]["effort"], "unknown")
        self.assertIsNone(payload["routes"][0]["usage"])
        self.assertNotEqual(payload["routes"][0]["usage"], {key: 0 for key in telemetry.USAGE_KEYS})

    def test_correction_rounds_count_each_changes_requested_review_once(self):
        run_id = self.journal()
        path = self.logs / f"{run_id}.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        accepted = next(record for record in records if record["event"] == "review")
        corrections = []
        for offset, kind in enumerate(("functional", "both", None), 1):
            review = json.loads(json.dumps(accepted))
            review["timestamp"] = f"2026-01-03T00:00:0{offset}Z"
            review["data"]["verdict"] = "changes_requested"
            if kind is not None:
                review["data"]["correction_kind"] = kind
            corrections.append(review)
        accepted["timestamp"] = "2026-01-03T00:00:04Z"
        records[2:-1] = corrections + [accepted]
        payload = telemetry.build_payload(records, str(uuid.uuid4()))
        route = payload["routes"][0]
        self.assertEqual(route["functional_corrections"], 2)
        self.assertEqual(route["quality_corrections"], 1)
        self.assertEqual(route["unclassified_corrections"], 1)
        self.assertEqual(route["correction_rounds"], 3)
        self.assertEqual(route["final_verdict"], "accepted")

    def test_correction_rounds_are_optional_and_internally_bounded(self):
        run_id = self.journal()
        payload = telemetry.build_payload(telemetry.load_run(self.logs, run_id), str(uuid.uuid4()))
        legacy = json.loads(json.dumps(payload))
        del legacy["routes"][0]["correction_rounds"]
        telemetry.validate_wire_payload(legacy)

        route = payload["routes"][0]
        route.update({
            "functional_corrections": 1,
            "quality_corrections": 1,
            "unclassified_corrections": 1,
        })
        for rounds in (-1, 1, 4, telemetry.MAX_CORRECTION_COUNT + 1):
            malformed = json.loads(json.dumps(payload))
            malformed["routes"][0]["correction_rounds"] = rounds
            with self.subTest(rounds=rounds), self.assertRaises(telemetry.TelemetryError):
                telemetry.validate_wire_payload(malformed)
        payload["routes"][0]["correction_rounds"] = 2
        telemetry.validate_wire_payload(payload)

    def test_assignment_dispositions_map_only_from_matching_finish_assignments(self):
        run_id = self.journal()
        records = telemetry.load_run(self.logs, run_id)
        first_assignment = records[1]["data"]["assignment_id"]
        second_assignment = "SECOND-SENTINEL-assignment-id"
        second_dispatch = json.loads(json.dumps(records[1]))
        second_dispatch["data"]["assignment_id"] = second_assignment
        second_review = json.loads(json.dumps(records[2]))
        second_review["data"].update({"assignment_id": second_assignment, "verdict": "blocked"})
        records[1:3] = [records[1], second_dispatch, records[2], second_review]
        finish = records[-1]["data"]
        finish["assignment_dispositions"] = {
            first_assignment: "superseded",
            second_assignment: "cancelled",
            "UNMATCHED-SENTINEL-assignment-id": "private free text",
        }

        payload = telemetry.build_payload(records, str(uuid.uuid4()))
        self.assertEqual(
            [route["assignment_disposition"] for route in payload["routes"]],
            ["superseded", "cancelled"],
        )
        self.assertEqual([route["final_verdict"] for route in payload["routes"]], ["accepted", "blocked"])
        encoded = json.dumps(payload)
        self.assertNotIn("SENTINEL", encoded)
        self.assertNotIn("assignment_id", encoded)
        self.assertNotIn("private free text", encoded)

    def test_invalid_or_missing_assignment_dispositions_are_omitted_and_frozen_legacy_payloads_validate(self):
        run_id = self.journal()
        records = telemetry.load_run(self.logs, run_id)
        assignment_id = records[1]["data"]["assignment_id"]
        finish = records[-1]["data"]
        for dispositions in (None, {assignment_id: "private free text"}, {assignment_id: {}}, []):
            with self.subTest(dispositions=dispositions):
                finish["assignment_dispositions"] = dispositions
                payload = telemetry.build_payload(records, str(uuid.uuid4()))
                self.assertNotIn("assignment_disposition", payload["routes"][0])

        legacy = telemetry.build_payload(records, str(uuid.uuid4()))
        legacy["routes"][0].pop("assignment_disposition", None)
        telemetry.validate_wire_payload(legacy)

    def test_legacy_frozen_payload_without_correction_rounds_is_retried_unchanged(self):
        run_id = self.journal(task_type="feature")
        current = [dt.datetime(2026, 1, 4, tzinfo=dt.timezone.utc)]
        with mock.patch.object(telemetry, "utc_now", side_effect=lambda: current[0]), \
             mock.patch.object(telemetry, "submit_once", side_effect=telemetry.TelemetryError("failed")):
            self.invoke(
                "submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run",
            )
        state = telemetry.load_state(self.state_path)
        del state["runs"][run_id]["payload"]["routes"][0]["correction_rounds"]
        state["runs"][run_id]["payload"]["routes"][0].pop("assignment_disposition", None)
        frozen_payload = json.loads(json.dumps(state["runs"][run_id]["payload"]))
        telemetry.save_state(self.state_path, state)
        path = self.logs / f"{run_id}.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assignment_id = next(record for record in records if record["event"] == "dispatch")["data"]["assignment_id"]
        next(record for record in records if record["event"] == "finish")["data"]["assignment_dispositions"] = {
            assignment_id: "cancelled",
        }
        path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
        current[0] += dt.timedelta(minutes=2)
        bodies = []

        def capture(_endpoint, body):
            bodies.append(json.loads(body))
            return 202

        with mock.patch.object(telemetry, "utc_now", side_effect=lambda: current[0]), \
             mock.patch.object(telemetry, "submit_once", side_effect=capture):
            _code, result = self.invoke(
                "submit", "--log-root", str(self.logs), "--run-id", run_id, "--approve-run",
            )
        self.assertEqual(result["status"], "sent")
        self.assertNotIn("correction_rounds", bodies[0]["routes"][0])
        self.assertNotIn("assignment_disposition", bodies[0]["routes"][0])
        self.assertEqual(bodies[0], frozen_payload)
        self.assertEqual(result["event_id"], frozen_payload["event_id"])

    def test_wire_numeric_and_semver_bounds(self):
        self.consent()
        oversized = {"measurement_id": "worker-turn", "scope": "worker_turn", "source": "x",
                     "input_tokens": telemetry.MAX_TOKEN_COUNT + 1, "cached_input_tokens": 0,
                     "output_tokens": 0, "reasoning_output_tokens": 0}
        run_id = self.journal(usage=oversized)
        code, result = self.invoke("preview", "--log-root", str(self.logs), "--run-id", run_id)
        self.assertEqual(code, 0)
        self.assertIsNone(result["payload"]["routes"][0]["usage"])
        self.assertEqual(result["payload"]["routes"][0]["usage_reason"], "incomplete_counters")
        path = self.logs / f"{run_id}.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        records[0]["policy"]["version"] = "1" * 40 + ".2.3"
        path.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
        code, result = self.invoke("preview", "--log-root", str(self.logs), "--run-id", run_id)
        self.assertEqual(code, 0)
        self.assertIsNone(result["payload"]["policy_version"])

    def test_explicit_outcome_categories_are_transmitted_and_legacy_remains_absent(self):
        self.consent()
        run_id = self.journal(
            outcome="blocked",
            blocker_reasons=["external_approval", "environment_limitation"],
            delivered_work_status="not_reviewed",
        )
        code, result = self.invoke("preview", "--log-root", str(self.logs), "--run-id", run_id)
        self.assertEqual(code, 0)
        payload = result["payload"]
        self.assertEqual(payload["blocker_reasons"], ["external_approval", "environment_limitation"])
        self.assertEqual(payload["delivered_work_status"], "not_reviewed")

        legacy_id = self.journal(secret="blocked by verification gap but accepted")
        code, result = self.invoke("preview", "--log-root", str(self.logs), "--run-id", legacy_id)
        self.assertEqual(code, 0)
        self.assertNotIn("blocker_reasons", result["payload"])
        self.assertNotIn("delivered_work_status", result["payload"])

    def test_source_outcome_categories_are_filtered_without_type_errors(self):
        run_id = self.journal()
        path = self.logs / f"{run_id}.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        finish = next(record for record in records if record["event"] == "finish")
        for reasons, status, expected_status in (
            ([{}], "accepted", "accepted"),
            (["private free text"], [], None),
        ):
            finish["data"]["blocker_reasons"] = reasons
            finish["data"]["delivered_work_status"] = status
            payload = telemetry.build_payload(records, str(uuid.uuid4()))
            self.assertNotIn("blocker_reasons", payload)
            if expected_status is None:
                self.assertNotIn("delivered_work_status", payload)
            else:
                self.assertEqual(payload["delivered_work_status"], expected_status)

    def test_frozen_payload_validation_is_strict_for_outcome_categories(self):
        run_id = self.journal(outcome="blocked", blocker_reasons=["verification_gap"],
                              delivered_work_status="accepted")
        records = telemetry.load_run(self.logs, run_id)
        payload = telemetry.build_payload(records, str(uuid.uuid4()))
        telemetry.validate_wire_payload(payload)
        for key, value in (
            ("blocker_reasons", ["verification_gap", "verification_gap"]),
            ("blocker_reasons", [{}]),
            ("delivered_work_status", "private free text"),
            ("delivered_work_status", {}),
        ):
            malformed = {**payload, key: value}
            with self.subTest(key=key, value=value), self.assertRaises(telemetry.TelemetryError):
                telemetry.validate_wire_payload(malformed)

        invalid_outcome = {**payload, "outcome": "completed"}
        with self.assertRaises(telemetry.TelemetryError):
            telemetry.validate_wire_payload(invalid_outcome)

    def test_frozen_payload_rejects_invalid_assignment_disposition(self):
        run_id = self.journal()
        payload = telemetry.build_payload(telemetry.load_run(self.logs, run_id), str(uuid.uuid4()))
        for disposition in ("private free text", "accepted", None, {}):
            malformed = json.loads(json.dumps(payload))
            malformed["routes"][0]["assignment_disposition"] = disposition
            with self.subTest(disposition=disposition), self.assertRaises(telemetry.TelemetryError):
                telemetry.validate_wire_payload(malformed)


if __name__ == "__main__":
    unittest.main()
