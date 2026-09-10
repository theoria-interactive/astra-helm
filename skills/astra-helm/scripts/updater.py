#!/usr/bin/env python3
"""Opt-in, pinned updater for an installed Astra Helm skill."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
import urllib.error
import urllib.request
import uuid


SKILL_ROOT = Path(__file__).resolve().parent.parent
STATE_NAME = ".update-state.json"
LOCK_NAME = ".update-lock"
MANIFEST_NAME = "update-manifest.json"
STATE_SCHEMA = 1
CHECK_INTERVAL = dt.timedelta(days=7)
TIMEOUT_SECONDS = 8
MAX_MANIFEST_BYTES = 128 * 1024
MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_FILES = 64
API_URL = "https://api.github.com/repos/kivancguckiran/astra-helm/git/ref/heads/main"
RAW_PREFIX = "https://raw.githubusercontent.com/kivancguckiran/astra-helm/"
REMOTE_SUBDIR = "skills/astra-helm"
SEMVER_RE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
REQUIRED_FILES = {"SKILL.md", "policy.json", "scripts/updater.py"}
PRIVATE_NAMES = {".telemetry-state.json", ".telemetry-lock", STATE_NAME, LOCK_NAME, MANIFEST_NAME, ".update-backups", "settings.json", ".git"}
SAFE_PART_RE = re.compile(r"[A-Za-z0-9._-]+\Z")


class UpdaterError(ValueError):
    """A bounded updater failure suitable for display to the user."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        raise UpdaterError("network redirect refused")


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def format_time(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: object) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(dt.timezone.utc) if parsed.tzinfo else None


def semver(value: object) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise UpdaterError("version must be a numeric SemVer string")
    match = SEMVER_RE.fullmatch(value)
    if not match:
        raise UpdaterError("version must use numeric SemVer (major.minor.patch)")
    return tuple(int(part) for part in match.groups())


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(128 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 240:
        raise UpdaterError("manifest file paths must be non-empty strings of at most 240 characters")
    if "\\" in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise UpdaterError(f"unsafe manifest path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(part in ("", ".", "..") for part in path.parts):
        raise UpdaterError(f"unsafe manifest path: {value!r}")
    if any(not SAFE_PART_RE.fullmatch(part) for part in path.parts):
        raise UpdaterError(f"manifest path contains unsupported characters: {value}")
    if any(part.casefold() in PRIVATE_NAMES for part in path.parts):
        raise UpdaterError(f"manifest may not manage private path: {value}")
    return value


def validate_manifest(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"version", "notes", "files"}:
        raise UpdaterError("manifest must contain exactly version, notes, and files")
    version = value["version"]
    semver(version)
    notes = value["notes"]
    if (not isinstance(notes, list) or len(notes) > 20
            or any(not isinstance(note, str) or len(note.encode("utf-8")) > 2048 for note in notes)):
        raise UpdaterError("manifest notes must be an array of at most 20 short strings")
    files = value["files"]
    if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
        raise UpdaterError(f"manifest files must contain 1 to {MAX_FILES} entries")
    clean_files: dict[str, str] = {}
    for raw_path, digest in files.items():
        path = validate_relative_path(raw_path)
        if not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
            raise UpdaterError(f"invalid sha256 for {path}")
        clean_files[path] = digest
    paths = set(clean_files)
    folded_paths = {path.casefold() for path in paths}
    if len(folded_paths) != len(paths):
        raise UpdaterError("manifest contains paths that collide on a case-insensitive filesystem")
    for path in paths:
        parts = PurePosixPath(path.casefold()).parts
        if any("/".join(parts[:index]) in folded_paths for index in range(1, len(parts))):
            raise UpdaterError(f"manifest contains a file/directory prefix conflict: {path}")
    missing = sorted(REQUIRED_FILES - set(clean_files))
    if missing:
        raise UpdaterError("manifest omits required managed files: " + ", ".join(missing))
    return {"version": version, "notes": list(notes), "files": clean_files}


def state_path(root: Path) -> Path:
    return root / STATE_NAME


def default_state(checks_enabled: bool) -> dict:
    return {
        "schema_version": STATE_SCHEMA,
        "checks_enabled": checks_enabled,
        "last_attempt_at": None,
        "last_check": None,
        "declined_versions": [],
        "candidate": None,
    }


def load_state(root: Path) -> dict | None:
    path = state_path(root)
    if not path.exists():
        return None
    try:
        if path.is_symlink():
            raise UpdaterError("update state may not be a symbolic link")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UpdaterError(f"cannot read update state: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != STATE_SCHEMA:
        raise UpdaterError("unsupported update-state schema")
    if not isinstance(value.get("checks_enabled"), bool):
        raise UpdaterError("update state has invalid checks_enabled")
    declined = value.get("declined_versions")
    if not isinstance(declined, list) or any(not isinstance(item, str) for item in declined):
        raise UpdaterError("update state has invalid declined_versions")
    candidate = value.get("candidate")
    if candidate is not None:
        if not isinstance(candidate, dict) or not SHA_RE.fullmatch(str(candidate.get("commit", ""))):
            raise UpdaterError("update state has invalid candidate")
        validate_manifest({key: candidate.get(key) for key in ("version", "notes", "files")})
    return value


def write_state(root: Path, value: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    destination = state_path(root)
    if destination.is_symlink():
        raise UpdaterError("update state may not be a symbolic link")
    temporary = root / f".{STATE_NAME}.{uuid.uuid4().hex}.tmp"
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(fd)
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    finally:
        os.close(fd)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def read_local_manifest(root: Path) -> dict:
    path = root / MANIFEST_NAME
    try:
        if path.is_symlink():
            raise UpdaterError("installed manifest may not be a symbolic link")
        raw = path.read_bytes()
        if len(raw) > MAX_MANIFEST_BYTES:
            raise UpdaterError("installed manifest is too large")
        return validate_manifest(json.loads(raw))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UpdaterError(f"cannot read installed manifest: {exc}") from exc


def _local_version(root: Path) -> tuple[str | None, str | None]:
    try:
        return read_local_manifest(root)["version"], None
    except UpdaterError as exc:
        return None, str(exc)


def status(root: Path = SKILL_ROOT) -> dict:
    installed, baseline_error = _local_version(root)
    try:
        state = load_state(root)
    except UpdaterError as exc:
        return {"status": "error", "installed_version": installed, "error": str(exc)}
    if state is None:
        return {"status": "consent_required", "installed_version": installed, "baseline_error": baseline_error}
    result = {
        "status": "ready" if state["checks_enabled"] else "checks_disabled",
        "installed_version": installed,
        "baseline_error": baseline_error,
        "checks_enabled": state["checks_enabled"],
        "last_attempt_at": state.get("last_attempt_at"),
        "last_check": state.get("last_check"),
        "candidate": state.get("candidate"),
        "declined_versions": state.get("declined_versions", []),
    }
    if state["checks_enabled"] and state.get("candidate"):
        result["status"] = "available"
    return result


def _configure_locked(enabled: bool, root: Path) -> dict:
    state = load_state(root) or default_state(enabled)
    state["checks_enabled"] = enabled
    write_state(root, state)
    return {"status": "configured", "checks_enabled": enabled}


def _open_url(url: str, max_bytes: int) -> bytes:
    if url != API_URL and not url.startswith(RAW_PREFIX):
        raise UpdaterError("network URL is outside the fixed official origin")
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "astra-helm-updater/1"},
        method="GET",
    )
    try:
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(max_bytes + 1)
    except UpdaterError:
        raise
    except (OSError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise UpdaterError(f"network request failed: {exc}") from exc
    if len(body) > max_bytes:
        raise UpdaterError("network response exceeds size limit")
    return body


def _fetch_json(url: str, max_bytes: int) -> object:
    try:
        return json.loads(_open_url(url, max_bytes))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise UpdaterError(f"invalid JSON response: {exc}") from exc


def resolve_main_commit() -> str:
    value = _fetch_json(API_URL, 64 * 1024)
    reference = value.get("object") if isinstance(value, dict) else None
    commit = reference.get("sha") if isinstance(reference, dict) and reference.get("type") == "commit" else None
    if not isinstance(commit, str) or not SHA_RE.fullmatch(commit):
        raise UpdaterError("GitHub main response did not contain a valid commit SHA")
    return commit


def raw_url(commit: str, relative: str) -> str:
    if not SHA_RE.fullmatch(commit):
        raise UpdaterError("invalid pinned commit SHA")
    validate_relative_path(relative) if relative != MANIFEST_NAME else None
    return f"{RAW_PREFIX}{commit}/{REMOTE_SUBDIR}/{relative}"


def fetch_candidate() -> tuple[str, dict]:
    commit = resolve_main_commit()
    value = _fetch_json(raw_url(commit, MANIFEST_NAME), MAX_MANIFEST_BYTES)
    return commit, validate_manifest(value)


def _check_locked(force: bool, root: Path, now: dt.datetime | None) -> dict:
    now = now or utc_now()
    state = load_state(root)
    if state is None:
        return {"status": "consent_required"}
    if not state["checks_enabled"]:
        return {"status": "checks_disabled"}
    last_attempt = parse_time(state.get("last_attempt_at"))
    if not force and last_attempt is not None and now - last_attempt < CHECK_INTERVAL:
        return {
            "status": "throttled",
            "last_attempt_at": state["last_attempt_at"],
            "next_check_at": format_time(last_attempt + CHECK_INTERVAL),
        }
    attempted_at = format_time(now)
    state["last_attempt_at"] = attempted_at
    state["last_check"] = {"status": "attempting", "checked_at": attempted_at, "error": None}
    write_state(root, state)
    try:
        installed = read_local_manifest(root)
        commit, manifest = fetch_candidate()
        candidate = {**manifest, "commit": commit, "fetched_at": attempted_at}
        if semver(manifest["version"]) <= semver(installed["version"]):
            outcome = "up_to_date"
            state["candidate"] = None
        elif manifest["version"] in state.get("declined_versions", []):
            outcome = "declined"
            state["candidate"] = None
        else:
            outcome = "available"
            state["candidate"] = candidate
        state["last_check"] = {"status": outcome, "checked_at": attempted_at, "error": None}
        write_state(root, state)
        return {
            "status": outcome,
            "installed_version": installed["version"],
            "available_version": manifest["version"],
            "notes": manifest["notes"],
            "pinned_commit": commit,
        }
    except Exception as exc:
        error = str(exc) if isinstance(exc, UpdaterError) else f"unexpected updater error: {exc}"
        state["last_check"] = {"status": "error", "checked_at": attempted_at, "error": error}
        write_state(root, state)
        return {"status": "error", "error": error, "last_attempt_at": attempted_at}


def _decline_locked(commit: str, root: Path) -> dict:
    state = load_state(root)
    candidate = state.get("candidate") if state else None
    if not candidate or candidate.get("commit") != commit:
        raise UpdaterError("decline commit does not match the cached candidate")
    declined = set(state.get("declined_versions", []))
    declined.add(candidate["version"])
    state["declined_versions"] = sorted(declined, key=semver)
    state["candidate"] = None
    write_state(root, state)
    return {"status": "declined", "version": candidate["version"], "commit": commit}


def _path_kind(path: Path) -> str:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return "missing"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    return "special"


def _unsafe_parent(root: Path, relative: str) -> str | None:
    current = root
    for part in PurePosixPath(relative).parts[:-1]:
        current = current / part
        kind = _path_kind(current)
        if kind == "missing":
            return None
        if kind != "directory":
            return str(current)
    return None


def installation_changes(root: Path, baseline: dict, target: dict) -> list[dict]:
    changes: list[dict] = []
    for relative, expected in baseline["files"].items():
        path = root / relative
        bad_parent = _unsafe_parent(root, relative)
        if bad_parent:
            changes.append({"path": relative, "reason": f"unsafe parent: {bad_parent}"})
            continue
        kind = _path_kind(path)
        if kind != "file":
            changes.append({"path": relative, "reason": "deleted" if kind == "missing" else kind})
            continue
        try:
            actual = sha256_file(path)
        except OSError as exc:
            changes.append({"path": relative, "reason": f"unreadable: {exc}"})
            continue
        if actual != expected:
            changes.append({"path": relative, "reason": "modified", "expected": expected, "actual": actual})
    for relative in target["files"]:
        bad_parent = _unsafe_parent(root, relative)
        if bad_parent:
            changes.append({"path": relative, "reason": f"unsafe parent: {bad_parent}"})
        if relative not in baseline["files"] and _path_kind(root / relative) != "missing":
            changes.append({"path": relative, "reason": "unknown target collision"})
    return changes


def in_git_checkout(root: Path) -> bool:
    current = root.resolve()
    return any((ancestor / ".git").exists() or (ancestor / ".git").is_symlink()
               for ancestor in (current, *current.parents))


def _validate_downloaded(stage: Path, manifest: dict) -> None:
    try:
        skill_text = (stage / "SKILL.md").read_text(encoding="utf-8")
        policy = json.loads((stage / "policy.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UpdaterError(f"cannot validate required downloaded files: {exc}") from exc
    frontmatter = skill_text.split("---", 2)
    name_match = re.search(r"(?m)^name:\s*['\"]?([^'\"\s]+)", frontmatter[1]) if len(frontmatter) == 3 else None
    if not name_match or name_match.group(1) != "astra-helm":
        raise UpdaterError("downloaded SKILL.md does not identify the astra-helm skill")
    if not isinstance(policy, dict) or policy.get("version") != manifest["version"]:
        raise UpdaterError("downloaded policy.json version does not match manifest")


def _download_candidate(commit: str, manifest: dict, stage: Path) -> None:
    total = 0
    for relative, expected in manifest["files"].items():
        body = _open_url(raw_url(commit, relative), MAX_FILE_BYTES)
        total += len(body)
        if total > MAX_TOTAL_BYTES:
            raise UpdaterError("downloaded update exceeds total size limit")
        if sha256_bytes(body) != expected:
            raise UpdaterError(f"download hash mismatch: {relative}")
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
    _validate_downloaded(stage, manifest)


def _acquire_lock(root: Path) -> tuple[int, Path]:
    path = root / LOCK_NAME
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError as exc:
        raise UpdaterError("another Astra Helm update is in progress") from exc
    os.write(fd, f"{os.getpid()}\n".encode("ascii"))
    return fd, path


def _release_lock(fd: int, path: Path) -> None:
    os.close(fd)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def configure(enabled: bool, root: Path = SKILL_ROOT) -> dict:
    fd, path = _acquire_lock(root)
    try:
        return _configure_locked(enabled, root)
    finally:
        _release_lock(fd, path)


def check(force: bool = False, root: Path = SKILL_ROOT, now: dt.datetime | None = None) -> dict:
    fd, path = _acquire_lock(root)
    try:
        return _check_locked(force, root, now)
    finally:
        _release_lock(fd, path)


def decline(commit: str, root: Path = SKILL_ROOT) -> dict:
    fd, path = _acquire_lock(root)
    try:
        return _decline_locked(commit, root)
    finally:
        _release_lock(fd, path)


def _backup(root: Path, baseline: dict, backup: Path) -> None:
    backup.mkdir(parents=True, mode=0o700)
    for relative in baseline["files"]:
        source = root / relative
        destination = backup / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination, follow_symlinks=False)
    shutil.copy2(root / MANIFEST_NAME, backup / MANIFEST_NAME, follow_symlinks=False)


def _install_locked(commit: str, root: Path) -> dict:
    state = load_state(root)
    if state is None:
        raise UpdaterError("update consent is required")
    if not state["checks_enabled"]:
        raise UpdaterError("update checks are disabled")
    candidate = state.get("candidate")
    if not candidate or candidate.get("commit") != commit:
        raise UpdaterError("approve-commit does not match the cached candidate")
    if in_git_checkout(root):
        raise UpdaterError("refusing to update an Astra Helm installation inside a Git checkout")
    target = validate_manifest({key: candidate.get(key) for key in ("version", "notes", "files")})
    baseline = read_local_manifest(root)
    if semver(target["version"]) <= semver(baseline["version"]):
        raise UpdaterError("cached candidate is not newer than the installed version")
    changes = installation_changes(root, baseline, target)
    if changes:
        return {"status": "local_modifications", "changes": changes}

    stage: Path | None = None
    backups_root = root / ".update-backups"
    backup = backups_root / f"{format_time(utc_now()).replace(':', '')}-{commit[:12]}-{uuid.uuid4().hex[:8]}"
    created: list[Path] = []
    mutation_started = False
    try:
        backup_kind = _path_kind(backups_root)
        if backup_kind not in ("missing", "directory"):
            raise UpdaterError("private update backup path must be a real directory")
        if backup_kind == "missing":
            backups_root.mkdir(mode=0o700)
        os.chmod(backups_root, 0o700)
        stage = Path(tempfile.mkdtemp(prefix=".astra-helm-stage-", dir=root.parent))
        os.chmod(stage, 0o700)
        _download_candidate(commit, target, stage)
        changes = installation_changes(root, baseline, target)
        if changes:
            return {"status": "local_modifications", "changes": changes}
        _backup(root, baseline, backup)
        mutation_started = True
        for relative in target["files"]:
            destination = root / relative
            missing_parents: list[Path] = []
            parent = destination.parent
            while parent != root and not parent.exists():
                missing_parents.append(parent)
                parent = parent.parent
            for directory in reversed(missing_parents):
                directory.mkdir()
                created.append(directory)
            os.replace(stage / relative, destination)
        for relative in sorted(set(baseline["files"]) - set(target["files"]), reverse=True):
            (root / relative).unlink()
        manifest_payload = (json.dumps(target, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        staged_manifest = stage / MANIFEST_NAME
        staged_manifest.write_bytes(manifest_payload)
        os.replace(staged_manifest, root / MANIFEST_NAME)
        state["candidate"] = None
        state["last_check"] = {
            "status": "installed", "checked_at": format_time(utc_now()), "error": None,
        }
        write_state(root, state)
        return {
            "status": "installed", "version": target["version"], "commit": commit,
            "backup": str(backup),
        }
    except BaseException as exc:
        rollback_failures: list[str] = []
        if mutation_started:
            for relative in set(baseline["files"]) | set(target["files"]):
                destination = root / relative
                saved = backup / relative
                try:
                    if relative in baseline["files"]:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(saved, destination)
                    elif _path_kind(destination) != "missing":
                        destination.unlink()
                except OSError as rollback_exc:
                    rollback_failures.append(f"{relative}: {rollback_exc}")
            try:
                shutil.copy2(backup / MANIFEST_NAME, root / MANIFEST_NAME)
            except OSError as rollback_exc:
                rollback_failures.append(f"{MANIFEST_NAME}: {rollback_exc}")
            for directory in reversed(created):
                try:
                    directory.rmdir()
                except OSError:
                    pass
        if rollback_failures and isinstance(exc, Exception):
            raise UpdaterError(
                f"update failed ({exc}); rollback incomplete: " + "; ".join(rollback_failures)
            ) from exc
        raise
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)


def install(commit: str, root: Path = SKILL_ROOT) -> dict:
    if not SHA_RE.fullmatch(commit):
        raise UpdaterError("approve-commit must be a 40-character lowercase SHA")
    fd, path = _acquire_lock(root)
    try:
        return _install_locked(commit, root)
    finally:
        _release_lock(fd, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="show local updater state without network access")
    configure_parser = commands.add_parser("configure", help="enable or disable update checks")
    configure_parser.add_argument("--checks", required=True, choices=("on", "off"))
    check_parser = commands.add_parser("check", help="check the official origin for an update")
    check_parser.add_argument("--force", action="store_true", help="bypass the weekly attempt throttle")
    decline_parser = commands.add_parser("decline", help="decline the cached candidate version")
    decline_parser.add_argument("--commit", required=True)
    install_parser = commands.add_parser("install", help="install an explicitly approved cached candidate")
    install_parser.add_argument("--approve-commit", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "status":
            result = status()
        elif args.command == "configure":
            result = configure(args.checks == "on")
        elif args.command == "check":
            result = check(args.force)
        elif args.command == "decline":
            result = decline(args.commit)
        else:
            result = install(args.approve_commit)
    except UpdaterError as exc:
        result = {"status": "error", "error": str(exc)}
    except Exception as exc:
        result = {"status": "error", "error": f"unexpected updater error: {exc}"}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 1 if result.get("status") == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
