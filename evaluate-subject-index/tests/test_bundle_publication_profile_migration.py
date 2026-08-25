#!/usr/bin/env python3
"""Regression coverage for guarded checkpoint publication-profile migration."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "bundle_cli.py"


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def write_legacy_bundle(path: Path, locator_status: str = "not_started") -> None:
    state = {
        "schema_version": "subject-index-evaluation-state-v4",
        "evaluation_id": "evaluation-example",
        "artifact_manifest_path": "artifact-manifest.json",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "configuration": {"storage_mode": "hybrid"},
        "stages": {
            "locator_audit": {"status": locator_status, "updated_at": None, "notes": []},
            "missing_access_audit": {"status": "not_started", "updated_at": None, "notes": []},
            "structure_audit": {"status": "not_started", "updated_at": None, "notes": []},
            "scoring": {"status": "not_started", "updated_at": None, "notes": []},
        },
    }
    manifest = {
        "schema_version": "subject-index-artifact-manifest-v1",
        "evaluation_id": "evaluation-example",
        "artifacts": [],
    }
    state_payload = json_bytes(state)
    manifest_payload = json_bytes(manifest)
    metadata = {
        "schema_version": "subject-index-bundle-v1",
        "evaluation_id": "evaluation-example",
        "profile": "portable",
        "created_at": "2026-01-01T00:00:00Z",
        "state_sha256": hashlib.sha256(state_payload).hexdigest(),
        "manifest_sha256": hashlib.sha256(manifest_payload).hexdigest(),
        "included_paths": ["artifact-manifest.json", "evaluation-state.json"],
        "excluded": [],
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("artifact-manifest.json", manifest_payload)
        archive.writestr("evaluation-state.json", state_payload)
        archive.writestr("bundle-metadata.json", json_bytes(metadata))


def run(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        cwd=SKILL_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class BundlePublicationProfileMigrationTests(unittest.TestCase):
    def test_migrates_legacy_pre_audit_checkpoint_and_revalidates_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "legacy.zip"
            migrated = root / "migrated.zip"
            write_legacy_bundle(source)
            completed = run(
                "migrate-publication-profile",
                "--input", source,
                "--output", migrated,
                "--from-profile", "aggregate_only",
                "--publication-profile", "public_evaluation_artifacts",
            )
            self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
            result = json.loads(completed.stdout)
            self.assertTrue(result["ok"])
            self.assertFalse(result["source_profile_was_explicit"])
            with zipfile.ZipFile(source) as before, zipfile.ZipFile(migrated) as after:
                before_manifest = before.read("artifact-manifest.json")
                after_manifest = after.read("artifact-manifest.json")
                self.assertEqual(before_manifest, after_manifest)
                state = json.loads(after.read("evaluation-state.json"))
                metadata = json.loads(after.read("bundle-metadata.json"))
            self.assertEqual("public_evaluation_artifacts", state["configuration"]["publication_profile"])
            self.assertEqual(hashlib.sha256(json_bytes(state)).hexdigest(), metadata["state_sha256"])
            imported = root / "imported"
            imported_result = run("import-bundle", "--input", migrated, "--output-dir", imported)
            self.assertEqual(0, imported_result.returncode, imported_result.stderr or imported_result.stdout)

    def test_refuses_checkpoint_after_locator_audit_started(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "legacy.zip"
            migrated = root / "migrated.zip"
            write_legacy_bundle(source, locator_status="in_progress")
            completed = run(
                "migrate-publication-profile",
                "--input", source,
                "--output", migrated,
                "--from-profile", "aggregate_only",
                "--publication-profile", "public_evaluation_artifacts",
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("candidate_audit_migration_requires_revalidation", completed.stdout)
            self.assertFalse(migrated.exists())


if __name__ == "__main__":
    unittest.main()
