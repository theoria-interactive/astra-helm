#!/usr/bin/env python3
"""Append-only orchestration journal for the Astra Helm skill."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

try:
    import fcntl
except ImportError:  # pragma: no cover - Astra Helm currently targets macOS/Linux.
    fcntl = None


SCHEMA_VERSION = 1
MAX_RECORD_BYTES = 16 * 1024
EVENTS = {"dispatch", "report", "review", "replan", "runtime", "finish", "feedback", "policy_change"}
POST_FINISH_EVENTS = {"runtime", "feedback", "policy_change"}
FINISH_OUTCOMES = {"completed", "blocked", "cancelled", "failed"}
REVIEW_VERDICTS = {"accepted", "changes_requested", "blocked"}
BLOCKER_REASONS = {
    "pending_decision", "external_approval", "environment_limitation",
    "unresolved_defect", "verification_gap",
}
DELIVERED_WORK_STATUSES = {"accepted", "changes_requested", "not_reviewed"}
ASSIGNMENT_DISPOSITIONS = {"superseded", "cancelled"}
MAX_ASSIGNMENT_DISPOSITIONS = 64
SKILL_ROOT = Path(__file__).resolve().parent.parent


class JournalError(ValueError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def load_json_object(path: str, label: str = "data file") -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JournalError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise JournalError(f"{label} must contain a JSON object")
    encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_RECORD_BYTES:
        raise JournalError(f"{label} exceeds {MAX_RECORD_BYTES} UTF-8 bytes")
    return value


def require(data: dict, names: tuple[str, ...]) -> None:
    missing = [name for name in names if name not in data]
    if missing:
        raise JournalError("missing required field(s): " + ", ".join(missing))


def validate_uuid(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise JournalError("run-id must be a canonical UUID") from exc
    canonical = str(parsed)
    if value != canonical:
        raise JournalError("run-id must be a lowercase canonical UUID")
    return canonical


def validate_start(data: dict) -> dict:
    require(data, ("project", "task_summary", "task_type", "risk"))
    for name in ("project", "task_summary", "task_type", "risk"):
        if not isinstance(data[name], str) or not data[name].strip():
            raise JournalError(f"{name} must be a non-empty string")
    result = dict(data)
    result.setdefault("kind", "execution")
    if not isinstance(result["kind"], str) or not result["kind"].strip():
        raise JournalError("kind must be a non-empty string")
    coordinator = result.setdefault("coordinator", {})
    if not isinstance(coordinator, dict):
        raise JournalError("coordinator must be an object")
    coordinator = dict(coordinator)
    for name in ("requested_model", "actual_model", "requested_effort", "actual_effort"):
        coordinator.setdefault(name, None)
        if coordinator[name] is not None and not isinstance(coordinator[name], str):
            raise JournalError(f"coordinator.{name} must be a string or null")
    result["coordinator"] = coordinator
    return result


def validate_event(event: str, data: dict) -> None:
    required = {
        "dispatch": ("assignment_id", "model", "effort", "reason"),
        "report": ("assignment_id", "summary"),
        "review": ("assignment_id", "verdict", "findings"),
        "runtime": (),
        "finish": ("outcome",),
        "replan": ("reason",),
        "feedback": ("summary",),
        "policy_change": ("reason", "before_version", "after_version"),
    }
    require(data, required[event])
    string_fields = {
        "dispatch": ("assignment_id", "model", "effort", "reason"),
        "report": ("assignment_id", "summary"),
        "review": ("assignment_id", "verdict"),
        "replan": ("reason",),
        "feedback": ("summary",),
        "policy_change": ("reason",),
    }.get(event, ())
    for name in string_fields:
        if not isinstance(data[name], str) or not data[name].strip():
            raise JournalError(f"{event} {name} must be a non-empty string")
    if event == "review":
        if data["verdict"] not in REVIEW_VERDICTS:
            raise JournalError("review verdict must be accepted, changes_requested, or blocked")
        if not isinstance(data["findings"], list):
            raise JournalError("review findings must be an array")
    if event == "finish":
        if not isinstance(data["outcome"], str) or data["outcome"] not in FINISH_OUTCOMES:
            raise JournalError("finish outcome must be completed, blocked, cancelled, or failed")
        if "blocker_reasons" in data:
            reasons = data["blocker_reasons"]
            if (not isinstance(reasons, list)
                    or any(not isinstance(reason, str) or reason not in BLOCKER_REASONS for reason in reasons)):
                raise JournalError("finish blocker_reasons must be an array of supported categories")
            if len(reasons) != len(set(reasons)):
                raise JournalError("finish blocker_reasons must not contain duplicates")
            if reasons and data["outcome"] != "blocked":
                raise JournalError("finish blocker_reasons may be non-empty only for a blocked outcome")
        if ("delivered_work_status" in data
                and (not isinstance(data["delivered_work_status"], str)
                     or data["delivered_work_status"] not in DELIVERED_WORK_STATUSES)):
            raise JournalError(
                "finish delivered_work_status must be accepted, changes_requested, or not_reviewed"
            )
        if "assignment_dispositions" in data:
            dispositions = data["assignment_dispositions"]
            if (not isinstance(dispositions, dict)
                    or len(dispositions) > MAX_ASSIGNMENT_DISPOSITIONS
                    or any(not nonempty_string(assignment_id)
                           or not isinstance(disposition, str)
                           or disposition not in ASSIGNMENT_DISPOSITIONS
                           for assignment_id, disposition in dispositions.items())):
                raise JournalError(
                    "finish assignment_dispositions must map assignment IDs to superseded or cancelled"
                )
    if event == "runtime":
        validate_runtime(data)


def nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_runtime(data: dict) -> None:
    assignment_id = data.get("assignment_id")
    coordinator = data.get("coordinator")
    has_assignment = nonempty_string(assignment_id)
    has_coordinator = coordinator is True
    if has_assignment == has_coordinator:
        raise JournalError("runtime requires exactly one target: assignment_id or coordinator: true")
    if assignment_id is not None and not nonempty_string(assignment_id):
        raise JournalError("runtime assignment_id must be a non-empty string")
    if coordinator is not None and coordinator is not True:
        raise JournalError("runtime coordinator must be true")
    if not nonempty_string(data.get("source")):
        raise JournalError("runtime source must be a non-empty string")
    for name in ("actual_model", "actual_effort"):
        if name not in data:
            raise JournalError(f"runtime requires {name} (string or null)")
        if data[name] is not None and not nonempty_string(data[name]):
            raise JournalError(f"runtime {name} must be a non-empty string or null")
    usage = data.get("usage")
    if usage is None:
        return
    validate_usage(usage, require_measurement=True)


def validate_usage(usage: object, require_measurement: bool) -> None:
    if not isinstance(usage, dict):
        raise JournalError("runtime usage must be an object or null")
    required = ("measurement_id", "scope", "source") if require_measurement else ("scope", "source")
    for name in required:
        if not nonempty_string(usage.get(name)):
            raise JournalError(f"runtime usage.{name} must be a non-empty string")
    if "measurement_id" in usage and not nonempty_string(usage["measurement_id"]):
        raise JournalError("runtime usage.measurement_id must be a non-empty string")
    counters = {name: value for name, value in usage.items() if name.endswith("_tokens")}
    if not counters:
        raise JournalError("runtime usage requires at least one *_tokens counter")
    for name, value in counters.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise JournalError(f"runtime usage.{name} must be a nonnegative integer")
    if ("cached_input_tokens" in counters and "input_tokens" in counters
            and counters["cached_input_tokens"] > counters["input_tokens"]):
        raise JournalError("runtime usage.cached_input_tokens cannot exceed input_tokens")
    if ("reasoning_output_tokens" in counters and "output_tokens" in counters
            and counters["reasoning_output_tokens"] > counters["output_tokens"]):
        raise JournalError("runtime usage.reasoning_output_tokens cannot exceed output_tokens")


def default_log_root() -> Path:
    settings = SKILL_ROOT / "settings.json"
    if settings.is_file():
        try:
            value = json.loads(settings.read_text(encoding="utf-8"))
            configured = value.get("log_root") if isinstance(value, dict) else None
            if isinstance(configured, str) and configured.strip():
                path = Path(configured).expanduser()
                return path if path.is_absolute() else SKILL_ROOT / path
        except (OSError, json.JSONDecodeError):
            pass
    return Path.cwd() / "work" / "astra-helm-logs"


def resolve_root(argument: str | None) -> Path:
    return Path(argument).expanduser() if argument else default_log_root()


def canonical_root(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def registry_path(root: Path) -> Path:
    return root / "roots.json"


def read_registry(root: Path) -> tuple[list[Path], list[str]]:
    path = registry_path(root)
    if not path.exists():
        return [], []
    try:
        if path.is_symlink():
            return [], [f"{path}: symbolic-link registry is not read"]
        with path.open("r", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [], [f"{path}: cannot read registry: {exc}"]
    roots = value.get("roots") if isinstance(value, dict) else None
    if not isinstance(roots, list) or any(not nonempty_string(item) for item in roots):
        return [], [f"{path}: registry must contain a roots array of non-empty paths"]
    return [canonical_root(Path(item)) for item in roots], []


def register_root(root: Path, registered: Path) -> dict:
    root = canonical_root(root)
    registered = canonical_root(registered)
    root.mkdir(parents=True, exist_ok=True)
    path = registry_path(root)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        with os.fdopen(fd, "r+", encoding="utf-8", closefd=False) as handle:
            try:
                value = json.load(handle)
            except json.JSONDecodeError as exc:
                handle.seek(0, os.SEEK_END)
                if handle.tell() != 0:
                    raise JournalError(f"cannot update registry: {exc}") from exc
                value = {"roots": []}
            roots = value.get("roots") if isinstance(value, dict) else None
            if not isinstance(roots, list) or any(not nonempty_string(item) for item in roots):
                raise JournalError("cannot update registry: roots.json must contain a roots array of non-empty paths")
            canonical = {str(canonical_root(Path(item))) for item in roots}
            canonical.add(str(registered))
            output = {"roots": sorted(canonical)}
            handle.seek(0)
            handle.truncate()
            json.dump(output, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    return {"registry": str(path), "registered_root": str(registered), "roots": output["roots"]}


def policy_snapshot() -> tuple[object, str]:
    skill_path = SKILL_ROOT / "SKILL.md"
    policy_path = SKILL_ROOT / "policy.json"
    try:
        skill_bytes = skill_path.read_bytes()
        policy_bytes = policy_path.read_bytes()
        policy = json.loads(policy_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JournalError(f"cannot snapshot SKILL.md and policy.json: {exc}") from exc
    digest = hashlib.sha256(skill_bytes + policy_bytes).hexdigest()
    return policy, digest


def log_path(root: Path, run_id: str) -> Path:
    return root / f"{validate_uuid(run_id)}.jsonl"


def encode_record(record: dict) -> bytes:
    encoded = (json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    if len(encoded) > MAX_RECORD_BYTES:
        raise JournalError(f"journal record exceeds {MAX_RECORD_BYTES} UTF-8 bytes")
    return encoded


def write_all(fd: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(fd, view)
        if written == 0:
            raise OSError("short write while appending journal record")
        view = view[written:]


def start_run(root: Path, data: dict) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    policy, digest = policy_snapshot()
    record = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "timestamp": utc_now(),
        "event": "start",
        "skill_hash": digest,
        "policy": policy,
        "data": validate_start(data),
    }
    encoded = encode_record(record)
    path = log_path(root, run_id)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        write_all(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)
    return record


def parse_lines(handle) -> tuple[list[dict], list[str]]:
    records, warnings = [], []
    handle.seek(0)
    for line_number, raw in enumerate(handle, 1):
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("record is not an object")
            records.append(value)
        except (json.JSONDecodeError, ValueError) as exc:
            warnings.append(f"line {line_number}: {exc}")
    return records, warnings


def append_event(root: Path, run_id: str, event: str, data: dict) -> dict:
    validate_event(event, data)
    path = log_path(root, run_id)
    try:
        fd = os.open(path, os.O_RDWR | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError as exc:
        raise JournalError(f"run does not exist: {run_id}") from exc
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "r+", encoding="utf-8", closefd=False) as handle:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            records, warnings = parse_lines(handle)
            if warnings:
                raise JournalError("run contains malformed records; refusing append: " + "; ".join(warnings))
            if not records or records[0].get("event") != "start" or records[0].get("run_id") != run_id:
                raise JournalError("run has no valid matching start record")
            finished = any(record.get("event") == "finish" for record in records)
            if finished and event not in POST_FINISH_EVENTS:
                raise JournalError(f"cannot record {event} after finish")
            if event == "runtime" and isinstance(data.get("usage"), dict):
                measurement_id = data["usage"]["measurement_id"]
                for existing in records:
                    existing_data = existing.get("data")
                    existing_usage = existing_data.get("usage") if isinstance(existing_data, dict) else None
                    if (existing.get("event") == "runtime" and isinstance(existing_usage, dict)
                            and existing_usage.get("measurement_id") == measurement_id):
                        raise JournalError(f"runtime usage measurement_id already exists: {measurement_id}")
            record = {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "timestamp": utc_now(),
                "event": event,
                "data": data,
            }
            write_all(fd, encode_record(record))
            os.fsync(fd)
            return record
    finally:
        os.close(fd)


def parse_timestamp(value: object) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
    except ValueError:
        return None


def summarize_file(path: Path) -> tuple[dict | None, list[str], list[dict]]:
    warnings: list[str] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
            records, parse_warnings = parse_lines(handle)
    except (OSError, UnicodeError) as exc:
        return None, [f"{path.name}: cannot read: {exc}"], []
    warnings.extend(f"{path.name}: {warning}" for warning in parse_warnings)
    if not records:
        return None, warnings or [f"{path.name}: empty run"], []
    start = records[0]
    if (start.get("event") != "start" or start.get("run_id") != path.stem
            or start.get("schema_version") != SCHEMA_VERSION):
        warnings.append(f"{path.name}: first record is not a matching start")
        return None, warnings, []
    start_data = start.get("data")
    if not isinstance(start_data, dict):
        warnings.append(f"{path.name}: start data is malformed")
        start_data = {}
    else:
        try:
            start_data = validate_start(start_data)
        except JournalError as exc:
            warnings.append(f"{path.name}: malformed start data: {exc}")
            start_data = {}
    if parse_timestamp(start.get("timestamp")) is None:
        warnings.append(f"{path.name}: invalid start timestamp")
    skill_hash = start.get("skill_hash")
    if not isinstance(skill_hash, str) or len(skill_hash) != 64:
        warnings.append(f"{path.name}: invalid skill hash")
    valid_events: list[dict] = []
    corrupt = bool(warnings)
    seen_finish = False
    for index, record in enumerate(records[1:], 2):
        event, data = record.get("event"), record.get("data")
        if (record.get("run_id") != path.stem or record.get("schema_version") != SCHEMA_VERSION
                or not isinstance(event, str) or event not in EVENTS or not isinstance(data, dict)
                or parse_timestamp(record.get("timestamp")) is None):
            warnings.append(f"{path.name}: line {index}: malformed event record")
            corrupt = True
            continue
        try:
            validate_event(event, data)
        except JournalError as exc:
            warnings.append(f"{path.name}: line {index}: {exc}")
            corrupt = True
            continue
        if seen_finish and event not in POST_FINISH_EVENTS:
            warnings.append(f"{path.name}: line {index}: {event} appears after finish")
            corrupt = True
        if event == "finish":
            seen_finish = True
        valid_events.append(record)
    finishes = [record for record in valid_events if record["event"] == "finish"]
    if len(finishes) > 1:
        warnings.append(f"{path.name}: duplicate finish records")
        corrupt = True
    finish = finishes[0] if finishes else None
    start_time = parse_timestamp(start.get("timestamp"))
    finish_time = parse_timestamp(finish.get("timestamp")) if finish else None
    elapsed = (finish_time - start_time).total_seconds() if start_time and finish_time else None
    if finish and elapsed is None:
        warnings.append(f"{path.name}: invalid start or finish timestamp")
        corrupt = True
    elif elapsed is not None and elapsed < 0:
        warnings.append(f"{path.name}: finish timestamp precedes start")
        elapsed = None
        corrupt = True
    dispatches = [record for record in valid_events if record["event"] == "dispatch"]
    reviews = [record for record in valid_events if record["event"] == "review"]
    replans = [record for record in valid_events if record["event"] == "replan"]
    feedback = [record["data"] for record in valid_events if record["event"] == "feedback"]
    runtime_records = [record for record in valid_events if record["event"] == "runtime"]
    reviews_by_assignment: dict[object, list[dict]] = {}
    for review in reviews:
        reviews_by_assignment.setdefault(review["data"]["assignment_id"], []).append(review)
    assignment_dispositions = (
        finish["data"].get("assignment_dispositions", {}) if finish else {}
    )
    policy = start.get("policy")
    policy_version = policy.get("version") if isinstance(policy, dict) else None
    if policy_version is not None and not isinstance(policy_version, (str, int, float)):
        warnings.append(f"{path.name}: invalid policy version")
        policy_version = None
        corrupt = True
    runtime_evidence = []
    seen_measurements: set[str] = set()
    for runtime in runtime_records:
        data = runtime["data"]
        usage = data.get("usage")
        if isinstance(usage, dict):
            measurement_id = usage["measurement_id"]
            if measurement_id in seen_measurements:
                warnings.append(f"{path.name}: repeated runtime usage measurement_id: {measurement_id}")
                corrupt = True
                continue
            seen_measurements.add(measurement_id)
        runtime_evidence.append({
            "timestamp": runtime["timestamp"],
            "target": data.get("assignment_id") or "coordinator",
            "source": data["source"],
            "actual_model": data["actual_model"],
            "actual_effort": data["actual_effort"],
            "usage": usage,
        })
    outcome = "corrupt" if corrupt else (finish["data"]["outcome"] if finish else "incomplete")

    route_rows = []
    legacy_usage_targets: set[str] = set()
    for dispatch in dispatches:
        data = dispatch["data"]
        evidence = [item for item in runtime_evidence if item["target"] == data["assignment_id"]]
        reports = [record["data"] for record in valid_events
                   if record["event"] == "report" and record["data"]["assignment_id"] == data["assignment_id"]]
        for report in reports:
            report_usage = report.get("usage")
            sourced_usage = None
            if report_usage is not None:
                try:
                    validate_usage(report_usage, require_measurement=False)
                    sourced_usage = report_usage
                    legacy_usage_targets.add(data["assignment_id"])
                except JournalError as exc:
                    warnings.append(f"{path.name}: ignored malformed legacy report usage: {exc}")
            has_sourced_settings = nonempty_string(report.get("runtime_source")) and (
                report.get("actual_model") is not None or report.get("actual_effort") is not None)
            if has_sourced_settings or sourced_usage is not None:
                evidence.append({
                    "timestamp": None,
                    "target": data["assignment_id"],
                    "source": report.get("runtime_source") or sourced_usage["source"],
                    "actual_model": report.get("actual_model") if has_sourced_settings else None,
                    "actual_effort": report.get("actual_effort") if has_sourced_settings else None,
                    "usage": sourced_usage,
                    "legacy_report": True,
                })
        models = {item["actual_model"] for item in evidence if nonempty_string(item.get("actual_model"))}
        efforts = {item["actual_effort"] for item in evidence if nonempty_string(item.get("actual_effort"))}
        if len(models) > 1 or len(efforts) > 1:
            warnings.append(f"{path.name}: conflicting sourced runtime settings for {data['assignment_id']}")
        actual_model = next(iter(models)) if len(models) == 1 else None
        actual_effort = next(iter(efforts)) if len(efforts) == 1 else None
        if actual_model is not None and actual_effort is not None:
            settings_status = "sourced"
        elif evidence:
            settings_status = "partial"
        else:
            settings_status = "requested"
        route_rows.append({
            "assignment_id": data["assignment_id"],
            "model": data["model"],
            "effort": data["effort"],
            "actual_model": actual_model,
            "actual_effort": actual_effort,
            "settings_status": settings_status,
            "runtime_sources": sorted({item["source"] for item in evidence}),
            "usage_evidence": [item["usage"] for item in evidence if isinstance(item.get("usage"), dict)],
            "latest_review": (
                {
                    "verdict": reviews_by_assignment[data["assignment_id"]][-1]["data"]["verdict"],
                    "timestamp": reviews_by_assignment[data["assignment_id"]][-1]["timestamp"],
                }
                if reviews_by_assignment.get(data["assignment_id"]) else None
            ),
            "assignment_disposition": assignment_dispositions.get(data["assignment_id"]),
        })

    expected_targets = {"coordinator", *(route["assignment_id"] for route in route_rows)}
    targets_with_usage = ({item["target"] for item in runtime_evidence if isinstance(item.get("usage"), dict)}
                          | legacy_usage_targets)
    row = {
        "run_id": path.stem,
        "source_path": str(path.resolve(strict=False)),
        "project": start_data.get("project"),
        "task_type": start_data.get("task_type"),
        "risk": start_data.get("risk"),
        "kind": start_data.get("kind", "execution"),
        "policy_version": policy_version,
        "outcome": outcome,
        "dispatch_count": len(dispatches),
        "changes_requested_count": sum(r["data"]["verdict"] == "changes_requested" for r in reviews),
        "replan_count": len(replans),
        "elapsed_wall_seconds": elapsed,
        "routes": route_rows,
        "feedback": feedback,
        "usage": finish["data"].get("usage") if finish else None,
        "runtime_evidence": runtime_evidence,
        "usage_coverage": {
            "measurement_count": len(seen_measurements),
            "targets_with_usage": sorted(targets_with_usage),
            "targets_without_usage": sorted(expected_targets - targets_with_usage),
            "legacy_finish_usage_present": bool(finish and finish["data"].get("usage") is not None),
            "overlapping_measurements_summed": False,
        },
    }
    if finish and "blocker_reasons" in finish["data"]:
        row["blocker_reasons"] = finish["data"]["blocker_reasons"]
    if finish and "delivered_work_status" in finish["data"]:
        row["delivered_work_status"] = finish["data"]["delivered_work_status"]
    if finish and "assignment_dispositions" in finish["data"]:
        row["assignment_dispositions"] = finish["data"]["assignment_dispositions"]
        dispatched_ids = {route["assignment_id"] for route in route_rows}
        for assignment_id in sorted(set(assignment_dispositions) - dispatched_ids):
            warnings.append(
                f"{path.name}: finish disposition names unknown assignment: {assignment_id}"
            )
    if finish and finish["data"].get("delivered_work_status") == "accepted":
        for route in route_rows:
            latest = route["latest_review"]
            if ((latest is None or latest["verdict"] != "accepted")
                    and route["assignment_disposition"] not in ASSIGNMENT_DISPOSITIONS):
                verdict = "unknown" if latest is None else latest["verdict"]
                warnings.append(
                    f"{path.name}: accepted closure has unresolved assignment "
                    f"{route['assignment_id']} (latest review: {verdict})"
                )
    group_items = []
    aggregate_dispatches = dispatches if not corrupt and start_data.get("kind", "execution") == "execution" else []
    for dispatch in aggregate_dispatches:
        data = dispatch["data"]
        verdicts = [review["data"]["verdict"]
                    for review in reviews_by_assignment.get(data["assignment_id"], [])]
        group_items.append({
            "requested_model": data["model"],
            "requested_effort": data["effort"],
            "task_type": start_data.get("task_type"),
            "risk": start_data.get("risk"),
            "policy_version": policy_version,
            "accepted_reviews": verdicts.count("accepted"),
            "changes_requested_reviews": verdicts.count("changes_requested"),
        })
    return row, warnings, group_items


def summary(root: Path, project: str | None, last: int,
            include_roots: list[Path] | None = None) -> dict:
    rows, warnings, group_items = [], [], []
    selected_root = canonical_root(root)
    registered, registry_warnings = read_registry(selected_root)
    warnings.extend(registry_warnings)
    root_entries = [(selected_root, "selected")]
    root_entries.extend((path, "registered") for path in registered)
    root_entries.extend((canonical_root(path), "included") for path in (include_roots or []))
    seen_roots: set[str] = set()
    roots = []
    for candidate, source in root_entries:
        key = str(candidate)
        if key in seen_roots:
            continue
        seen_roots.add(key)
        roots.append(candidate)
        if source == "registered" and not candidate.is_dir():
            warnings.append(f"registered root missing: {candidate}")
        elif source == "included" and not candidate.is_dir():
            warnings.append(f"included root missing: {candidate}")

    by_run: dict[str, list[tuple[Path, float, bytes]]] = {}
    for candidate_root in roots:
        if not candidate_root.is_dir():
            continue
        try:
            candidates = list(candidate_root.glob("*.jsonl"))
        except OSError as exc:
            warnings.append(f"cannot list log root {candidate_root}: {exc}")
            continue
        for path in candidates:
            try:
                validate_uuid(path.stem)
            except JournalError:
                warnings.append(f"{path}: filename is not a canonical UUID")
                continue
            if path.is_symlink():
                warnings.append(f"{path}: symbolic-link logs are not read")
                continue
            try:
                with path.open("rb") as handle:
                    if fcntl is not None:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
                    content = handle.read()
                    modified = os.fstat(handle.fileno()).st_mtime
                by_run.setdefault(path.stem, []).append((path, modified, content))
            except OSError as exc:
                warnings.append(f"{path}: cannot inspect log: {exc}")

    ordered = sorted(by_run.items(), key=lambda item: max(entry[1] for entry in item[1]), reverse=True)
    for run_id, copies in ordered:
        histories: dict[bytes, list[Path]] = {}
        for path, _mtime, content in copies:
            histories.setdefault(hashlib.sha256(content).digest(), []).append(path)
        if len(histories) == 1:
            paths = next(iter(histories.values()))
            row, file_warnings, items = summarize_file(paths[0])
            warnings.extend(file_warnings)
            if row is not None and (project is None or row["project"] == project):
                if len(paths) > 1:
                    row["duplicate_sources"] = [str(path.resolve(strict=False)) for path in paths[1:]]
                rows.append(row)
                group_items.extend(items)
        else:
            source_names = [str(path.resolve(strict=False)) for path, _mtime, _content in copies]
            warnings.append(f"conflicting histories for run {run_id}: " + ", ".join(source_names))
            projects = set()
            for path, _mtime, _content in copies:
                row, file_warnings, _items = summarize_file(path)
                warnings.extend(file_warnings)
                if row is not None and row.get("project") is not None:
                    projects.add(row["project"])
            conflict_project = next(iter(projects)) if len(projects) == 1 else None
            if project is None or conflict_project == project:
                rows.append({
                    "run_id": run_id,
                    "source_path": None,
                    "project": conflict_project,
                    "outcome": "conflict",
                    "history_conflict": True,
                    "conflicting_sources": source_names,
                })
        if len(rows) >= last:
            rows = rows[:last]
            break
    groups: dict[tuple, dict] = {}
    for item in group_items:
        key = tuple(item[name] for name in ("requested_model", "requested_effort", "task_type", "risk", "policy_version"))
        group = groups.setdefault(key, {
            "requested_model": key[0], "requested_effort": key[1], "task_type": key[2],
            "risk": key[3], "policy_version": key[4], "dispatch_count": 0,
            "accepted_reviews": 0, "changes_requested_reviews": 0,
        })
        group["dispatch_count"] += 1
        group["accepted_reviews"] += item["accepted_reviews"]
        group["changes_requested_reviews"] += item["changes_requested_reviews"]
    return {
        "runs": rows,
        "groups": list(groups.values()),
        "warnings": warnings,
        "log_roots": [str(path) for path in roots],
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--log-root")
    commands = result.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start")
    start.add_argument("--data-file", required=True)
    record = commands.add_parser("record")
    record.add_argument("--run-id", required=True)
    record.add_argument("--event", required=True, choices=sorted(EVENTS))
    record.add_argument("--data-file", required=True)
    register = commands.add_parser("register-root")
    register.add_argument("--path", required=True)
    report = commands.add_parser("summary")
    report.add_argument("--project")
    report.add_argument("--last", type=int, default=30)
    report.add_argument("--include-root", action="append", default=[])
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        root = resolve_root(args.log_root)
        if args.command == "start":
            output = start_run(root, load_json_object(args.data_file))
        elif args.command == "record":
            output = append_event(root, validate_uuid(args.run_id), args.event, load_json_object(args.data_file))
        elif args.command == "register-root":
            output = register_root(root, Path(args.path))
        else:
            if args.last < 1:
                raise JournalError("--last must be at least 1")
            output = summary(root, args.project, args.last, [Path(path) for path in args.include_root])
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0
    except (JournalError, OSError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
