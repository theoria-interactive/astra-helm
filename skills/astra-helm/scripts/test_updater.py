#!/usr/bin/env python3

import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).with_name("updater.py")
SPEC = importlib.util.spec_from_file_location("astra_helm_updater", MODULE_PATH)
updater = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(updater)


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base / "astra-helm"
        self.root.mkdir()
        self.old_files = self.release_files("1.4.1", "old")
        self.write_install("1.4.1", self.old_files)
        (self.root / "settings.json").write_text('{"local":true}\n', encoding="utf-8")
        self.commit = "a" * 40

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def release_files(version, marker, extra=None):
        files = {
            "SKILL.md": f"---\nname: astra-helm\ndescription: Test skill\n---\n\n# {marker}\n".encode(),
            "policy.json": (json.dumps({"version": version, "marker": marker}) + "\n").encode(),
            "scripts/updater.py": f"# {marker} updater\n".encode(),
        }
        files.update(extra or {})
        return files

    @staticmethod
    def manifest(version, files, notes=None):
        return {
            "version": version,
            "notes": notes or [f"Release {version}"],
            "files": {name: updater.sha256_bytes(body) for name, body in files.items()},
        }

    def write_install(self, version, files):
        for relative, body in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        (self.root / updater.MANIFEST_NAME).write_text(
            json.dumps(self.manifest(version, files)) + "\n", encoding="utf-8"
        )

    def enable(self):
        updater.configure(True, self.root)

    def cache(self, version="1.5.0", files=None, commit=None):
        files = files or self.release_files(version, "new")
        commit = commit or self.commit
        state = updater.load_state(self.root) or updater.default_state(True)
        state["checks_enabled"] = True
        state["candidate"] = {
            **self.manifest(version, files),
            "commit": commit,
            "fetched_at": "2026-09-10T00:00:00Z",
        }
        updater.write_state(self.root, state)
        return files

    def network(self, files, version="1.5.0", commit=None, bad_file=None):
        commit = commit or self.commit
        manifest = self.manifest(version, files)

        def open_url(url, max_bytes):
            if url == updater.API_URL:
                return json.dumps({"object": {"sha": commit, "type": "commit"}}).encode()
            if url == updater.raw_url(commit, updater.MANIFEST_NAME):
                return json.dumps(manifest).encode()
            relative = url.split(f"/{updater.REMOTE_SUBDIR}/", 1)[1]
            if relative == bad_file:
                return b"tampered"
            return files[relative]

        return mock.patch.object(updater, "_open_url", side_effect=open_url)

    def test_status_and_unknown_consent_are_strictly_offline(self):
        with mock.patch.object(updater, "fetch_candidate") as fetch:
            report = updater.status(self.root)
            check = updater.check(root=self.root)
        self.assertEqual(report["status"], "consent_required")
        self.assertEqual(check["status"], "consent_required")
        fetch.assert_not_called()

        updater.configure(False, self.root)
        with mock.patch.object(updater, "fetch_candidate") as fetch:
            self.assertEqual(updater.check(root=self.root)["status"], "checks_disabled")
        fetch.assert_not_called()
        self.assertEqual((self.root / "settings.json").read_text(), '{"local":true}\n')
        self.assertEqual(os.stat(self.root / updater.STATE_NAME).st_mode & 0o777, 0o600)

    def test_failed_attempt_is_throttled_and_force_is_explicit_bypass(self):
        self.enable()
        now = dt.datetime(2026, 9, 10, tzinfo=dt.timezone.utc)
        with mock.patch.object(updater, "fetch_candidate", side_effect=updater.UpdaterError("offline")):
            first = updater.check(root=self.root, now=now)
        self.assertEqual(first["status"], "error")
        with mock.patch.object(updater, "fetch_candidate") as fetch:
            second = updater.check(root=self.root, now=now + dt.timedelta(days=1))
        self.assertEqual(second["status"], "throttled")
        fetch.assert_not_called()
        with mock.patch.object(updater, "fetch_candidate", side_effect=updater.UpdaterError("still offline")) as fetch:
            forced = updater.check(force=True, root=self.root, now=now + dt.timedelta(days=1))
        self.assertEqual(forced["status"], "error")
        fetch.assert_called_once()

    def test_newer_version_is_pinned_and_decline_remembers_version(self):
        self.enable()
        files = self.release_files("1.5.0", "new")
        with self.network(files):
            result = updater.check(root=self.root)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["pinned_commit"], self.commit)
        self.assertEqual(updater.load_state(self.root)["candidate"]["commit"], self.commit)
        self.assertEqual(updater.decline(self.commit, self.root)["version"], "1.5.0")

        newer_sha = "b" * 40
        with self.network(files, commit=newer_sha):
            repeated = updater.check(force=True, root=self.root)
        self.assertEqual(repeated["status"], "declined")
        self.assertIsNone(updater.load_state(self.root)["candidate"])

    def test_malicious_manifests_are_rejected(self):
        files = self.release_files("1.5.0", "new")
        base = self.manifest("1.5.0", files)
        invalid = []
        for path in (
            "../escape", "settings.json", "SETTINGS.JSON", ".git/config",
            "update-manifest.json", "UPDATE-MANIFEST.JSON", "a?x",
            ".telemetry-state.json", ".telemetry-lock",
        ):
            value = json.loads(json.dumps(base))
            value["files"][path] = "0" * 64
            invalid.append(value)
        prefix = json.loads(json.dumps(base))
        prefix["files"]["scripts"] = "0" * 64
        invalid.append(prefix)
        case_collision = json.loads(json.dumps(base))
        case_collision["files"]["skill.md"] = "0" * 64
        invalid.append(case_collision)
        missing = json.loads(json.dumps(base))
        del missing["files"]["SKILL.md"]
        invalid.append(missing)
        invalid.append({**base, "version": "v1.5"})
        invalid.append({**base, "extra": True})
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(updater.UpdaterError):
                updater.validate_manifest(value)

    def test_pin_and_download_hash_must_match(self):
        self.enable()
        files = self.cache()
        with self.assertRaisesRegex(updater.UpdaterError, "does not match"):
            updater.install("b" * 40, self.root)
        with self.network(files, bad_file="policy.json"):
            with self.assertRaisesRegex(updater.UpdaterError, "hash mismatch"):
                updater.install(self.commit, self.root)
        self.assertEqual((self.root / "policy.json").read_bytes(), self.old_files["policy.json"])

    def test_modified_managed_file_refuses_before_network_and_preserves_settings(self):
        self.enable()
        self.cache()
        (self.root / "SKILL.md").write_text("locally edited\n", encoding="utf-8")
        with mock.patch.object(updater, "_open_url") as network:
            result = updater.install(self.commit, self.root)
        self.assertEqual(result["status"], "local_modifications")
        self.assertEqual(result["changes"][0]["path"], "SKILL.md")
        network.assert_not_called()
        self.assertEqual((self.root / "settings.json").read_text(), '{"local":true}\n')

    def test_deleted_managed_file_and_unknown_target_collision_refuse(self):
        self.enable()
        files = self.release_files("1.5.0", "new", {"references/new.md": b"new\n"})
        self.cache(files=files)
        (self.root / "policy.json").unlink()
        collision = self.root / "references" / "new.md"
        collision.parent.mkdir()
        collision.write_text("mine\n", encoding="utf-8")
        result = updater.install(self.commit, self.root)
        reasons = {item["reason"] for item in result["changes"]}
        self.assertIn("deleted", reasons)
        self.assertIn("unknown target collision", reasons)

    def test_install_preserves_settings_and_keeps_private_backup(self):
        consent = json.dumps({
            "schema_version": 1,
            "consent": {
                "enabled": True,
                "automatic_sending": True,
                "consented_at": "2026-09-09T00:00:00Z",
                "endpoint": "https://example.test/v1/events",
                "disclosure_version": "3",
                "retention_days": 30,
                "evidence": {
                    "prompt": "May Astra Helm automatically send the disclosed telemetry?",
                    "response": "Yes.",
                    "source": "explicit user response in task",
                },
            },
            "runs": {},
        }, sort_keys=True) + "\n"
        (self.root / ".telemetry-state.json").write_text(consent)
        self.enable()
        files = self.cache()
        with self.network(files):
            result = updater.install(self.commit, self.root)
        self.assertEqual(result["status"], "installed")
        self.assertEqual((self.root / "policy.json").read_bytes(), files["policy.json"])
        self.assertEqual((self.root / "settings.json").read_text(), '{"local":true}\n')
        self.assertEqual((self.root / ".telemetry-state.json").read_text(), consent)
        backup = Path(result["backup"])
        self.assertTrue(backup.is_relative_to(self.root / ".update-backups"))
        self.assertEqual((backup / "policy.json").read_bytes(), self.old_files["policy.json"])
        self.assertEqual(updater.read_local_manifest(self.root)["version"], "1.5.0")
        self.assertIsNone(updater.load_state(self.root)["candidate"])
        follow_up = result["follow_up"]
        self.assertEqual(follow_up["action"], "check_telemetry_status")
        self.assertFalse(follow_up["execute"])
        self.assertEqual(follow_up["ask_separately_only_if_decision"], ["unset", "renewal_required"])
        self.assertFalse(follow_up["installation_approval_is_telemetry_consent"])
        self.assertEqual(follow_up["helper"], "scripts/telemetry.py")
        self.assertEqual(follow_up["arguments"], ["status"])
        self.assertNotIn(str(self.root), json.dumps(follow_up))

    def test_failed_mutation_rolls_back_replaced_and_removed_files(self):
        old = self.release_files("1.4.1", "old", {"obsolete.txt": b"old managed\n"})
        self.write_install("1.4.1", old)
        self.enable()
        files = self.cache()
        original_replace = updater.os.replace

        def fail_manifest(source, destination):
            if Path(destination) == self.root / updater.MANIFEST_NAME:
                raise OSError("injected manifest failure")
            return original_replace(source, destination)

        with self.network(files), mock.patch.object(updater.os, "replace", side_effect=fail_manifest):
            with self.assertRaisesRegex(OSError, "injected"):
                updater.install(self.commit, self.root)
        for relative, body in old.items():
            self.assertEqual((self.root / relative).read_bytes(), body)
        self.assertEqual(updater.read_local_manifest(self.root)["version"], "1.4.1")
        self.assertFalse((self.root / updater.LOCK_NAME).exists())

    def test_stale_candidate_cannot_downgrade_and_git_checkout_refuses(self):
        self.enable()
        self.cache(version="1.5.0")
        newer = self.release_files("1.6.0", "newer")
        self.write_install("1.6.0", newer)
        with self.assertRaisesRegex(updater.UpdaterError, "not newer"):
            updater.install(self.commit, self.root)
        self.write_install("1.4.1", self.old_files)
        (self.base / ".git").mkdir()
        with self.assertRaisesRegex(updater.UpdaterError, "Git checkout"):
            updater.install(self.commit, self.root)

    def test_lock_contention_is_immediate_and_non_mutating(self):
        lock = self.root / updater.LOCK_NAME
        lock.write_text("other\n", encoding="utf-8")
        with self.assertRaisesRegex(updater.UpdaterError, "in progress"):
            updater.configure(True, self.root)
        with self.assertRaisesRegex(updater.UpdaterError, "in progress"):
            updater.check(root=self.root)
        self.assertFalse((self.root / updater.STATE_NAME).exists())


if __name__ == "__main__":
    unittest.main()
