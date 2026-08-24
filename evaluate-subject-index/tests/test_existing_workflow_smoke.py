#!/usr/bin/env python3
"""Synthetic smoke coverage for established evaluate-subject-index workflows."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
FIXTURES = SKILL_ROOT / "tests"
STAMP = "2026-08-24T12:00:00Z"
SOURCE_SHA = "986a741c3f4566cb788fd9e6fed021355e4fc4ff7ca36a270eb957efbbdc5415"
POLICY_SHA = "2" * 64

EXPECTED_STAGES = [
    "initialize",
    "page_mapping",
    "chunk_definition",
    "define_policy",
    "source_chunk_preparation",
    "source_subject_discovery",
    "benchmark_synthesis",
    "benchmark_review",
    "benchmark_freeze",
    "candidate_normalization",
    "locator_chunk_preparation",
    "locator_audit",
    "missing_access_audit",
    "structure_audit",
    "scoring",
    "web_report",
]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: dict[str, Any], excluded_field: str) -> str:
    clone = copy.deepcopy(value)
    clone.pop(excluded_field, None)
    encoded = json.dumps(clone, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_cli(script: str, *arguments: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *map(str, arguments)],
        cwd=SKILL_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - diagnostic path
        raise AssertionError(
            f"{script} emitted non-JSON output\nstdout={completed.stdout}\nstderr={completed.stderr}"
        ) from exc
    if completed.returncode != 0 or payload.get("ok") is not True:
        raise AssertionError(
            f"{script} failed with {completed.returncode}\nargs={arguments}\n"
            f"stdout={completed.stdout}\nstderr={completed.stderr}"
        )
    return payload


def artifact_records(root: Path, stage: str, artifact_type: str, path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    relative = path.relative_to(root).as_posix()
    digest = sha256_file(path)
    artifact_id = "ART-" + hashlib.sha256(f"{relative}\0{digest}".encode("utf-8")).hexdigest()[:12].upper()
    manifest_record = {
        "artifact_id": artifact_id,
        "stage": stage,
        "artifact_type": artifact_type,
        "path": relative,
        "sha256": digest,
        "media_type": "application/json",
        "visibility": "private",
        "retention": "required",
        "frozen": True,
        "recorded_at": STAMP,
    }
    state_record = {key: value for key, value in manifest_record.items() if key != "media_type"}
    return manifest_record, state_record


class ExistingWorkflowSmokeTests(unittest.TestCase):
    maxDiff = None

    def test_two_chunk_discovery_state_and_portable_bundles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_dir = root / "source"
            page_map_input = root / "page-map-input.json"
            chunk_input = root / "chunk-manifest.input.json"
            page_map = source_dir / "page-map.json"
            chunk_manifest = source_dir / "chunk-manifest.json"
            policy = source_dir / "evaluation-policy.json"
            source_inventory = source_dir / "source-chunk-inventory.json"
            state_path = root / "evaluation-state.json"
            manifest_path = root / "artifact-manifest.json"

            shutil.copyfile(FIXTURES / "page-map-input.valid.json", page_map_input)
            shutil.copyfile(FIXTURES / "chunk-manifest.input.json", chunk_input)
            run_cli("page_chunk_cli.py", "expand-page-map", "--input", page_map_input, "--output", page_map)
            run_cli(
                "page_chunk_cli.py",
                "validate-chunks",
                "--input",
                chunk_input,
                "--page-map",
                page_map,
                "--output",
                chunk_manifest,
            )
            page_map_data = read_json(page_map)
            chunk_data = read_json(chunk_manifest)
            write_json(
                policy,
                {
                    "schema_version": "synthetic-policy-v1",
                    "source_sha256": SOURCE_SHA,
                    "policy_sha256": POLICY_SHA,
                },
            )
            write_json(
                source_inventory,
                {
                    "schema_version": "synthetic-source-chunk-inventory-v1",
                    "source_sha256": SOURCE_SHA,
                    "chunk_ids": ["CHUNK-001", "CHUNK-002"],
                },
            )

            completed = {
                "initialize",
                "page_mapping",
                "chunk_definition",
                "define_policy",
                "source_chunk_preparation",
            }
            stages = {
                name: {
                    "status": "completed" if name in completed else "not_started",
                    "updated_at": STAMP if name in completed else None,
                    "notes": [],
                }
                for name in EXPECTED_STAGES
            }
            manifest_artifacts: list[dict[str, Any]] = []
            state_artifacts: list[dict[str, Any]] = []
            for stage, artifact_type, path in (
                ("page_mapping", "page_map", page_map),
                ("chunk_definition", "chunk_manifest", chunk_manifest),
                ("define_policy", "evaluation_policy", policy),
                ("source_chunk_preparation", "source_chunk_inventory", source_inventory),
            ):
                manifest_record, state_record = artifact_records(root, stage, artifact_type, path)
                manifest_artifacts.append(manifest_record)
                state_artifacts.append(state_record)

            state = {
                "schema_version": "subject-index-evaluation-state-v4",
                "evaluation_id": "synthetic-existing-workflow-smoke",
                "artifact_manifest_path": "artifact-manifest.json",
                "created_at": STAMP,
                "updated_at": STAMP,
                "source": {
                    "title": "The Clockwork Orchard",
                    "edition": "Synthetic edition",
                    "filename": "clockwork-orchard.pdf",
                    "sha256": SOURCE_SHA,
                    "document_page_span": [1, 10],
                    "document_page_basis": "one_based_inclusive",
                },
                "candidate": None,
                "configuration": {
                    "audit_mode": "full",
                    "index_type": "subject_index",
                    "intended_readership": "synthetic_test_readers",
                    "readership_provenance": {
                        "basis": "inferred",
                        "confidence": "high",
                        "rationale": "Synthetic fixture.",
                    },
                    "output_format": "json",
                    "storage_mode": "local",
                    "policy_profile": "subject-index-standard-policy-v1",
                    "rubric_version": "subject-index-rubric-v4",
                },
                "stages": stages,
                "artifacts": sorted(state_artifacts, key=lambda item: item["path"]),
                "blockers": [],
            }
            manifest = {
                "schema_version": "subject-index-artifact-manifest-v1",
                "evaluation_id": state["evaluation_id"],
                "created_at": STAMP,
                "updated_at": STAMP,
                "artifacts": sorted(manifest_artifacts, key=lambda item: item["path"]),
            }
            write_json(state_path, state)
            write_json(manifest_path, manifest)

            pages_by_number = {item["document_page"]: item for item in page_map_data["pages"]}
            worker_artifacts: list[Path] = []
            for index, chunk in enumerate(chunk_data["chunks"], start=1):
                chunk_id = chunk["chunk_id"]
                owned_pages = [
                    page
                    for start, end in chunk["owned_document_page_ranges"]
                    for page in range(start, end + 1)
                ]
                context_pages = [
                    page
                    for start, end in chunk["context_document_page_ranges"]
                    for page in range(start, end + 1)
                ]
                evidence_page = owned_pages[0]
                artifact = root / "workers" / chunk_id / f"source-subject-chunk.{chunk_id}.json"
                write_json(
                    artifact,
                    {
                        "schema_version": "source-subject-chunk-v1",
                        "evaluation_id": state["evaluation_id"],
                        "chunk": {
                            "chunk_id": chunk_id,
                            "chapter_labels": chunk["source_units"],
                            "owned_document_pages": owned_pages,
                            "context_document_pages": context_pages,
                        },
                        "candidate_blindness": "preserved",
                        "page_review": {
                            "expected_owned_pages": len(owned_pages),
                            "reviewed_owned_pages": len(owned_pages),
                            "indexable_source_words": 1000 + index,
                            "complete": True,
                        },
                        "provenance": {
                            "source_sha256": SOURCE_SHA,
                            "page_map_sha256": chunk_data["page_map_sha256"],
                            "chunk_manifest_sha256": chunk_data["chunk_manifest_sha256"],
                            "policy_sha256": POLICY_SHA,
                        },
                        "subjects": [
                            {
                                "local_subject_id": f"LOCAL-{index:03d}",
                                "label": f"Clockwork orchard theme {index}",
                                "priority": "major",
                                "meaning": "A fictional subject used only for deterministic smoke testing.",
                                "stance": "Treated as a fictional mechanism in the synthetic source.",
                                "acceptable_access": [f"clockwork theme {index}"],
                                "evidence": [
                                    {
                                        "document_page": evidence_page,
                                        "source_page_label": pages_by_number[evidence_page]["source_page_label"],
                                        "locator_class": "principal",
                                        "evidence_summary": "Synthetic treatment of the fictional mechanism.",
                                    }
                                ],
                            }
                        ],
                        "exclusions": [],
                        "uncertainties": [],
                    },
                )
                worker_artifacts.append(artifact)
                receipt = artifact.parent / "worker-discovery-receipt.json"
                payload = run_cli(
                    "parallel_discovery_cli.py",
                    "worker-receipt",
                    "--state",
                    state_path,
                    "--chunk-manifest",
                    chunk_manifest,
                    "--artifact",
                    artifact,
                    "--chunk-id",
                    chunk_id,
                    "--project",
                    "example/synthetic-benchmark",
                    "--base-commit",
                    "a" * 40,
                    "--output",
                    receipt,
                )
                self.assertEqual(chunk_id, payload["chunk_id"])
                self.assertTrue(receipt.is_file())

            integration_arguments: list[str] = [
                "integrate",
                "--state",
                str(state_path),
                "--chunk-manifest",
                str(chunk_manifest),
            ]
            for artifact in worker_artifacts:
                integration_arguments.extend(["--artifact", str(artifact)])
            integrated = run_cli("parallel_discovery_cli.py", *integration_arguments)
            self.assertEqual("completed", integrated["source_subject_discovery_status"])
            self.assertEqual(2, integrated["active_chunk_count"])
            self.assertEqual([], integrated["missing_chunks"])

            validation = run_cli("state_cli.py", "validate", "--state", state_path)
            self.assertEqual([], validation["errors"])

            checkpoint = root / "exports" / "synthetic-checkpoint.zip"
            export = root / "exports" / "synthetic-export.zip"
            checkpoint_payload = run_cli(
                "bundle_cli.py", "checkpoint", "--state", state_path, "--profile", "portable", "--output", checkpoint
            )
            export_payload = run_cli(
                "bundle_cli.py", "export-bundle", "--state", state_path, "--profile", "portable", "--output", export
            )
            self.assertEqual("portable", checkpoint_payload["profile"])
            self.assertEqual("portable", export_payload["profile"])
            self.assertTrue(checkpoint.is_file())
            self.assertTrue(export.is_file())

            imported_root = root / "imported"
            imported = run_cli("bundle_cli.py", "import-bundle", "--input", export, "--output-dir", imported_root)
            self.assertEqual([], imported["reconnect_required"])
            imported_validation = run_cli(
                "state_cli.py", "validate", "--state", imported_root / "evaluation-state.json"
            )
            self.assertEqual([], imported_validation["errors"])

    def test_page_routing_item_grading_and_score_arithmetic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            page_map = root / "page-map.json"
            chunks = root / "chunk-manifest.json"
            packets = root / "locator-packets"
            inventory = root / "item-inventory.json"
            assessments = root / "item-assessments.json"
            scorecard = root / "scorecard.json"

            run_cli(
                "page_chunk_cli.py",
                "expand-page-map",
                "--input",
                FIXTURES / "page-map-input.valid.json",
                "--output",
                page_map,
            )
            run_cli(
                "page_chunk_cli.py",
                "validate-chunks",
                "--input",
                FIXTURES / "chunk-manifest.input.json",
                "--page-map",
                page_map,
                "--output",
                chunks,
            )
            routed = run_cli(
                "page_chunk_cli.py",
                "filter-candidate",
                "--candidate",
                FIXTURES / "candidate-index.valid.json",
                "--page-map",
                page_map,
                "--chunks",
                chunks,
                "--benchmark-lock",
                FIXTURES / "candidate-benchmark-lock.valid.json",
                "--output-dir",
                packets,
            )
            self.assertEqual(0, routed["exception_count"])
            first_packet = read_json(packets / "candidate-locator-CHUNK-001.json")
            second_packet = read_json(packets / "candidate-locator-CHUNK-002.json")
            self.assertEqual(1, first_packet["summary"]["locator_assignment_count"])
            self.assertEqual(2, second_packet["summary"]["locator_assignment_count"])

            inventory_payload = run_cli(
                "item_grade_cli.py",
                "build-inventory",
                "--candidate",
                FIXTURES / "candidate-index.valid.json",
                "--output",
                inventory,
            )
            self.assertEqual("subject-index-item-inventory-v2", inventory_payload["schema_version"])
            assessment_payload = run_cli(
                "item_grade_cli.py",
                "build-assessments",
                "--candidate",
                FIXTURES / "candidate-index.valid.json",
                "--inventory",
                inventory,
                "--locator-audit",
                FIXTURES / "locator-audit.item-grading.valid.json",
                "--missing-access-audit",
                FIXTURES / "missing-access-audit.item-grading.valid.json",
                "--structure-audit",
                FIXTURES / "structure-audit.item-grading.valid.json",
                "--audit-mode",
                "full",
                "--evaluation-id",
                "eval-item-test",
                "--output",
                assessments,
            )
            self.assertTrue(assessment_payload["scope_complete"])
            self.assertEqual(3, assessment_payload["summary"]["locators"]["graded"])
            self.assertEqual(0, assessment_payload["summary"]["locators"]["not_measured"])

            score_payload = run_cli(
                "score_cli.py",
                "scorecard",
                "--input",
                FIXTURES / "scorecard.valid.json",
                "--output",
                scorecard,
            )
            self.assertTrue(score_payload["arithmetic_check"])
            self.assertEqual(84.5, score_payload["total_score"])
            self.assertEqual(100, score_payload["maximum_score"])
            self.assertTrue(scorecard.is_file())

    def test_benchmark_review_and_final_freeze_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            draft = root / "source-benchmark.draft.v1.json"
            inventory = root / "source-benchmark-review-inventory.json"
            review = root / "source-benchmark-review.v1.json"
            final = root / "source-benchmark.v1.json"
            shutil.copyfile(FIXTURES / "source-benchmark.draft.valid.json", draft)

            screen = run_cli("benchmark_review_cli.py", "screen", "--draft", draft, "--output", inventory)
            self.assertEqual(3, screen["denominators"]["subjects"])
            inventory_data = read_json(inventory)
            queues = inventory_data["queues"]
            draft_data = read_json(draft)
            review_data = {
                "schema_version": "source-benchmark-review-v1",
                "evaluation_id": draft_data["evaluation_id"],
                "review_mode": "full",
                "draft": {
                    "file_sha256": sha256_file(draft),
                    "canonical_sha256": canonical_hash(draft_data, "benchmark_sha256"),
                },
                "candidate_blindness": "preserved",
                "reviewer_independence": {
                    "candidate_unseen": True,
                    "fresh_context": True,
                    "source_reconnected_sha256": draft_data["source_sha256"],
                },
                "coverage": {
                    "subject_ids_reviewed": queues["subject_ids"],
                    "relationship_ids_reviewed": queues["relationship_ids"],
                    "reader_task_ids_reviewed": queues["reader_task_ids"],
                    "cross_chapter_subject_ids_reviewed": queues["cross_chapter_subject_ids"],
                    "unresolved_relationship_ids_dispositioned": queues["unresolved_relationship_ids"],
                    "fallback_reader_task_ids_reviewed": queues["fallback_reader_task_ids"],
                },
                "completion": {
                    "structural_validation_passed": True,
                    "editorial_review_complete": True,
                    "source_first_omission_review_complete": True,
                    "candidate_blindness_preserved": True,
                    "no_unreviewed_required_items": True,
                    "public_claims_allowed": True,
                },
                "changes": {
                    "merges": [],
                    "splits": [],
                    "priority_changes": [],
                    "relationship_changes": [],
                    "reader_task_changes": [],
                    "subjects_added": [],
                    "subjects_removed": [],
                    "terminology_changes": [],
                },
                "recommendation": "retain_draft",
            }
            write_json(review, review_data)
            review_payload = run_cli(
                "benchmark_review_cli.py",
                "validate-review",
                "--draft",
                draft,
                "--inventory",
                inventory,
                "--review",
                review,
            )
            self.assertEqual("retain_draft", review_payload["recommendation"])

            final_data = copy.deepcopy(draft_data)
            final_data["schema_version"] = "source-subject-benchmark-v2"
            final_data.pop("synthesis", None)
            final_data["freeze"] = {
                "frozen_at": STAMP,
                "synthesis_pass_complete": True,
                "page_coverage_complete": True,
            }
            final_data["benchmark_sha256"] = canonical_hash(final_data, "benchmark_sha256")
            write_json(final, final_data)
            final_payload = run_cli(
                "benchmark_review_cli.py",
                "validate-final",
                "--draft",
                draft,
                "--inventory",
                inventory,
                "--review",
                review,
                "--final",
                final,
            )
            self.assertEqual(final_data["benchmark_sha256"], final_payload["benchmark_sha256"])
            self.assertEqual(1, final_payload["version"])


if __name__ == "__main__":
    unittest.main()
