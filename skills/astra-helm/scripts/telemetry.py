#!/usr/bin/env python3
"""Consent-gated, minimized telemetry export for one finished Astra Helm run."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
from pathlib import Path
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

import journal

try:
    import fcntl
except ImportError:  # pragma: no cover - Astra Helm targets macOS/Linux.
    fcntl = None

SCHEMA_VERSION = 1
MAX_REQUEST_BYTES = 32 * 1024
MAX_RESPONSE_BYTES = 4 * 1024
MAX_JOURNAL_BYTES = 2 * 1024 * 1024
MAX_ROUTES = 64
MAX_ATTEMPTS = 3
MAX_TOKEN_COUNT = 1_000_000_000_000
MAX_CORRECTION_COUNT = 1000
MAX_POLICY_VERSION_LENGTH = 32
MAX_ENDPOINT_LENGTH = 2048
MAX_CONSENT_EVIDENCE_BYTES = 64 * 1024
MAX_CONSENT_PROMPT_LENGTH = 8192
MAX_CONSENT_RESPONSE_LENGTH = 2048
MAX_CONSENT_SOURCE_LENGTH = 1024
TIMEOUT_SECONDS = 5.0
BACKOFF_SECONDS = (60, 300, 1800)
SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = SKILL_ROOT / "telemetry-config.json"
DEFAULT_STATE = SKILL_ROOT / ".telemetry-state.json"

TASK_TYPES = {"feature", "bugfix", "refactor", "mechanical", "investigation"}
RISKS = {"low", "medium", "high"}
OUTCOMES = {"completed", "blocked", "cancelled", "failed"}
MODELS = {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}
EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}
VERDICTS = {"accepted", "changes_requested", "blocked"}
BLOCKER_REASONS = {
    "pending_decision", "external_approval", "environment_limitation",
    "unresolved_defect", "verification_gap",
}
DELIVERED_WORK_STATUSES = {"accepted", "changes_requested", "not_reviewed"}
USAGE_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
USAGE_REASONS = {"no_measurements", "unsupported_scope", "incomplete_counters", "conflicting_measurements"}
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class TelemetryError(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def timestamp(value: object) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(dt.timezone.utc)


def timestamp_text(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def read_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TelemetryError(f"cannot read {label}") from exc
    if not isinstance(value, dict):
        raise TelemetryError(f"{label} must be a JSON object")
    return value


def read_consent_evidence(path: Path) -> dict:
    try:
        if path.is_symlink():
            raise TelemetryError("consent evidence file may not be a symbolic link")
        with path.open("rb") as handle:
            raw = handle.read(MAX_CONSENT_EVIDENCE_BYTES + 1)
        if len(raw) > MAX_CONSENT_EVIDENCE_BYTES:
            raise TelemetryError("consent evidence file exceeds the local processing limit")
        value = json.loads(raw)
    except TelemetryError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TelemetryError("cannot read consent evidence file") from exc
    return validate_consent_evidence(value)


def validate_consent_evidence(value: object) -> dict:
    limits = {
        "prompt": MAX_CONSENT_PROMPT_LENGTH,
        "response": MAX_CONSENT_RESPONSE_LENGTH,
        "source": MAX_CONSENT_SOURCE_LENGTH,
    }
    if not isinstance(value, dict) or set(value) != set(limits):
        raise TelemetryError("consent evidence must contain exactly prompt, response, and source")
    evidence: dict[str, str] = {}
    for key, limit in limits.items():
        item = value[key]
        if not isinstance(item, str) or not item.strip() or len(item) > limit:
            raise TelemetryError(f"consent evidence {key} must be a non-empty string of at most {limit} characters")
        evidence[key] = item
    return evidence


def validate_endpoint(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TelemetryError("configured endpoint must be a string or null")
    if len(value) > MAX_ENDPOINT_LENGTH:
        raise TelemetryError("configured endpoint is too long")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise TelemetryError("configured endpoint is not a valid HTTPS URL") from exc
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment):
        raise TelemetryError("configured endpoint must be an HTTPS URL without credentials, query, or fragment")
    if port not in (None, 443):
        raise TelemetryError("configured endpoint must use the default HTTPS port")
    return value


def load_config(path: Path) -> dict:
    config = read_object(path, "telemetry config")
    if config.get("schema_version") != SCHEMA_VERSION:
        raise TelemetryError("unsupported telemetry config schema")
    disclosure = config.get("disclosure_version")
    retention = config.get("retention_days")
    if not isinstance(disclosure, str) or not disclosure:
        raise TelemetryError("configured disclosure_version must be a non-empty string")
    if isinstance(retention, bool) or not isinstance(retention, int) or retention <= 0:
        raise TelemetryError("configured retention_days must be a positive integer")
    return {
        "schema_version": SCHEMA_VERSION,
        "endpoint": validate_endpoint(config.get("endpoint")),
        "disclosure_version": disclosure,
        "retention_days": retention,
    }


def empty_state() -> dict:
    return {"schema_version": SCHEMA_VERSION, "consent": None, "runs": {}}


def load_state(path: Path) -> dict:
    if not path.exists():
        return empty_state()
    state = read_object(path, "telemetry state")
    if state.get("schema_version") != SCHEMA_VERSION:
        raise TelemetryError("unsupported telemetry state schema")
    consent, runs = state.get("consent"), state.get("runs")
    if consent is not None and not isinstance(consent, dict):
        raise TelemetryError("telemetry state consent is malformed")
    if not isinstance(runs, dict):
        raise TelemetryError("telemetry state runs is malformed")
    return {"schema_version": SCHEMA_VERSION, "consent": consent, "runs": runs}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", closefd=False) as handle:
            json.dump(state, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(fd)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        os.close(fd)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@contextlib.contextmanager
def state_lock(path: Path):
    """Serialize consent and delivery changes across helper invocations."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(".telemetry-lock") if path == DEFAULT_STATE else path.with_name(path.name + ".lock")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.fchmod(fd, 0o600)
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def consent_matches(state: dict, config: dict) -> bool:
    consent = state.get("consent")
    try:
        evidence_valid = validate_consent_evidence(consent.get("evidence")) if isinstance(consent, dict) else None
    except TelemetryError:
        evidence_valid = None
    return bool(
        isinstance(consent, dict)
        and consent.get("enabled") is True
        and consent.get("automatic_sending") is True
        and evidence_valid is not None
        and timestamp(consent.get("consented_at")) is not None
        and consent.get("endpoint") == config["endpoint"]
        and consent.get("disclosure_version") == config["disclosure_version"]
        and consent.get("retention_days") == config["retention_days"]
        and config["endpoint"] is not None
    )


def opted_out(state: dict) -> bool:
    """An explicit local refusal applies to every one-run submission too."""
    consent = state.get("consent")
    return bool(
        isinstance(consent, dict)
        and consent.get("invalidated") is not True
        and (consent.get("mode") == "off" or (consent.get("mode") is None and consent.get("enabled") is False))
    )


def run_approval_matches(run_state: object, config: dict) -> bool:
    """Validate a one-run authorization bound to the current public disclosure."""
    if not isinstance(run_state, dict):
        return False
    approval = run_state.get("approval")
    return bool(
        isinstance(approval, dict)
        and approval.get("scope") == "one_run"
        and timestamp(approval.get("approved_at")) is not None
        and approval.get("endpoint") == config["endpoint"]
        and approval.get("disclosure_version") == config["disclosure_version"]
        and approval.get("retention_days") == config["retention_days"]
        and config["endpoint"] is not None
    )


def invalidate_changed_consent(state: dict, config: dict, now: dt.datetime) -> bool:
    consent = state.get("consent")
    if not isinstance(consent, dict) or consent.get("enabled") is not True:
        return False
    binding_matches = (
        consent.get("endpoint") == config["endpoint"]
        and consent.get("disclosure_version") == config["disclosure_version"]
        and consent.get("retention_days") == config["retention_days"]
        and config["endpoint"] is not None
    )
    if binding_matches:
        return False
    consent["enabled"] = False
    consent["automatic_sending"] = False
    consent["invalidated"] = True
    consent["invalidated_at"] = timestamp_text(now)
    return True


def public_status(config: dict, state: dict) -> dict:
    consent = state.get("consent")
    configured = config["endpoint"] is not None
    enabled = consent_matches(state, config)
    reason = None
    decision = "authorized" if enabled else "unset"
    if isinstance(consent, dict) and (consent.get("invalidated") is True
                                     or consent.get("enabled") is True and not enabled):
        decision = "renewal_required"
        if consent.get("enabled") is True and "evidence" not in consent:
            reason = "legacy_consent_requires_confirmation"
        elif consent.get("invalidated") is True:
            reason = "consent_invalidated"
        else:
            reason = "consent_receipt_invalid"
    elif isinstance(consent, dict) and consent.get("mode") == "ask":
        decision = "ask"
        reason = "selective_run_approval"
    elif opted_out(state):
        decision = "declined"
        reason = "consent_off"
    elif not configured:
        reason = "endpoint_not_configured"
    result = {
        "ok": True,
        "configured": configured,
        "consent": "on" if enabled else "off",
        "decision": decision,
        "reason": reason,
        "endpoint": config["endpoint"],
        "disclosure_version": config["disclosure_version"],
        "retention_days": config["retention_days"],
        "automatic_sending": enabled,
    }
    if enabled:
        result["authorization_receipt"] = {
            **consent["evidence"],
            "consented_at": consent["consented_at"],
            "endpoint": consent["endpoint"],
            "disclosure_version": consent["disclosure_version"],
            "retention_days": consent["retention_days"],
        }
    return result


def configure(config: dict, state: dict, choice: str, now: dt.datetime,
              evidence: dict | None = None) -> dict:
    if choice == "on":
        if config["endpoint"] is None:
            raise TelemetryError("cannot opt in until an HTTPS endpoint is configured")
        if evidence is None:
            raise TelemetryError("--consent-evidence-file is required when enabling automatic telemetry")
        evidence = validate_consent_evidence(evidence)
        if consent_matches(state, config):
            return public_status(config, state)
        state["consent"] = {
            "enabled": True,
            "mode": "automatic",
            "automatic_sending": True,
            "consented_at": timestamp_text(now),
            "endpoint": config["endpoint"],
            "disclosure_version": config["disclosure_version"],
            "retention_days": config["retention_days"],
            "evidence": evidence,
        }
    elif choice == "off":
        if evidence is not None:
            raise TelemetryError("consent evidence is not accepted when disabling telemetry")
        state["consent"] = {
            "enabled": False,
            "mode": "off",
            "automatic_sending": False,
            "disabled_at": timestamp_text(now),
            "endpoint": config["endpoint"],
            "disclosure_version": config["disclosure_version"],
            "retention_days": config["retention_days"],
        }
    else:
        if evidence is not None:
            raise TelemetryError("consent evidence is not accepted when selecting per-run approval")
        state["consent"] = {
            "enabled": False,
            "mode": "ask",
            "automatic_sending": False,
            "selected_at": timestamp_text(now),
            "endpoint": config["endpoint"],
            "disclosure_version": config["disclosure_version"],
            "retention_days": config["retention_days"],
        }
    return public_status(config, state)


def canonical_run_id(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise TelemetryError("run-id must be a canonical lowercase UUID") from exc
    if str(parsed) != value:
        raise TelemetryError("run-id must be a canonical lowercase UUID")
    return value


def load_run(log_root: Path, run_id: str) -> list[dict]:
    run_id = canonical_run_id(run_id)
    path = log_root / f"{run_id}.jsonl"
    try:
        if path.is_symlink():
            raise TelemetryError("symbolic-link journals are not eligible")
        if path.stat().st_size > MAX_JOURNAL_BYTES:
            raise TelemetryError("journal exceeds local processing limit")
        with path.open("r", encoding="utf-8") as handle:
            records, warnings = journal.parse_lines(handle)
    except FileNotFoundError as exc:
        raise TelemetryError("run does not exist") from exc
    except (OSError, UnicodeError) as exc:
        raise TelemetryError("cannot read run journal") from exc
    if warnings or not records:
        raise TelemetryError("run journal is corrupt")
    skill_hash = records[0].get("skill_hash")
    if (records[0].get("schema_version") != SCHEMA_VERSION or records[0].get("event") != "start"
            or records[0].get("run_id") != run_id or timestamp(records[0].get("timestamp")) is None
            or not isinstance(skill_hash, str) or len(skill_hash) != 64):
        raise TelemetryError("run journal is corrupt")
    try:
        journal.validate_start(records[0].get("data"))
    except (journal.JournalError, AttributeError, TypeError) as exc:
        raise TelemetryError("run journal is corrupt") from exc
    seen_finish = False
    finish_count = 0
    measurements: set[str] = set()
    for record in records[1:]:
        event, data = record.get("event"), record.get("data")
        if (record.get("schema_version") != SCHEMA_VERSION or record.get("run_id") != run_id
                or event not in journal.EVENTS or not isinstance(data, dict)
                or timestamp(record.get("timestamp")) is None):
            raise TelemetryError("run journal is corrupt")
        try:
            journal.validate_event(event, data)
        except journal.JournalError as exc:
            raise TelemetryError("run journal is corrupt") from exc
        if seen_finish and event not in journal.POST_FINISH_EVENTS:
            raise TelemetryError("run journal is corrupt")
        if event == "finish":
            finish_count += 1
            seen_finish = True
        if event == "runtime" and isinstance(data.get("usage"), dict):
            measurement_id = data["usage"]["measurement_id"]
            if measurement_id in measurements:
                raise TelemetryError("run journal is corrupt")
            measurements.add(measurement_id)
    if finish_count != 1:
        raise TelemetryError("run is incomplete")
    return records


def mapped(value: object, allowed: set[str]) -> str:
    return value if isinstance(value, str) and value in allowed else "unknown"


def mapped_nullable(value: object, allowed: set[str]) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) and value in allowed else "unknown"


def usage_total(evidence: list[object], required_scope: str) -> tuple[dict | None, str | None]:
    if not evidence:
        return None, "no_measurements"
    if any(not isinstance(item, dict) for item in evidence):
        return None, "incomplete_counters"
    # The journal has no validated relationship for proving that two observations
    # are disjoint. A single turn-scoped measurement is the only safe total.
    if len(evidence) != 1:
        return None, "conflicting_measurements"
    if any(item.get("scope") != required_scope for item in evidence):
        return None, "unsupported_scope"
    identifiers = [item.get("measurement_id") for item in evidence]
    if any(not isinstance(item, str) or not item for item in identifiers) or len(set(identifiers)) != len(identifiers):
        return None, "conflicting_measurements"
    if any(any(isinstance(item.get(key), bool) or not isinstance(item.get(key), int)
               or item[key] < 0 or item[key] > MAX_TOKEN_COUNT for key in USAGE_KEYS) for item in evidence):
        return None, "incomplete_counters"
    totals = {key: sum(item[key] for item in evidence) for key in USAGE_KEYS}
    if totals["cached_input_tokens"] > totals["input_tokens"] or totals["reasoning_output_tokens"] > totals["output_tokens"]:
        return None, "conflicting_measurements"
    return totals, None


def bounded_integer(value: object, maximum: int) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and 0 <= value <= maximum


def validate_wire_usage(value: object, reason: object) -> None:
    if value is None:
        if reason not in USAGE_REASONS:
            raise TelemetryError("frozen telemetry payload is malformed")
        return
    if reason is not None or not isinstance(value, dict) or set(value) != set(USAGE_KEYS):
        raise TelemetryError("frozen telemetry payload is malformed")
    if not all(bounded_integer(value[key], MAX_TOKEN_COUNT) for key in USAGE_KEYS):
        raise TelemetryError("frozen telemetry payload is malformed")
    if value["cached_input_tokens"] > value["input_tokens"] or value["reasoning_output_tokens"] > value["output_tokens"]:
        raise TelemetryError("frozen telemetry payload is malformed")


def validate_wire_payload(payload: object) -> bytes:
    required = {
        "schema_version", "event_id", "policy_version", "task_type", "risk", "outcome",
        "worker_count", "dependency_count", "routes", "coordinator_usage", "coordinator_usage_reason",
    }
    optional = {
        "contract_clarity", "coupling", "state_concurrency",
        "blocker_reasons", "delivered_work_status",
    }
    if not isinstance(payload, dict) or not required.issubset(payload) or not set(payload).issubset(required | optional):
        raise TelemetryError("frozen telemetry payload is malformed")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise TelemetryError("frozen telemetry payload is malformed")
    try:
        parsed_id = uuid.UUID(payload["event_id"])
    except (ValueError, AttributeError, TypeError) as exc:
        raise TelemetryError("frozen telemetry payload is malformed") from exc
    if str(parsed_id) != payload["event_id"] or parsed_id.version != 4:
        raise TelemetryError("frozen telemetry payload is malformed")
    policy_version = payload["policy_version"]
    if policy_version is not None and (not isinstance(policy_version, str)
            or len(policy_version) > MAX_POLICY_VERSION_LENGTH or not SEMVER.fullmatch(policy_version)):
        raise TelemetryError("frozen telemetry payload is malformed")
    if payload["task_type"] not in TASK_TYPES | {"unknown"} or payload["risk"] not in RISKS | {"unknown"}:
        raise TelemetryError("frozen telemetry payload is malformed")
    if payload["outcome"] not in OUTCOMES | {"unknown"} or not bounded_integer(payload["worker_count"], MAX_ROUTES):
        raise TelemetryError("frozen telemetry payload is malformed")
    dependency_count = payload["dependency_count"]
    maximum_dependencies = payload["worker_count"] * (payload["worker_count"] - 1) // 2
    if dependency_count is not None and not bounded_integer(dependency_count, maximum_dependencies):
        raise TelemetryError("frozen telemetry payload is malformed")
    routes = payload["routes"]
    if not isinstance(routes, list) or len(routes) != payload["worker_count"]:
        raise TelemetryError("frozen telemetry payload is malformed")
    route_keys = {"model", "effort", "actual_model", "actual_effort", "functional_corrections",
                  "quality_corrections", "unclassified_corrections", "final_verdict", "usage", "usage_reason"}
    for route in routes:
        if not isinstance(route, dict) or set(route) != route_keys:
            raise TelemetryError("frozen telemetry payload is malformed")
        if route["model"] not in MODELS | {"unknown"} or route["effort"] not in EFFORTS | {"unknown"}:
            raise TelemetryError("frozen telemetry payload is malformed")
        if route["actual_model"] is not None and route["actual_model"] not in MODELS | {"unknown"}:
            raise TelemetryError("frozen telemetry payload is malformed")
        if route["actual_effort"] is not None and route["actual_effort"] not in EFFORTS | {"unknown"}:
            raise TelemetryError("frozen telemetry payload is malformed")
        if route["final_verdict"] not in VERDICTS | {"unknown"}:
            raise TelemetryError("frozen telemetry payload is malformed")
        for key in ("functional_corrections", "quality_corrections", "unclassified_corrections"):
            if not bounded_integer(route[key], MAX_CORRECTION_COUNT):
                raise TelemetryError("frozen telemetry payload is malformed")
        validate_wire_usage(route["usage"], route["usage_reason"])
    validate_wire_usage(payload["coordinator_usage"], payload["coordinator_usage_reason"])
    category_enums = {"contract_clarity": {"clear", "mixed", "unclear"},
                      "coupling": {"low", "medium", "high"},
                      "state_concurrency": {"low", "medium", "high"}}
    if any(key in payload and payload[key] not in allowed for key, allowed in category_enums.items()):
        raise TelemetryError("frozen telemetry payload is malformed")
    if "blocker_reasons" in payload:
        reasons = payload["blocker_reasons"]
        if (not isinstance(reasons, list)
                or any(not isinstance(reason, str) or reason not in BLOCKER_REASONS for reason in reasons)
                or len(reasons) != len(set(reasons))
                or (reasons and payload["outcome"] != "blocked")):
            raise TelemetryError("frozen telemetry payload is malformed")
    if "delivered_work_status" in payload:
        delivered_status = payload["delivered_work_status"]
        if not isinstance(delivered_status, str) or delivered_status not in DELIVERED_WORK_STATUSES:
            raise TelemetryError("frozen telemetry payload is malformed")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_REQUEST_BYTES:
        raise TelemetryError("minimized event exceeds request size limit")
    return encoded


def explicit_characteristics(dispatches: list[dict]) -> dict:
    aliases = {
        "contract_clarity": ("contract_clarity", {"clear", "mixed", "unclear"}),
        "coupling": ("cross_component_coupling", {"low", "medium", "high"}),
        "state_concurrency": ("state_and_concurrency", {"low", "medium", "high"}),
    }
    output = {}
    for wire_name, (journal_name, allowed) in aliases.items():
        values = []
        for dispatch in dispatches:
            assessment = dispatch["data"].get("routing_assessment")
            if isinstance(assessment, dict) and journal_name in assessment:
                values.append(assessment[journal_name])
        if (values and len(values) == len(dispatches) and all(isinstance(value, str) for value in values)
                and len(set(values)) == 1 and values[0] in allowed):
            output[wire_name] = values[0]
    return output


def build_payload(records: list[dict], event_id: str) -> dict:
    start, start_data = records[0], records[0]["data"]
    if start_data.get("kind", "execution") != "execution":
        raise TelemetryError("test, tuning, and synthetic runs are not eligible")
    dispatches = [record for record in records if record.get("event") == "dispatch"]
    if len(dispatches) > MAX_ROUTES:
        raise TelemetryError("run has too many routes")
    reviews = [record for record in records if record.get("event") == "review"]
    runtimes = [record for record in records if record.get("event") == "runtime"]
    finish = next(record for record in records if record.get("event") == "finish")

    routes = []
    for dispatch in dispatches:
        data = dispatch["data"]
        assignment_id = data["assignment_id"]
        relevant_reviews = [r["data"] for r in reviews if r["data"].get("assignment_id") == assignment_id]
        settings = [r["data"] for r in runtimes if r["data"].get("assignment_id") == assignment_id]
        actual_models = {item["actual_model"] for item in settings if item.get("actual_model") is not None}
        actual_efforts = {item["actual_effort"] for item in settings if item.get("actual_effort") is not None}
        actual_model = None if not actual_models else (next(iter(actual_models)) if len(actual_models) == 1 else "unknown")
        actual_effort = None if not actual_efforts else (next(iter(actual_efforts)) if len(actual_efforts) == 1 else "unknown")
        evidence = [item.get("usage") for item in settings]
        usage, usage_reason = usage_total(evidence, "worker_turn")
        counts = {"functional": 0, "quality": 0, "unclassified": 0}
        for review in relevant_reviews:
            if review.get("verdict") != "changes_requested":
                continue
            correction = review.get("correction_kind")
            if correction == "both":
                counts["functional"] += 1
                counts["quality"] += 1
            elif correction in ("functional", "quality"):
                counts[correction] += 1
            else:
                counts["unclassified"] += 1
        routes.append({
            "model": mapped(data.get("model"), MODELS),
            "effort": mapped(data.get("effort"), EFFORTS),
            "actual_model": mapped_nullable(actual_model, MODELS),
            "actual_effort": mapped_nullable(actual_effort, EFFORTS),
            "functional_corrections": counts["functional"],
            "quality_corrections": counts["quality"],
            "unclassified_corrections": counts["unclassified"],
            "final_verdict": mapped(relevant_reviews[-1].get("verdict") if relevant_reviews else None, VERDICTS),
            "usage": usage,
            "usage_reason": usage_reason,
        })

    dependencies = []
    reliable_dependencies = True
    seen_assignments: set[str] = set()
    for dispatch in dispatches:
        assignment_id = dispatch["data"]["assignment_id"]
        value = dispatch["data"].get("depends_on")
        if (assignment_id in seen_assignments or not isinstance(value, list)
                or any(not isinstance(item, str) or not item or item not in seen_assignments for item in value)
                or len(value) != len(set(value))):
            reliable_dependencies = False
            break
        dependencies.extend((assignment_id, item) for item in value)
        seen_assignments.add(assignment_id)

    coordinator = [item["data"].get("usage") for item in runtimes
                   if item["data"].get("coordinator") is True]
    coordinator_usage, coordinator_reason = usage_total(coordinator, "coordinator_turn")
    policy_version = start.get("policy", {}).get("version") if isinstance(start.get("policy"), dict) else None
    if (not isinstance(policy_version, str) or len(policy_version) > MAX_POLICY_VERSION_LENGTH
            or not SEMVER.fullmatch(policy_version)):
        policy_version = None
    payload = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "policy_version": policy_version,
        "task_type": mapped(start_data.get("task_type"), TASK_TYPES),
        "risk": mapped(start_data.get("risk"), RISKS),
        "outcome": mapped(finish["data"].get("outcome"), OUTCOMES),
        "worker_count": len(dispatches),
        "dependency_count": len(set(dependencies)) if reliable_dependencies else None,
        "routes": routes,
        "coordinator_usage": coordinator_usage,
        "coordinator_usage_reason": coordinator_reason,
    }
    payload.update(explicit_characteristics(dispatches))
    finish_data = finish.get("data")
    if isinstance(finish_data, dict):
        reasons = finish_data.get("blocker_reasons")
        if (isinstance(reasons, list)
                and all(isinstance(reason, str) and reason in BLOCKER_REASONS for reason in reasons)
                and len(reasons) == len(set(reasons))
                and (not reasons or payload["outcome"] == "blocked")):
            payload["blocker_reasons"] = reasons
        delivered_status = finish_data.get("delivered_work_status")
        if isinstance(delivered_status, str) and delivered_status in DELIVERED_WORK_STATUSES:
            payload["delivered_work_status"] = delivered_status
    validate_wire_payload(payload)
    return payload


def checked_event_id(run_state: dict) -> str:
    try:
        event_id = str(uuid.UUID(run_state["event_id"]))
    except (KeyError, ValueError, AttributeError) as exc:
        raise TelemetryError("telemetry state run entry is malformed") from exc
    if event_id != run_state["event_id"]:
        raise TelemetryError("telemetry state run entry is malformed")
    return event_id


def new_run_state() -> dict:
    return {"event_id": str(uuid.uuid4()), "attempts": 0, "next_retry_at": None, "sent": False}


def bind_one_run_approval(run_state: dict, config: dict, now: dt.datetime) -> None:
    """Renew only the authorization binding; delivery identity and retry state stay fixed."""
    run_state["approval"] = {
        "scope": "one_run",
        "approved_at": timestamp_text(now),
        "endpoint": config["endpoint"],
        "disclosure_version": config["disclosure_version"],
        "retention_days": config["retention_days"],
    }


def prepare(config: dict, state: dict, log_root: Path, run_id: str, now: dt.datetime,
            approve_run: bool = False, require_authorization: bool = True) -> tuple[dict, dict]:
    records = load_run(log_root, run_id)
    run_state = state["runs"].get(run_id)
    if run_state is not None and not isinstance(run_state, dict):
        raise TelemetryError("telemetry state run entry is malformed")
    if not require_authorization:
        if run_state is not None and run_state.get("payload") is not None:
            validate_wire_payload(run_state["payload"])
            return run_state["payload"], run_state
        event_id = checked_event_id(run_state) if run_state is not None else str(uuid.uuid4())
        return build_payload(records, event_id), run_state if run_state is not None else {"event_id": event_id}
    if run_state is not None and run_state.get("sent") is True:
        return build_payload(records, checked_event_id(run_state)), run_state

    automatic = consent_matches(state, config)
    one_run = run_approval_matches(run_state, config)
    if opted_out(state):
        raise TelemetryError("telemetry sharing is declined")
    if approve_run and not one_run:
        if config["endpoint"] is None:
            raise TelemetryError("cannot approve a run until an HTTPS endpoint is configured")
        if run_state is None:
            run_state = new_run_state()
            state["runs"][run_id] = run_state
        else:
            checked_event_id(run_state)
        bind_one_run_approval(run_state, config, now)
        one_run = True
    elif not automatic and not one_run:
        raise TelemetryError("this run has not been approved for telemetry")
    if automatic and not one_run:
        consent_time = timestamp(state["consent"]["consented_at"])
        if consent_time is None:
            raise TelemetryError("telemetry consent is off or invalidated")
        start_time = timestamp(records[0].get("timestamp"))
        if start_time is None:
            raise TelemetryError("run journal is corrupt")
        if start_time < consent_time:
            raise TelemetryError("run started before the current telemetry consent")
    if not isinstance(run_state, dict):
        run_state = new_run_state()
        state["runs"][run_id] = run_state
    payload = build_payload(records, checked_event_id(run_state))
    return payload, run_state


def submit_once(endpoint: str, body: bytes) -> int:
    request = urllib.request.Request(endpoint, data=body, headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "astra-helm-telemetry/1",
    }, method="POST")
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            content = response.read(MAX_RESPONSE_BYTES + 1)
            if len(content) > MAX_RESPONSE_BYTES:
                raise TelemetryError("response exceeded size limit")
            return response.status
    except urllib.error.HTTPError as exc:
        try:
            exc.read(MAX_RESPONSE_BYTES + 1)
        except Exception:
            pass
        return exc.code
    except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError, OSError) as exc:
        raise TelemetryError("delivery failed") from exc


def command_submit(config: dict, state: dict, state_path: Path,
                   log_root: Path, run_id: str, now: dt.datetime, approve_run: bool = False) -> dict:
    payload, run_state = prepare(config, state, log_root, run_id, now, approve_run)
    if run_state.get("sent") is True:
        return {"ok": True, "status": "already_sent", "event_id": run_state["event_id"]}
    attempts = run_state.get("attempts")
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
        raise TelemetryError("telemetry state run entry is malformed")
    if attempts >= MAX_ATTEMPTS:
        return {"ok": False, "status": "retry_limit_reached", "event_id": run_state["event_id"]}
    retry_at = timestamp(run_state.get("next_retry_at"))
    if retry_at is not None and now < retry_at:
        return {"ok": False, "status": "backoff", "event_id": run_state["event_id"],
                "retry_after_seconds": max(1, int((retry_at - now).total_seconds()))}
    frozen_payload = run_state.get("payload")
    if frozen_payload is None:
        run_state["payload"] = payload
        frozen_payload = payload
    body = validate_wire_payload(frozen_payload)
    run_state["attempts"] = attempts + 1
    # Persist the delivery ID, exact bytes, and attempt before any network I/O.
    save_state(state_path, state)
    try:
        status_code = submit_once(config["endpoint"], body)
        delivered = 200 <= status_code < 300
    except TelemetryError:
        status_code = None
        delivered = False
    if delivered:
        run_state["sent"] = True
        run_state["next_retry_at"] = None
        return {"ok": True, "status": "sent", "event_id": run_state["event_id"]}
    if run_state["attempts"] < MAX_ATTEMPTS:
        delay = BACKOFF_SECONDS[run_state["attempts"] - 1]
        run_state["next_retry_at"] = timestamp_text(now + dt.timedelta(seconds=delay))
        status = "delivery_failed"
    else:
        run_state["next_retry_at"] = None
        status = "retry_limit_reached"
    result = {"ok": False, "status": status, "event_id": run_state["event_id"],
              "attempts": run_state["attempts"]}
    if status_code is not None:
        result["http_status"] = status_code
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    result.add_argument("--state", type=Path, default=DEFAULT_STATE)
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    configure_parser = commands.add_parser("configure")
    configure_parser.add_argument("--consent", choices=("on", "off", "ask"), required=True)
    configure_parser.add_argument("--consent-evidence-file", type=Path)
    for name in ("preview", "submit"):
        selected = commands.add_parser(name)
        selected.add_argument("--log-root", type=Path, required=True)
        selected.add_argument("--run-id", required=True)
        if name == "submit":
            selected.add_argument("--approve-run", action="store_true",
                                  help="Submit this one closed run after its explicit user approval.")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = load_config(args.config)
        with state_lock(args.state):
            state = load_state(args.state)
            now = utc_now()
            changed = invalidate_changed_consent(state, config, now)
            if args.command == "status":
                result = public_status(config, state)
            elif args.command == "configure":
                evidence = None
                if args.consent == "on":
                    if config["endpoint"] is None:
                        raise TelemetryError("cannot opt in until an HTTPS endpoint is configured")
                    if args.consent_evidence_file is None:
                        raise TelemetryError("--consent-evidence-file is required when enabling automatic telemetry")
                    evidence = read_consent_evidence(args.consent_evidence_file)
                elif args.consent_evidence_file is not None:
                    raise TelemetryError("--consent-evidence-file is only valid with --consent on")
                result = configure(config, state, args.consent, now, evidence)
                changed = True
            elif args.command == "preview":
                payload, _run_state = prepare(config, state, args.log_root, args.run_id, now,
                                               require_authorization=False)
                result = {"ok": True, "status": "preview", "payload": payload}
            else:
                result = command_submit(config, state, args.state, args.log_root, args.run_id, now,
                                        args.approve_run)
                changed = True
            if changed:
                save_state(args.state, state)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except TelemetryError as exc:
        print(json.dumps({"ok": False, "status": "error", "reason": str(exc)},
                         sort_keys=True, separators=(",", ":")))
        return 0


if __name__ == "__main__":
    sys.exit(main())
