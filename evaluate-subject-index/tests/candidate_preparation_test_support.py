#!/usr/bin/env python3
"""Reusable, wholly synthetic candidate-preparation test data."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
CLI = SCRIPTS / "candidate_preparation_cli.py"
sys.path.insert(0, str(SCRIPTS))

from candidate_preparation_cli import canonical_hash  # noqa: E402
from state_cli import STAGES, validate_state  # noqa: E402


STAMP = "2020-01-01T12:00:00Z"
BEFORE_PREFLIGHT_STAMP = "2020-01-01T12:00:30Z"
PREFLIGHT_STAMP = "2020-01-01T12:01:00Z"
MERGE_STAMP = "2020-01-01T12:02:00Z"
SOURCE_SHA = "1" * 64
BASE_COMMIT = "b" * 40
HEAD_COMMIT = "c" * 40
MERGED_COMMIT = "d" * 40
BENCHMARK_COMMIT = "e" * 40
PUBLIC_PATHS = (
    "candidate/candidate-ref.json",
    "candidate/layout-profile.json",
    "validation/candidate-preparation-report.json",
)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob_sha(path: Path) -> str:
    payload = path.read_bytes()
    framed = f"blob {len(payload)}\0".encode("ascii") + payload
    return hashlib.sha1(framed).hexdigest()


def run_cli(*arguments: str, ok: bool = True) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    completed = subprocess.run(
        [sys.executable, str(CLI), *map(str, arguments)],
        cwd=SKILL_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - diagnostic path
        raise AssertionError(
            f"candidate_preparation_cli emitted non-JSON output\nstdout={completed.stdout}\nstderr={completed.stderr}"
        ) from exc
    if ok and (completed.returncode != 0 or payload.get("ok") is not True):
        raise AssertionError(
            f"candidate_preparation_cli failed\nargs={arguments}\nstdout={completed.stdout}\nstderr={completed.stderr}"
        )
    if not ok and completed.returncode == 0:
        raise AssertionError(f"candidate_preparation_cli unexpectedly succeeded: {arguments}")
    return completed, payload


def synthetic_geometry() -> dict[str, Any]:
    """A two-page, two-column fictional index with hierarchy and mixed syntax."""
    return {
        "file_name": "clockwork-orchard-index.pdf",
        "metadata": {
            "producer": "ReportLab PDF Library - synthetic candidate-preparation fixture",
            "title": "Clockwork Orchard Synthetic Index",
        },
        "pages": [
            {
                "page_number": 1,
                "width": 600,
                "height": 800,
                "lines": [
                    {"bbox": [220, 20, 380, 34], "text": "Synthetic Clockwork Index"},
                    {"bbox": [50, 100, 250, 112], "text": "Clockwork Orchard"},
                    {"bbox": [68, 120, 280, 132], "text": "Aërial Kites, iv–A-1"},
                    {
                        "bbox": [86, 140, 296, 152],
                        "text": "brass rigging, 120–23; see also Zephyr Engines; see Flying Looms",
                    },
                    {"bbox": [320, 100, 530, 112], "text": "Zephyr Engines, A-1"},
                    {"bbox": [320, 120, 530, 132], "text": "Flying Looms, Plate 2"},
                    {"bbox": [320, 140, 530, 152], "text": "Broken Compass, 999"},
                    {"bbox": [295, 780, 305, 792], "text": "1"},
                ],
            },
            {
                "page_number": 2,
                "width": 600,
                "height": 800,
                "lines": [
                    {"bbox": [220, 20, 380, 34], "text": "Synthetic Clockwork Index"},
                    {"bbox": [50, 100, 260, 112], "text": "Harmonic Gears, 121"},
                    {"bbox": [320, 100, 530, 112], "text": "Wind-up Beacons, 122"},
                    {"bbox": [295, 780, 305, 792], "text": "2"},
                ],
            },
        ],
    }


class SyntheticStudy:
    """Materialize a deterministic source-identity package and candidate worker."""

    candidate_id = "clockwork-orchard"
    evaluation_id = "synthetic-clockwork-evaluation"
    candidate_project = "example/clockwork-candidate"
    benchmark_project = "example/clockwork-benchmark"

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.source_dir = self.root / "source"
        self.preparation_dir = self.root / "worker-private"
        self.public_dir = self.root / "worker-public"
        self.candidate_file = self.root / "restricted" / "clockwork-orchard-index.pdf"
        self.geometry_path = self.root / "synthetic-geometry.json"
        self.layout_path = self.root / "candidate-layout-extraction.json"
        self.state_path = self.root / "evaluation-state.json"
        self.manifest_path = self.root / "artifact-manifest.json"
        self.page_map_path = self.source_dir / "page-map.json"
        self.chunk_manifest_path = self.source_dir / "chunk-manifest.json"
        self.policy_path = self.source_dir / "evaluation-policy.json"
        self.repo_state_path = self.root / "repository-state.json"
        self.recovery_zip = self.root / "exports" / "clockwork-orchard-preparation-portable.zip"
        self.receipt_path = self.root / "worker-receipt.pending.json"
        self.bound_receipt_path = self.root / "worker-receipt.bound.json"
        self.publication_evidence_path = self.root / "github-publication-evidence.json"
        self.merge_evidence_path = self.root / "github-merge-evidence.json"
        self.benchmark_path = self.source_dir / "source-benchmark.v1.json"
        self.benchmark_proof_path = self.root / "github-benchmark-proof.json"
        self.checkpoint_path = self.root / "exports" / "candidate-integration-checkpoint.zip"
        self._make_inputs()

    @property
    def candidate_sha256(self) -> str:
        return sha256_file(self.candidate_file)

    @property
    def paths(self) -> dict[str, Path]:
        slug = self.candidate_id
        return {
            "candidate_ref": self.preparation_dir / "candidates" / slug / "candidate-ref.json",
            "layout_profile": self.preparation_dir / "candidates" / slug / "layout-profile.json",
            "layout_extraction": self.preparation_dir / "candidates" / slug / "candidate-layout-extraction.v1.json",
            "candidate_index": self.preparation_dir / "candidates" / slug / "candidate-index.draft.v2.json",
            "item_inventory": self.preparation_dir / "candidates" / slug / "item-inventory.draft.v2.json",
            "normalization_exceptions": self.preparation_dir / "candidates" / slug / "normalization-exceptions.v1.json",
            "normalization_report": self.preparation_dir / "validation" / f"candidate-normalization-report.{slug}.v1.json",
            "normalization_qa": self.preparation_dir / "validation" / f"candidate-normalization-qa.{slug}.v1.template.json",
        }

    def _make_inputs(self) -> None:
        self.candidate_file.parent.mkdir(parents=True, exist_ok=True)
        self.candidate_file.write_bytes(
            b"%PDF-1.7\nSynthetic fixture only: Clockwork Orchard and Aerial Kites.\n%%EOF\n"
        )
        write_json(self.geometry_path, synthetic_geometry())
        page_map = {
            "schema_version": "page-map-v1",
            "source_sha256": SOURCE_SHA,
            "document_page_count": 8,
            "document_page_basis": "one_based_inclusive",
            "pages": [
                self._page(1, "iv", "irregular"),
                self._page(2, "v", "irregular"),
                self._page(3, "A-1", "irregular"),
                self._page(4, "120", "main"),
                self._page(5, "121", "main"),
                self._page(6, "122", "main"),
                self._page(7, "123", "main"),
                self._page(8, "Plate 2", "plates"),
            ],
            "validation": {"all_document_pages_covered": True, "unique_indexable_locator_keys": True},
            "page_map_sha256": None,
        }
        page_map["page_map_sha256"] = canonical_hash(page_map, "page_map_sha256")
        write_json(self.page_map_path, page_map)

        chunks = {
            "schema_version": "chunk-manifest-v1",
            "document_page_basis": "one_based_inclusive",
            "page_map_sha256": page_map["page_map_sha256"],
            "user_approved": True,
            "require_full_scope_coverage": True,
            "chunks": [
                {
                    "chunk_id": "CHUNK-001",
                    "title": "Synthetic source",
                    "source_units": ["Clockwork Orchard"],
                    "owned_document_page_ranges": [[1, 8]],
                    "context_document_page_ranges": [],
                    "packet_order": 1,
                }
            ],
            "validation": {
                "owned_pages_unique": True,
                "scope_coverage_complete": True,
                "owned_document_page_count": 8,
                "in_scope_document_page_count": 8,
            },
            "chunk_manifest_sha256": None,
        }
        chunks["chunk_manifest_sha256"] = canonical_hash(chunks, "chunk_manifest_sha256")
        write_json(self.chunk_manifest_path, chunks)

        policy = {
            "schema_version": "subject-index-evaluation-policy-v2",
            "policy_profile": {"id": "subject-index-standard-policy-v1"},
            "source_scope": {
                "source_sha256": SOURCE_SHA,
                "page_map_sha256": page_map["page_map_sha256"],
                "chunk_manifest_sha256": chunks["chunk_manifest_sha256"],
            },
            "audit_design": {"mode": "full"},
            "rubric": {"version": "subject-index-rubric-v4"},
            "policy_sha256": None,
        }
        policy["policy_sha256"] = canonical_hash(policy, "policy_sha256")
        write_json(self.policy_path, policy)

        state, manifest = self._base_state_and_manifest()
        write_json(self.state_path, state)
        write_json(self.manifest_path, manifest)
        write_json(
            self.repo_state_path,
            {
                "is_empty": False,
                "default_branch": "main",
                "base_commit": BASE_COMMIT,
                "branches": ["main"],
                "bootstrap_files": [],
            },
        )

    @staticmethod
    def _page(document_page: int, label: str, mapping_id: str) -> dict[str, Any]:
        return {
            "document_page": document_page,
            "source_page_label": label,
            "normalized_locator_key": label.casefold(),
            "label_style": "literal",
            "mapping_id": mapping_id,
            "in_evaluation_scope": True,
            "accepts_index_locators": True,
        }

    def _base_state_and_manifest(self) -> tuple[dict[str, Any], dict[str, Any]]:
        completed = {"initialize", "page_mapping", "chunk_definition", "define_policy"}
        stages = {
            name: {
                "status": "completed" if name in completed else "not_started",
                "updated_at": STAMP if name in completed else None,
                "notes": [],
            }
            for name in STAGES
        }
        manifest_records: list[dict[str, Any]] = []
        state_records: list[dict[str, Any]] = []
        for stage, artifact_type, path in (
            ("page_mapping", "page-map", self.page_map_path),
            ("chunk_definition", "chunk-manifest", self.chunk_manifest_path),
            ("define_policy", "evaluation_policy", self.policy_path),
        ):
            manifest_record, state_record = self._artifact_records(stage, artifact_type, path)
            manifest_records.append(manifest_record)
            state_records.append(state_record)
        state = {
            "schema_version": "subject-index-evaluation-state-v4",
            "evaluation_id": self.evaluation_id,
            "artifact_manifest_path": "artifact-manifest.json",
            "created_at": STAMP,
            "updated_at": STAMP,
            "source": {
                "title": "The Clockwork Orchard",
                "edition": "Synthetic 2026 edition",
                "filename": "synthetic-source.pdf",
                "sha256": SOURCE_SHA,
                "document_page_span": [1, 8],
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
                    "rationale": "Synthetic test fixture.",
                },
                "output_format": "json",
                "storage_mode": "local",
                "policy_profile": "subject-index-standard-policy-v1",
                "rubric_version": "subject-index-rubric-v4",
            },
            "stages": stages,
            "artifacts": state_records,
            "blockers": [],
        }
        manifest = {
            "schema_version": "subject-index-artifact-manifest-v1",
            "evaluation_id": self.evaluation_id,
            "created_at": STAMP,
            "updated_at": STAMP,
            "artifacts": manifest_records,
        }
        return state, manifest

    def _artifact_records(
        self, stage: str, artifact_type: str, path: Path
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        relative = path.resolve().relative_to(self.root).as_posix()
        digest = sha256_file(path)
        artifact_id = "ART-" + hashlib.sha256(f"{relative}\0{digest}".encode()).hexdigest()[:12].upper()
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

    def extract_and_normalize(self) -> None:
        run_cli(
            "extract",
            "--candidate-id", self.candidate_id,
            "--candidate-file", str(self.candidate_file),
            "--source-sha256", SOURCE_SHA,
            "--adapter", "auto",
            "--geometry-input", str(self.geometry_path),
            "--output", str(self.layout_path),
        )
        run_cli(
            "normalize",
            "--candidate-id", self.candidate_id,
            "--candidate-file", str(self.candidate_file),
            "--state", str(self.state_path),
            "--page-map", str(self.page_map_path),
            "--chunk-manifest", str(self.chunk_manifest_path),
            "--policy", str(self.policy_path),
            "--layout", str(self.layout_path),
            "--output-dir", str(self.preparation_dir),
        )

    def complete_qa_and_provenance(self) -> None:
        candidate_ref = read_json(self.paths["candidate_ref"])
        for field in (
            "internal_pdf_completeness",
            "structural_continuity",
            "source_edition_compatibility",
            "locator_page_map_compatibility",
        ):
            candidate_ref["provenance"][field] = {
                "status": "verified",
                "rationale": f"Synthetic full review verified {field.replace('_', ' ')}.",
            }
        candidate_ref["provenance"]["authoritative_copy_fidelity"] = {
            "status": "not_independently_verified",
            "rationale": "Internal completeness does not establish authoritative-copy fidelity.",
        }
        write_json(self.paths["candidate_ref"], candidate_ref)

        qa = read_json(self.paths["normalization_qa"])
        qa["reviewed"] = copy.deepcopy(qa["expected"])
        for page in qa["page_reviews"]:
            page["continuation_handling_reviewed"] = True
            page["reproduces_candidate_not_editorial_improvement"] = True
        qa["exception_dispositions"] = [
            {
                "exception_id": exception_id,
                "disposition": "confirmed_unresolved",
                "rationale": "Synthetic QA retained the delivered unresolved form.",
            }
            for exception_id in qa["expected"]["exception_ids"]
        ]
        qa["completion"] = {
            "all_denominators_complete": True,
            "all_exceptions_dispositioned": True,
            "candidate_reproduction_confirmed": True,
            "editorial_quality_judgments_performed": False,
            "complete": True,
        }
        write_json(self.paths["normalization_qa"], qa)

    def validate_private(self) -> dict[str, Any]:
        _, payload = run_cli(
            "validate-private",
            "--candidate-id", self.candidate_id,
            "--candidate-file", str(self.candidate_file),
            "--preparation-dir", str(self.preparation_dir),
            "--state", str(self.state_path),
            "--page-map", str(self.page_map_path),
            "--chunk-manifest", str(self.chunk_manifest_path),
            "--policy", str(self.policy_path),
        )
        return payload

    def build_worker(self) -> dict[str, Any]:
        _, payload = run_cli(
            "build-worker",
            "--candidate-id", self.candidate_id,
            "--candidate-file", str(self.candidate_file),
            "--preparation-dir", str(self.preparation_dir),
            "--state", str(self.state_path),
            "--page-map", str(self.page_map_path),
            "--chunk-manifest", str(self.chunk_manifest_path),
            "--policy", str(self.policy_path),
            "--project", self.candidate_project,
            "--benchmark-project", self.benchmark_project,
            "--benchmark-ref", BASE_COMMIT,
            "--repository-state", str(self.repo_state_path),
            "--checkpoint-ref", "source-identities-frozen-v1",
            "--public-output", str(self.public_dir),
            "--recovery-zip", str(self.recovery_zip),
            "--receipt-output", str(self.receipt_path),
        )
        return payload

    def make_publication_evidence(self, pull_request: int = 7, observed_at: str = STAMP) -> dict[str, Any]:
        evidence = {
            "schema_version": "candidate-preparation-publication-evidence-v1",
            "evidence_source": "github_api",
            "candidate_project": self.candidate_project,
            "pull_request": pull_request,
            "pull_request_url": f"https://github.com/{self.candidate_project}/pull/{pull_request}",
            "state": "open",
            "merged": False,
            "base_branch": "main",
            "base_commit": BASE_COMMIT,
            "head_branch": f"candidate-preparation/{self.candidate_id}",
            "head_commit": HEAD_COMMIT,
            "commit_count": 1,
            "bootstrap": None,
            "changed_files": [
                {
                    "path": path,
                    "blob_sha": git_blob_sha(self.public_dir / path),
                    "file_sha256": sha256_file(self.public_dir / path),
                }
                for path in PUBLIC_PATHS
            ],
            "observed_at": observed_at,
        }
        write_json(self.publication_evidence_path, evidence)
        return evidence

    def bind_publication(self, pull_request: int = 7) -> dict[str, Any]:
        self.make_publication_evidence(pull_request)
        arguments: list[str] = [
            "bind-publication",
            "--receipt", str(self.receipt_path),
            "--public-dir", str(self.public_dir),
            "--publication-evidence", str(self.publication_evidence_path),
            "--output", str(self.bound_receipt_path),
        ]
        _, payload = run_cli(*arguments)
        return payload

    def make_final_benchmark(self, **overrides: Any) -> dict[str, Any]:
        page_map = read_json(self.page_map_path)
        chunks = read_json(self.chunk_manifest_path)
        policy = read_json(self.policy_path)
        benchmark = {
            "schema_version": "source-subject-benchmark-v2",
            "benchmark_id": "BENCH-SYNTHETIC-CLOCKWORK",
            "version": 1,
            "source_sha256": SOURCE_SHA,
            "page_map_sha256": page_map["page_map_sha256"],
            "chunk_manifest_sha256": chunks["chunk_manifest_sha256"],
            "policy_sha256": policy["policy_sha256"],
            "candidate_blindness": "preserved",
            "subjects": [],
            "relationships": [],
            "reader_tasks": [],
            "freeze": {
                "frozen_at": STAMP,
                "synthesis_pass_complete": True,
                "page_coverage_complete": True,
            },
            "benchmark_sha256": None,
        }
        benchmark.update(overrides)
        benchmark["benchmark_sha256"] = canonical_hash(benchmark, "benchmark_sha256")
        write_json(self.benchmark_path, benchmark)
        write_json(
            self.benchmark_proof_path,
            {
                "schema_version": "candidate-benchmark-git-proof-v1",
                "evidence_source": "github_api",
                "benchmark_project": self.benchmark_project,
                "final_commit": BENCHMARK_COMMIT,
                "benchmark_path": "source/source-benchmark.v1.json",
                "blob_sha": git_blob_sha(self.benchmark_path),
                "file_sha256": sha256_file(self.benchmark_path),
                "observed_at": STAMP,
            },
        )
        return benchmark

    def make_merge_evidence(self, pull_request: int = 7) -> dict[str, Any]:
        evidence = {
            "schema_version": "candidate-preparation-merge-evidence-v1",
            "evidence_source": "github_api",
            "candidate_project": self.candidate_project,
            "pull_request": pull_request,
            "pull_request_url": f"https://github.com/{self.candidate_project}/pull/{pull_request}",
            "state": "closed",
            "merged": True,
            "base_branch": "main",
            "base_commit": BASE_COMMIT,
            "head_branch": f"candidate-preparation/{self.candidate_id}",
            "head_commit": HEAD_COMMIT,
            "merge_commit": MERGED_COMMIT,
            "commit_count": 1,
            "changed_files": [
                {
                    "path": path,
                    "blob_sha": git_blob_sha(self.public_dir / path),
                    "file_sha256": sha256_file(self.public_dir / path),
                }
                for path in PUBLIC_PATHS
            ],
            "observed_at": MERGE_STAMP,
        }
        write_json(self.merge_evidence_path, evidence)
        return evidence

    def freeze_benchmark_state(self) -> None:
        if not self.benchmark_path.exists():
            self.make_final_benchmark()
        state = read_json(self.state_path)
        manifest = read_json(self.manifest_path)
        stage_paths = {
            "source_chunk_preparation": self.source_dir / "source-chunk-inventory.json",
            "source_subject_discovery": self.source_dir / "source-subject-chunk.CHUNK-001.json",
            "benchmark_synthesis": self.source_dir / "source-benchmark.draft.v1.json",
            "benchmark_review": self.root / "validation" / "source-benchmark-review.v1.json",
            "benchmark_freeze": self.benchmark_path,
        }
        for stage, path in stage_paths.items():
            if not path.exists():
                write_json(path, {"schema_version": f"synthetic-{stage}-v1", "complete": True})
            manifest_record, state_record = self._artifact_records(stage, stage.replace("_", "-"), path)
            manifest["artifacts"] = [item for item in manifest["artifacts"] if item["path"] != manifest_record["path"]]
            state["artifacts"] = [item for item in state["artifacts"] if item["path"] != state_record["path"]]
            manifest["artifacts"].append(manifest_record)
            state["artifacts"].append(state_record)
            state["stages"][stage] = {"status": "completed", "updated_at": STAMP, "notes": []}
        manifest["artifacts"].sort(key=lambda item: item["path"])
        state["artifacts"].sort(key=lambda item: item["path"])
        write_json(self.manifest_path, manifest)
        write_json(self.state_path, state)
        errors, _ = validate_state(state, state_path=self.state_path, check_files=True)
        if errors:
            raise AssertionError(f"Synthetic frozen state is invalid: {errors}")

    def preflight_arguments(self, pull_request: int = 7) -> list[str]:
        self.make_publication_evidence(pull_request, observed_at=PREFLIGHT_STAMP)
        return [
            "--receipt", str(self.bound_receipt_path),
            "--recovery-zip", str(self.recovery_zip),
            "--public-dir", str(self.public_dir),
            "--state", str(self.state_path),
            "--page-map", str(self.page_map_path),
            "--chunk-manifest", str(self.chunk_manifest_path),
            "--policy", str(self.policy_path),
            "--benchmark-file", str(self.benchmark_path),
            "--publication-evidence", str(self.publication_evidence_path),
            "--benchmark-proof", str(self.benchmark_proof_path),
            "--benchmark-project", self.benchmark_project,
            "--benchmark-ref", BENCHMARK_COMMIT,
            "--pull-request", str(pull_request),
        ]

    def integration_arguments(
        self,
        pull_request: int = 7,
        *,
        merge_evidence: Path | None = None,
        checkpoint_output: Path | None = None,
        force_checkpoint: bool = False,
    ) -> list[str]:
        if merge_evidence is None:
            self.make_merge_evidence(pull_request)
            merge_evidence = self.merge_evidence_path
        arguments = [
            "integrate",
            *self.preflight_arguments(pull_request),
            "--merge-evidence", str(merge_evidence),
            "--checkpoint-output", str(checkpoint_output or self.checkpoint_path),
        ]
        if force_checkpoint:
            arguments.append("--force-checkpoint")
        return arguments

    def integrate(self, pull_request: int = 7) -> dict[str, Any]:
        arguments = self.integration_arguments(pull_request)
        _, payload = run_cli(*arguments)
        return payload
