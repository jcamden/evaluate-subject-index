#!/usr/bin/env python3
"""Regression coverage for worker launch-prompt rendering."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "worker_prompt_cli.py"


def prompt_spec() -> dict:
    sha = "a" * 64
    return {
        "schema_version": "locator-worker-prompt-pack-v1",
        "evaluation_id": "evaluation-example",
        "candidate_id": "candidate-example",
        "project": "owner/candidate-evaluation",
        "base_branch": "main",
        "base_commit": "b" * 40,
        "benchmark_project": "owner/benchmark",
        "benchmark_ref": "c" * 40,
        "benchmark_canonical_sha256": sha,
        "source_sha256": sha,
        "candidate_identity_sha256": sha,
        "normalized_candidate_sha256": sha,
        "item_inventory_sha256": sha,
        "policy_file_sha256": sha,
        "page_map_canonical_sha256": sha,
        "chunk_manifest_canonical_sha256": sha,
        "benchmark_lock_file_sha256": sha,
        "benchmark_lock_canonical_sha256": sha,
        "checkpoint_library_root": "/IndexPDF/evaluations/candidate-example/canonical-integration",
        "checkpoint_filename": "locator-packets-checkpoint-portable.zip",
        "checkpoint_sha256": sha,
        "worker_library_root": "/IndexPDF/evaluations/candidate-example/workers",
        "chunks": [
            {
                "chunk_id": "CHUNK-001",
                "source_unit": "Chapter One",
                "owned_document_pages": "1–20",
                "locator_packet_path": "candidate/candidate-example/locator-packets/candidate-locator-CHUNK-001.json",
                "locator_packet_sha256": sha,
                "expected_locator_assignments": 42,
                "source_library_path": "/Sources/chunks/CHUNK-001.pdf",
                "source_materialize_path": "source/chunks/CHUNK-001.pdf",
                "source_sha256": sha,
                "sidecar_library_path": "/Sources/chunks/CHUNK-001.pages.json",
                "sidecar_materialize_path": "source/chunks/CHUNK-001.pages.json",
                "sidecar_sha256": sha,
            }
        ],
    }


class WorkerPromptCliTests(unittest.TestCase):
    def test_locator_pack_requires_final_publication_bound_library_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "spec.json"
            output_path = root / "worker-locator-audit-prompts.md"
            input_path.write_text(json.dumps(prompt_spec()), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "render-locator-pack", "--input", str(input_path), "--output", str(output_path)],
                cwd=SKILL_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
            result = json.loads(completed.stdout)
            self.assertTrue(result["ok"])
            rendered = output_path.read_text(encoding="utf-8")
            self.assertIn("final publication-bound `locator-audit-worker-receipt.json`", rendered)
            self.assertIn("receipt-bound `locator-audit-worker-recovery.zip`", rendered)
            self.assertIn("/IndexPDF/evaluations/candidate-example/workers/locator-audit/CHUNK-001/", rendered)
            self.assertIn("replacing the earlier pre-publication receipt", rendered)
            self.assertIn("exact pull-request URL and head commit", rendered)
            self.assertIn("Do not modify or merge the pull request afterward", rendered)

    def test_duplicate_chunk_ids_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec = prompt_spec()
            spec["chunks"].append(dict(spec["chunks"][0]))
            input_path = root / "spec.json"
            output_path = root / "prompts.md"
            input_path.write_text(json.dumps(spec), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "render-locator-pack", "--input", str(input_path), "--output", str(output_path)],
                cwd=SKILL_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("duplicate chunk_id", completed.stdout)
            self.assertFalse(output_path.exists())

    def test_public_evaluation_profile_names_canonical_audit_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec = prompt_spec()
            spec["publication_profile"] = "public_evaluation_artifacts"
            input_path = root / "spec.json"
            output_path = root / "prompts.md"
            input_path.write_text(json.dumps(spec), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "render-locator-pack", "--input", str(input_path), "--output", str(output_path)],
                cwd=SKILL_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
            rendered = output_path.read_text(encoding="utf-8")
            self.assertIn("Publication profile: public_evaluation_artifacts", rendered)
            self.assertIn(
                "candidate/locator-audits/locator-audit.CHUNK-001.v1.json",
                rendered,
            )
            self.assertIn("exact validated canonical audit bytes", rendered)


if __name__ == "__main__":
    unittest.main()
