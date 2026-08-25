#!/usr/bin/env python3
"""Build and integrate privacy-safe parallel candidate-audit workers.

This helper is deliberately separate from candidate_preparation_cli.py.  It uses
the same canonical locator-audit-v1 and missing-access-audit-v1 judgment
artifacts, but applies a stricter parallel-worker profile around them.

GitHub evidence documents accepted here are deterministic snapshots.  The
``evidence_source`` value is a format discriminator, not authentication.  The
coordinating orchestrator must create those snapshots directly from GitHub API
or connector output and must never accept one supplied by a worker or caller.
"""

from __future__ import annotations

import argparse
import json
import re
import stat
import tempfile
import zipfile
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from candidate_preparation_cli import (
    MAX_RECOVERY_ARCHIVE_BYTES,
    MAX_RECOVERY_COMPRESSION_RATIO,
    MAX_RECOVERY_MEMBER_BYTES,
    MAX_RECOVERY_TOTAL_BYTES,
    PreparationError,
    SECRET_PATTERNS,
    artifact_id,
    canonical_hash,
    evaluation_integration_lock,
    git_blob_sha_bytes,
    load_json,
    load_json_snapshot,
    path_is_within,
    replace_bytes_atomic,
    require,
    require_commit,
    require_github_project,
    require_no_symlink_components,
    require_safe_output_path,
    require_sha256,
    require_timestamp,
    safe_relative_path,
    sha256_bytes,
    sha256_file,
    validate_self_hash,
    write_zip_atomic,
)
from state_cli import STAGES, next_stage, validate_state


STATE_VERSION = "subject-index-evaluation-state-v4"
MANIFEST_VERSION = "subject-index-artifact-manifest-v1"
LOCATOR_AUDIT_VERSION = "locator-audit-v1"
MISSING_AUDIT_VERSION = "missing-access-audit-v1"
LOCATOR_RECEIPT_VERSION = "parallel-locator-audit-worker-receipt-v1"
MISSING_RECEIPT_VERSION = "parallel-missing-access-worker-receipt-v2"
LOCATOR_REPORT_VERSION = "locator-audit-worker-report-v1"
MISSING_REPORT_VERSION = "missing-access-worker-report-v2"
OPEN_EVIDENCE_VERSION = "candidate-audit-open-pr-evidence-v1"
MERGE_EVIDENCE_VERSION = "candidate-audit-merge-evidence-v1"
RECOVERY_VERSION = "candidate-audit-worker-recovery-v1"
BINDING_VERSION = "candidate-audit-integration-binding-v1"
REPOSITORY_STATE_VERSION = "candidate-audit-repository-state-v1"
LOCATOR_INTEGRATION_VERSION = "locator-audit-batch-integration-v1"
MISSING_INTEGRATION_VERSION = "missing-access-batch-integration-v1"
AGGREGATE_ONLY = "aggregate_only"
PUBLIC_EVALUATION_ARTIFACTS = "public_evaluation_artifacts"
PUBLICATION_MIGRATION_VERSION = "candidate-audit-publication-migration-v1"
PUBLICATION_PROFILES = {AGGREGATE_ONLY, PUBLIC_EVALUATION_ARTIFACTS}

AUDIT_KINDS = {"locator", "missing_access"}
LOCATOR_STATUSES = {"supported", "partially_supported", "unsupported", "uninspectable"}
LOCATOR_SCOPE_STATUSES = {"indexable", "excluded", "unavailable", "ambiguous"}
TREATMENT_CLASSES = {
    "substantive", "passing_mention", "attribution_only", "citation_only",
    "incidental_example", "absent", "unavailable", "mixed",
}
LOCATOR_ERROR_CODES = {"SCP", "SEL", "CON", "STA", "LOC_POS", "CMP", "HED", "SUB"}
SEVERITIES = {"none", "cosmetic", "minor", "major", "critical"}
CONFIDENCES = {"high", "medium", "low"}
COVERAGE_STATUSES = {"complete", "partial", "missing", "uninspectable"}
STANCE_STATUSES = {"yes", "partly", "no", "not_applicable", "uninspectable"}
TASK_STATUSES = {"succeeds", "partially_succeeds", "fails", "uninspectable"}
TREATMENT_RECALL_STATUSES = {"found", "missed", "uninspectable"}
FIRST_LOOKUP_STATUSES = {"yes", "partly", "no", "uninspectable"}
ACCESS_MODES = {"direct", "cross_reference", "mixed", "none", "uninspectable"}
UNCERTAINTY_STATUSES = {"none", "uncertain", "uninspectable"}
MISSING_ERROR_CODES = {"SCP", "COV", "SEL", "CON", "STA", "LOC_POS", "LOC_NEG", "CMP", "HED", "SUB", "XRF", "DEN", "MEC"}
PRIORITIES = {"essential", "major", "optional"}
PRIORITY_RANK = {"essential": 0, "major": 1, "optional": 2, "exclude_by_default": 3}
LOCATOR_CLASS_RANK = {"principal": 0, "synthesis_or_conclusion": 1, "supporting": 2, "incidental": 3}
MISSING_ACCESS_EVIDENCE_MODE = "frozen_benchmark_and_canonical_locator_audits"
MISSING_ACCESS_SOURCE_ADJUDICATION_MODE = "exception_only"
MISSING_ACCESS_TREATMENT_IDENTITY_RULE = "unique_subject_document_page_locator_class"

RECEIPT_REQUIRED = {
    "schema_version", "receipt_id", "receipt_sha256", "created_at", "status",
    "audit_kind", "evaluation_id", "candidate_id", "chunk", "repositories",
    "identities", "source_reconnection", "private_artifact", "private_recovery",
    "public_projection", "validation", "publication", "limitations",
}
LOCATOR_REPORT_REQUIRED = {
    "schema_version", "report_sha256", "audit_kind", "evaluation_id", "candidate_id",
    "chunk_id", "source_unit_label", "immutable_base_commit", "identities",
    "owned_document_page_ranges", "denominators", "judgment_counts", "severity_counts",
    "error_code_counts", "completion", "private_artifact_sha256", "reconnection_status",
    "limitations", "public_safety",
}
MISSING_REPORT_REQUIRED = {
    "schema_version", "report_sha256", "audit_kind", "evaluation_id", "candidate_id",
    "chunk_id", "source_unit_label", "immutable_base_commit", "identities",
    "owned_document_page_ranges", "subject_denominators", "reader_task_denominators",
    "treatment_denominators", "concept_coverage_counts", "locator_recall", "treatment_recall",
    "access_route_counts", "reader_task_result_counts", "severity_counts", "error_code_counts",
    "dependency_defect_count", "completion",
    "private_artifact_sha256", "reconnection_status", "limitations", "public_safety",
}
PUBLIC_FORBIDDEN_KEYS = {
    "heading", "headings", "heading_path", "complete_heading_path", "path_id", "record_id",
    "locator", "locators", "locator_id", "locator_ids", "displayed_locator", "source_page_label",
    "cross_reference", "cross_references", "target", "target_display", "subject_id", "subject_ids",
    "subject_label", "question", "evidence", "evidence_ids", "evidence_summary", "raw", "raw_text",
    "text", "coordinates", "bbox", "pages", "document_page", "document_pages", "library_id",
    "library_file_id", "absolute_path", "local_path", "receipt_path", "recovery_path",
}
PUBLIC_AUDIT_FORBIDDEN_KEYS = {
    "raw", "raw_text", "verbatim", "quote", "quotation", "excerpt", "coordinates", "bbox",
    "library_id", "library_file_id", "absolute_path", "local_path", "receipt_path", "recovery_path",
    "source_pdf", "source_chunk", "candidate_pdf", "credential", "credentials", "secret", "secrets",
}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def emit(payload: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(exit_code)


def exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    require(
        isinstance(value, dict) and set(value) == expected,
        "schema_mismatch",
        f"{label} has missing or unexpected properties.",
        {"expected": sorted(expected), "actual": sorted(value) if isinstance(value, dict) else None},
    )
    return value


def require_nonempty_string(value: Any, field: str, maximum: int = 512) -> str:
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= maximum, "invalid_string", f"{field} must be a bounded nonempty string.")
    return value


def require_nonnegative_integer(value: Any, field: str) -> int:
    require(isinstance(value, int) and not isinstance(value, bool) and value >= 0, "invalid_count", f"{field} must be a nonnegative integer.")
    return value


def duplicate_values(values: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    duplicates: list[Any] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    replace_bytes_atomic(path, json_bytes(value))


def stable_identifier(prefix: str, identity: Any) -> str:
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{prefix}-{sha256_bytes(encoded)[:12].upper()}"


def audit_stage(audit_kind: str) -> str:
    require(audit_kind in AUDIT_KINDS, "invalid_audit_kind", f"Unknown audit kind: {audit_kind}")
    return "locator_audit" if audit_kind == "locator" else "missing_access_audit"


def serialized_audit_kind(audit_kind: str) -> str:
    require(audit_kind in AUDIT_KINDS, "invalid_audit_kind", f"Unknown audit kind: {audit_kind}")
    return "locator_audit" if audit_kind == "locator" else "missing_access"


def receipt_version(audit_kind: str) -> str:
    return LOCATOR_RECEIPT_VERSION if audit_kind == "locator" else MISSING_RECEIPT_VERSION


def report_version(audit_kind: str) -> str:
    return LOCATOR_REPORT_VERSION if audit_kind == "locator" else MISSING_REPORT_VERSION


def integration_version(audit_kind: str) -> str:
    return LOCATOR_INTEGRATION_VERSION if audit_kind == "locator" else MISSING_INTEGRATION_VERSION


def branch_for(audit_kind: str, chunk_id: str) -> str:
    prefix = "locator-audit" if audit_kind == "locator" else "missing-access-audit"
    return f"{prefix}/{chunk_id.lower()}"


def publication_profile_for(state: dict[str, Any]) -> str:
    configuration = state.get("configuration", {})
    profile = configuration.get("publication_profile", AGGREGATE_ONLY) if isinstance(configuration, dict) else AGGREGATE_ONLY
    require(profile in PUBLICATION_PROFILES, "publication_profile", "Publication profile must be aggregate_only or public_evaluation_artifacts.")
    return profile


def public_path_for(audit_kind: str, chunk_id: str, publication_profile: str = AGGREGATE_ONLY) -> str:
    require(publication_profile in PUBLICATION_PROFILES, "publication_profile", "Unknown publication profile.")
    if publication_profile == PUBLIC_EVALUATION_ARTIFACTS:
        directory = "locator-audits" if audit_kind == "locator" else "missing-access-audits"
        stem = "locator-audit" if audit_kind == "locator" else "missing-access-audit"
        return f"candidate/{directory}/{stem}.{chunk_id}.v1.json"
    stem = "locator-audit-worker" if audit_kind == "locator" else "missing-access-audit-worker"
    return f"validation/{stem}.{chunk_id}.json"


def publication_profile_from_path(audit_kind: str, chunk_id: str, path: Any) -> str:
    matches = [profile for profile in sorted(PUBLICATION_PROFILES) if path == public_path_for(audit_kind, chunk_id, profile)]
    require(len(matches) == 1, "receipt_public_path", "Worker receipt public path is not allowlisted by a publication profile.")
    return matches[0]


def validate_chunk_id(value: Any) -> str:
    require(isinstance(value, str) and bool(re.fullmatch(r"CHUNK-[A-Za-z0-9._-]+", value)), "invalid_chunk_id", "chunk-id must be a CHUNK-* identifier.")
    return value


def flatten_ranges(value: Any, field: str) -> list[int]:
    require(isinstance(value, list), "invalid_ranges", f"{field} must be an array of inclusive page pairs.")
    pages: list[int] = []
    for index, pair in enumerate(value):
        require(
            isinstance(pair, list) and len(pair) == 2
            and all(isinstance(item, int) and not isinstance(item, bool) for item in pair)
            and 1 <= pair[0] <= pair[1],
            "invalid_ranges",
            f"{field}[{index}] must be a one-based ascending pair.",
        )
        pages.extend(range(pair[0], pair[1] + 1))
    require(not duplicate_values(pages), "overlapping_ranges", f"{field} contains overlapping ranges.")
    return pages


def chunk_records(chunk_manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    chunks = chunk_manifest.get("chunks")
    require(isinstance(chunks, list) and bool(chunks), "invalid_chunk_manifest", "Chunk manifest must contain a nonempty chunks array.")
    result: dict[str, dict[str, Any]] = {}
    orders: set[int] = set()
    for record in chunks:
        require(isinstance(record, dict), "invalid_chunk_manifest", "Every chunk must be an object.")
        chunk_id = validate_chunk_id(record.get("chunk_id"))
        require(chunk_id not in result, "duplicate_chunk_id", f"Duplicate chunk ID: {chunk_id}")
        order = record.get("packet_order")
        require(isinstance(order, int) and not isinstance(order, bool) and order > 0 and order not in orders, "invalid_packet_order", f"Chunk {chunk_id} has an invalid packet order.")
        flatten_ranges(record.get("owned_document_page_ranges"), f"{chunk_id}.owned_document_page_ranges")
        flatten_ranges(record.get("context_document_page_ranges", []), f"{chunk_id}.context_document_page_ranges")
        orders.add(order)
        result[chunk_id] = record
    return result


def page_owner_map(chunk_manifest: dict[str, Any]) -> dict[int, str]:
    owners: dict[int, str] = {}
    for chunk_id, record in chunk_records(chunk_manifest).items():
        for page in flatten_ranges(record["owned_document_page_ranges"], f"{chunk_id}.owned_document_page_ranges"):
            require(page not in owners, "overlapping_chunk_ownership", f"Document page {page} is owned by more than one chunk.")
            owners[page] = chunk_id
    return owners


def source_unit_label(record: dict[str, Any]) -> str:
    if isinstance(record.get("title"), str) and record["title"].strip():
        return record["title"].strip()
    units = record.get("source_units")
    if isinstance(units, list) and units and all(isinstance(item, str) and item.strip() for item in units):
        return " / ".join(item.strip() for item in units)
    return str(record.get("chunk_id", ""))


def resolve_manifest_path(root: Path, value: str) -> Path:
    return root.joinpath(*PurePosixPath(safe_relative_path(value)).parts)


def load_canonical_run(state_path: Path) -> dict[str, Any]:
    state_path = state_path.resolve()
    state, state_bytes, state_file_sha256 = load_json_snapshot(state_path, "Canonical evaluation state")
    require(state.get("schema_version") == STATE_VERSION, "unsupported_state", f"Expected {STATE_VERSION}.")
    root = state_path.parent
    manifest_path = resolve_manifest_path(root, str(state.get("artifact_manifest_path", "artifact-manifest.json")))
    manifest, manifest_bytes, manifest_file_sha256 = load_json_snapshot(manifest_path, "Canonical artifact manifest")
    require(manifest.get("schema_version") == MANIFEST_VERSION, "unsupported_manifest", f"Expected {MANIFEST_VERSION}.")
    require(manifest.get("evaluation_id") == state.get("evaluation_id"), "evaluation_identity_mismatch", "State and manifest evaluation IDs differ.")
    errors, warnings = validate_state(state, state_path=state_path, check_files=True, manifest_document=manifest)
    require(not errors, "canonical_state_invalid", "Canonical evaluation state failed validation.", errors)
    return {
        "state_path": state_path,
        "state": state,
        "state_bytes": state_bytes,
        "state_file_sha256": state_file_sha256,
        "root": root,
        "manifest_path": manifest_path,
        "manifest": manifest,
        "manifest_bytes": manifest_bytes,
        "manifest_file_sha256": manifest_file_sha256,
        "warnings": warnings,
    }


def manifest_record_for_path(run: dict[str, Any], path: Path, required: bool = True) -> dict[str, Any] | None:
    root = run["root"]
    require(path_is_within(path, root), "canonical_artifact_outside_root", f"Canonical artifact is outside the evaluation root: {path}")
    relative = path.resolve().relative_to(root.resolve()).as_posix()
    matches = [item for item in run["manifest"].get("artifacts", []) if isinstance(item, dict) and item.get("path") == relative]
    if required:
        require(len(matches) == 1, "canonical_artifact_not_registered", f"Expected exactly one manifest record for {relative}.")
    elif len(matches) > 1:
        raise PreparationError("duplicate_manifest_path", f"Manifest contains duplicate path {relative}.")
    if not matches:
        return None
    require(matches[0].get("sha256") == sha256_file(path), "canonical_artifact_hash_mismatch", f"Manifest hash differs from canonical bytes: {relative}")
    return matches[0]


def validate_json_identity_file(path: Path, label: str, schema_version: str, own_hash_field: str | None = None) -> tuple[dict[str, Any], bytes, str]:
    document, payload, digest = load_json_snapshot(path.resolve(), label)
    require(document.get("schema_version") == schema_version, "schema_mismatch", f"{label} must use {schema_version}.")
    if own_hash_field is not None:
        validate_self_hash(document, own_hash_field, label)
    return document, payload, digest


def load_frozen_inputs(args: argparse.Namespace, audit_kind: str) -> dict[str, Any]:
    run = load_canonical_run(Path(args.state))
    state = run["state"]
    publication_profile = publication_profile_for(state)
    page_map, page_map_bytes, page_map_file_sha = validate_json_identity_file(Path(args.page_map), "Page map", "page-map-v1", "page_map_sha256")
    chunks, chunk_bytes, chunk_file_sha = validate_json_identity_file(Path(args.chunk_manifest), "Chunk manifest", "chunk-manifest-v1", "chunk_manifest_sha256")
    policy, policy_bytes, policy_file_sha = validate_json_identity_file(Path(args.policy), "Evaluation policy", "subject-index-evaluation-policy-v2", "policy_sha256")
    benchmark, benchmark_bytes, benchmark_file_sha = validate_json_identity_file(Path(args.benchmark), "Frozen benchmark", "source-subject-benchmark-v2", "benchmark_sha256")
    lock, lock_bytes, lock_file_sha = validate_json_identity_file(Path(args.benchmark_lock), "Candidate benchmark lock", "candidate-benchmark-lock-v1", "lock_sha256")
    candidate, candidate_bytes, candidate_file_sha = validate_json_identity_file(Path(args.normalized_candidate), "Normalized candidate", "candidate-index-v2")
    inventory, inventory_bytes, inventory_file_sha = validate_json_identity_file(Path(args.item_inventory), "Item inventory", "subject-index-item-inventory-v2")

    for path in (Path(args.page_map), Path(args.chunk_manifest), Path(args.policy), Path(args.benchmark), Path(args.benchmark_lock), Path(args.normalized_candidate), Path(args.item_inventory)):
        manifest_record_for_path(run, path.resolve())

    source_sha = require_sha256(state.get("source", {}).get("sha256"), "state.source.sha256")
    candidate_state = state.get("candidate")
    require(isinstance(candidate_state, dict), "candidate_not_integrated", "Canonical candidate preparation has not been integrated.")
    for state_field, supplied, label in (
        ("normalized_path", Path(args.normalized_candidate).resolve(), "normalized candidate"),
        ("item_inventory_path", Path(args.item_inventory).resolve(), "item inventory"),
        ("benchmark_lock_path", Path(args.benchmark_lock).resolve(), "candidate benchmark lock"),
    ):
        stored = candidate_state.get(state_field)
        require(isinstance(stored, str) and resolve_manifest_path(run["root"], stored).resolve() == supplied, "canonical_checkpoint_path_mismatch", f"Supplied {label} is not the exact path recorded by the integrated candidate checkpoint.")
    candidate_id = require_nonempty_string(candidate.get("candidate_id"), "candidate.candidate_id", 128)
    candidate_sha = require_sha256(candidate.get("candidate_sha256"), "candidate.candidate_sha256")
    require(candidate_state.get("candidate_id") == candidate_id and candidate_state.get("sha256") == candidate_sha, "candidate_identity_mismatch", "State and normalized candidate identities differ.")
    require(inventory.get("candidate_id") == candidate_id and inventory.get("candidate_sha256") == candidate_sha, "inventory_identity_mismatch", "Item inventory and candidate identities differ.")
    require(candidate.get("page_map_sha256") == page_map.get("page_map_sha256"), "page_map_identity_mismatch", "Normalized candidate references a different page map.")
    require(chunks.get("page_map_sha256") == page_map.get("page_map_sha256"), "chunk_identity_mismatch", "Chunk manifest references a different page map.")
    scope = policy.get("source_scope", {})
    for field, expected in (
        ("source_sha256", source_sha),
        ("page_map_sha256", page_map.get("page_map_sha256")),
        ("chunk_manifest_sha256", chunks.get("chunk_manifest_sha256")),
    ):
        require(scope.get(field) == expected, "policy_identity_mismatch", f"Policy {field} differs from canonical input.")
    for field, expected in (
        ("source_sha256", source_sha),
        ("page_map_sha256", page_map.get("page_map_sha256")),
        ("chunk_manifest_sha256", chunks.get("chunk_manifest_sha256")),
        ("policy_sha256", policy.get("policy_sha256")),
    ):
        require(benchmark.get(field) == expected, "benchmark_identity_mismatch", f"Benchmark {field} differs from canonical input.")
    require(benchmark.get("candidate_blindness") == "preserved", "benchmark_blindness", "Parallel candidate auditing requires a candidate-blind frozen benchmark.")
    require(lock.get("status") == "locked", "benchmark_lock_pending", "Candidate benchmark lock must be final.")
    require(lock.get("candidate_id") == candidate_id and lock.get("candidate_sha256") == candidate_sha, "benchmark_lock_candidate_mismatch", "Benchmark lock names a different candidate.")
    compatibility = lock.get("compatibility", {})
    for field, expected in (
        ("source_sha256", source_sha),
        ("page_map_sha256", page_map.get("page_map_sha256")),
        ("chunk_manifest_sha256", chunks.get("chunk_manifest_sha256")),
        ("policy_sha256", policy.get("policy_sha256")),
    ):
        require(compatibility.get(field) == expected, "benchmark_lock_identity_mismatch", f"Benchmark lock {field} differs from canonical input.")
    benchmark_repository = lock.get("benchmark_repository", {})
    require(benchmark_repository.get("benchmark_sha256") == benchmark.get("benchmark_sha256"), "benchmark_lock_identity_mismatch", "Benchmark lock canonical benchmark hash differs.")
    if benchmark_repository.get("benchmark_file_sha256") is not None:
        require(benchmark_repository.get("benchmark_file_sha256") == benchmark_file_sha, "benchmark_lock_identity_mismatch", "Benchmark lock benchmark file hash differs.")
    require(candidate_state.get("benchmark_lock_sha256") == lock.get("lock_sha256"), "benchmark_lock_identity_mismatch", "State records a different benchmark-lock canonical hash.")

    stages = state.get("stages", {})
    require(stages.get("candidate_normalization", {}).get("status") == "completed", "candidate_normalization_incomplete", "Candidate normalization must be complete.")
    require(stages.get("locator_chunk_preparation", {}).get("status") == "completed", "locator_packet_preparation_incomplete", "Locator-packet preparation must be complete.")
    if audit_kind == "locator":
        if not getattr(args, "allow_completed_boundary", False):
            require(stages.get("missing_access_audit", {}).get("status") == "not_started", "stage_boundary_crossed", "Locator workers cannot run after missing-access auditing has begun.")
    else:
        require(stages.get("locator_audit", {}).get("status") == "completed", "locator_audit_incomplete", "Every locator audit must be canonically integrated before missing-access work.")

    identities = {
        "source_sha256": source_sha,
        "candidate_sha256": candidate_sha,
        "benchmark_version": benchmark["version"],
        "benchmark_sha256": benchmark["benchmark_sha256"],
        "benchmark_file_sha256": benchmark_file_sha,
        "benchmark_lock_sha256": lock["lock_sha256"],
        "policy_sha256": policy["policy_sha256"],
        "policy_file_sha256": policy_file_sha,
        "page_map_sha256": page_map["page_map_sha256"],
        "page_map_file_sha256": page_map_file_sha,
        "chunk_manifest_sha256": chunks["chunk_manifest_sha256"],
        "chunk_manifest_file_sha256": chunk_file_sha,
        "normalized_candidate_file_sha256": candidate_file_sha,
        "item_inventory_file_sha256": inventory_file_sha,
    }
    return {
        **run,
        "publication_profile": publication_profile,
        "page_map": page_map,
        "page_map_bytes": page_map_bytes,
        "page_map_file_sha256": page_map_file_sha,
        "chunk_manifest": chunks,
        "chunk_manifest_bytes": chunk_bytes,
        "chunk_manifest_file_sha256": chunk_file_sha,
        "policy": policy,
        "policy_bytes": policy_bytes,
        "policy_file_sha256": policy_file_sha,
        "benchmark": benchmark,
        "benchmark_bytes": benchmark_bytes,
        "benchmark_file_sha256": benchmark_file_sha,
        "benchmark_lock": lock,
        "benchmark_lock_bytes": lock_bytes,
        "benchmark_lock_file_sha256": lock_file_sha,
        "candidate": candidate,
        "candidate_bytes": candidate_bytes,
        "candidate_file_sha256": candidate_file_sha,
        "inventory": inventory,
        "inventory_bytes": inventory_bytes,
        "inventory_file_sha256": inventory_file_sha,
        "candidate_id": candidate_id,
        "candidate_sha256": candidate_sha,
        "identities": identities,
        "chunks": chunk_records(chunks),
    }


def validate_source_reconnection(args: argparse.Namespace, frozen: dict[str, Any], chunk_id: str) -> dict[str, Any]:
    source_file = Path(args.source_file).resolve()
    source_chunk = Path(args.source_chunk).resolve()
    sidecar_path = Path(args.source_sidecar).resolve()
    require(source_file.is_file(), "source_reconnection_missing", f"Source file is unavailable: {source_file}")
    require(sha256_file(source_file) == frozen["identities"]["source_sha256"], "source_reconnection_mismatch", "Reconnected source bytes differ from canonical source SHA-256.")
    require(source_chunk.is_file() and source_chunk.stat().st_size > 0, "source_chunk_missing", "Exact source chunk is unavailable or empty.")
    sidecar, sidecar_bytes, sidecar_sha = load_json_snapshot(sidecar_path, "Source chunk page sidecar")
    require(sidecar.get("schema_version") == "source-chunk-sidecar-v1", "sidecar_schema", "Expected source-chunk-sidecar-v1.")
    require(sidecar.get("chunk_id") == chunk_id, "sidecar_chunk_mismatch", "Source sidecar names a different chunk.")
    require(sidecar.get("page_map_sha256") == frozen["identities"]["page_map_sha256"], "sidecar_identity_mismatch", "Source sidecar page-map hash differs.")
    require(sidecar.get("chunk_manifest_sha256") == frozen["identities"]["chunk_manifest_sha256"], "sidecar_identity_mismatch", "Source sidecar chunk-manifest hash differs.")
    record = frozen["chunks"][chunk_id]
    owned = flatten_ranges(record["owned_document_page_ranges"], f"{chunk_id}.owned_document_page_ranges")
    context = flatten_ranges(record.get("context_document_page_ranges", []), f"{chunk_id}.context_document_page_ranges")
    selected = sorted(set(owned) | set(context))
    page_map_by_page = {item.get("document_page"): item for item in frozen["page_map"].get("pages", []) if isinstance(item, dict)}
    expected_pages = [
        {
            "chunk_pdf_page": index,
            "document_page": page,
            "source_page_label": page_map_by_page.get(page, {}).get("source_page_label"),
            "ownership": "owned" if page in set(owned) else "context",
        }
        for index, page in enumerate(selected, start=1)
    ]
    require(sidecar.get("pages") == expected_pages, "sidecar_page_mismatch", "Source sidecar is not the exact canonical chunk/page projection.")
    try:
        from pypdf import PdfReader
        source_reader = PdfReader(str(source_file), strict=True)
        chunk_reader = PdfReader(str(source_chunk), strict=True)
    except Exception as exc:
        raise PreparationError("source_pdf_invalid", "Source and source-chunk inputs must be parseable PDF files.") from exc
    require(not source_reader.is_encrypted and not chunk_reader.is_encrypted, "source_pdf_encrypted", "Parallel source reconnection requires readable, unencrypted PDF inputs.")
    require(len(chunk_reader.pages) == len(selected), "source_chunk_page_count", "Source chunk PDF page count differs from the exact sidecar selection.")
    require(all(1 <= page <= len(source_reader.pages) for page in selected), "source_page_out_of_range", "Sidecar selection references a page outside the complete source PDF.")

    def canonical_pdf_object(value: Any, active: set[int] | None = None, *, annotation: bool = False) -> Any:
        active = set() if active is None else active
        try:
            if value is not None and value.__class__.__name__ == "IndirectObject":
                value = value.get_object()
        except Exception as exc:
            raise PreparationError("source_page_unreadable", "Could not dereference a source PDF page resource.") from exc
        if value is None:
            return None
        identity = id(value)
        if identity in active:
            return {"cycle": value.__class__.__name__}
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, bytes):
            return {"bytes_sha256": sha256_bytes(value), "byte_length": len(value)}
        if isinstance(value, (list, tuple)):
            active.add(identity)
            try:
                return [canonical_pdf_object(item, active, annotation=annotation) for item in value]
            finally:
                active.remove(identity)
        if isinstance(value, dict):
            active.add(identity)
            try:
                result: dict[str, Any] = {}
                for key in sorted(value, key=str):
                    name = str(key)
                    if name == "/Length" or (annotation and name in {"/P", "/Parent"}):
                        continue
                    result[name] = canonical_pdf_object(value[key], active, annotation=annotation)
                if hasattr(value, "get_data"):
                    data = value.get_data()
                    result["$stream_sha256"] = sha256_bytes(data)
                    result["$stream_byte_length"] = len(data)
                return result
            finally:
                active.remove(identity)
        return str(value)

    def pdf_object_sha256(value: Any, *, annotation: bool = False) -> str:
        canonical = canonical_pdf_object(value, annotation=annotation)
        return sha256_bytes(json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))

    def page_fingerprint(page: Any) -> dict[str, Any]:
        try:
            contents = page.get_contents()
            content_bytes = b"" if contents is None else contents.get_data()
            media_box = [str(value) for value in page.mediabox]
            crop_box = [str(value) for value in page.cropbox]
            rotation = int(page.get("/Rotate", 0) or 0) % 360
            resources_sha256 = pdf_object_sha256(page.get("/Resources"))
            annotations_sha256 = pdf_object_sha256(page.get("/Annots", []), annotation=True)
        except Exception as exc:
            raise PreparationError("source_page_unreadable", "Could not read a source PDF page for exact chunk reconnection.") from exc
        return {"content_stream_sha256": sha256_bytes(content_bytes), "resources_sha256": resources_sha256, "annotations_sha256": annotations_sha256, "media_box": media_box, "crop_box": crop_box, "rotation": rotation}

    page_bindings: list[dict[str, Any]] = []
    for chunk_index, document_page in enumerate(selected):
        source_fingerprint = page_fingerprint(source_reader.pages[document_page - 1])
        chunk_fingerprint = page_fingerprint(chunk_reader.pages[chunk_index])
        require(source_fingerprint == chunk_fingerprint, "source_chunk_page_mismatch", f"Source chunk page {chunk_index + 1} is not the exact selected source page {document_page}.")
        page_bindings.append({"chunk_pdf_page": chunk_index + 1, "document_page": document_page, **source_fingerprint})
    return {
        "status": "verified",
        "source_status": "verified_by_sha256",
        "candidate_status": "normalized_candidate_verified",
        "source_chunk_status": "verified_by_sidecar_and_hash",
        "sidecar_status": "verified",
        "source_file_sha256": sha256_file(source_file),
        "source_chunk_file_sha256": sha256_file(source_chunk),
        "source_sidecar_file_sha256": sidecar_sha,
        "source_sidecar_bytes": sidecar_bytes,
        "owned_document_pages": owned,
        "page_binding_sha256": sha256_bytes(json.dumps(page_bindings, sort_keys=True, separators=(",", ":")).encode("utf-8")),
    }


def packet_assignment_index(packet: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    assignments: dict[str, dict[str, Any]] = {}
    paths: dict[str, list[str]] = {}
    packet_paths = packet.get("paths")
    require(isinstance(packet_paths, list), "locator_packet_shape", "Locator packet paths must be an array.")
    for path_index, record in enumerate(packet_paths):
        require(isinstance(record, dict), "locator_packet_shape", f"Locator packet paths[{path_index}] must be an object.")
        path_id = require_nonempty_string(record.get("path_id"), f"packet.paths[{path_index}].path_id")
        heading_path = record.get("heading_path")
        require(
            isinstance(heading_path, list) and bool(heading_path)
            and all(isinstance(item, str) and bool(item.strip()) for item in heading_path),
            "locator_packet_shape",
            f"Packet {path_id} must preserve a complete nonempty heading path.",
        )
        require(path_id not in paths or paths[path_id] == heading_path, "locator_packet_shape", f"Packet path ID {path_id} has conflicting heading paths.")
        paths[path_id] = heading_path
        values = record.get("locator_assignments")
        require(isinstance(values, list), "locator_packet_shape", f"Packet {path_id} locator_assignments must be an array.")
        for assignment in values:
            require(isinstance(assignment, dict), "locator_packet_shape", f"Packet {path_id} has a non-object assignment.")
            locator_id = require_nonempty_string(assignment.get("locator_id"), f"packet.{path_id}.locator_id")
            require(locator_id not in assignments, "duplicate_locator_assignment", f"Locator packet repeats assignment {locator_id}.")
            require(assignment.get("mapping_status") == "resolved", "unresolved_locator_assignment", f"Parallel locator packet contains unresolved assignment {locator_id}.")
            require(isinstance(assignment.get("document_page"), int) and not isinstance(assignment.get("document_page"), bool), "locator_packet_shape", f"Assignment {locator_id} lacks one resolved document page.")
            require(isinstance(assignment.get("source_page_label"), str), "locator_packet_shape", f"Assignment {locator_id} lacks a source page-label string.")
            assignments[locator_id] = {**assignment, "path_id": path_id, "heading_path": heading_path}
    summary = packet.get("summary")
    require(isinstance(summary, dict), "locator_packet_shape", "Locator packet summary is required.")
    require(summary.get("path_count") == len(packet_paths), "locator_packet_count_mismatch", "Locator packet path count does not recompute.")
    require(summary.get("locator_assignment_count") == len(assignments), "locator_packet_count_mismatch", "Locator packet assignment count does not recompute.")
    return assignments, paths


def validate_locator_packet(path: Path, frozen: dict[str, Any], chunk_id: str) -> dict[str, Any]:
    packet, payload, digest = validate_json_identity_file(path, "Candidate locator packet", "candidate-locator-chunk-v1")
    require(packet.get("candidate_id") == frozen["candidate_id"], "locator_packet_identity_mismatch", "Locator packet candidate ID differs.")
    require(packet.get("candidate_sha256") == frozen["candidate_sha256"], "locator_packet_identity_mismatch", "Locator packet candidate hash differs.")
    require(packet.get("page_map_sha256") == frozen["identities"]["page_map_sha256"], "locator_packet_identity_mismatch", "Locator packet page-map hash differs.")
    require(packet.get("chunk_manifest_sha256") == frozen["identities"]["chunk_manifest_sha256"], "locator_packet_identity_mismatch", "Locator packet chunk-manifest hash differs.")
    require(packet.get("chunk_id") == chunk_id, "locator_packet_chunk_mismatch", "Locator packet names a different chunk.")
    record = frozen["chunks"].get(chunk_id)
    require(record is not None, "unknown_chunk", f"Chunk {chunk_id} is absent from the frozen manifest.")
    expected_pages = sorted(flatten_ranges(record["owned_document_page_ranges"], f"{chunk_id}.owned_document_page_ranges"))
    require(packet.get("owned_document_pages") == expected_pages, "locator_packet_ownership_mismatch", "Locator packet owned pages differ from the frozen manifest.")
    assignments, paths = packet_assignment_index(packet)
    owned_set = set(expected_pages)
    foreign = sorted(locator_id for locator_id, value in assignments.items() if value.get("document_page") not in owned_set)
    require(not foreign, "foreign_chunk_assignment", "Locator packet contains assignments owned by another chunk.", foreign)
    return {"document": packet, "bytes": payload, "sha256": digest, "assignments": assignments, "paths": paths}


def candidate_path_index(candidate: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    paths: dict[str, dict[str, Any]] = {}
    locators: dict[str, dict[str, Any]] = {}
    records = candidate.get("records")
    require(isinstance(records, list), "candidate_shape", "Normalized candidate records must be an array.")
    for record in records:
        require(isinstance(record, dict), "candidate_shape", "Every normalized candidate record must be an object.")
        path_id = record.get("path_id")
        require(isinstance(path_id, str) and path_id not in paths, "candidate_shape", f"Duplicate or missing candidate path ID: {path_id}")
        paths[path_id] = record
        assignments = record.get("locator_assignments")
        require(isinstance(assignments, list), "candidate_shape", f"Candidate {path_id} locator_assignments must be an array.")
        for assignment in assignments:
            locator_id = assignment.get("locator_id") if isinstance(assignment, dict) else None
            require(isinstance(locator_id, str) and locator_id not in locators, "candidate_shape", f"Duplicate or missing candidate locator ID: {locator_id}")
            locators[locator_id] = {**assignment, "path_id": path_id, "heading_path": record.get("heading_path")}
    return paths, locators


def compare_packet_to_candidate(packet: dict[str, Any], frozen: dict[str, Any]) -> None:
    candidate_paths, candidate_locators = candidate_path_index(frozen["candidate"])
    for locator_id, assignment in packet["assignments"].items():
        canonical = candidate_locators.get(locator_id)
        require(canonical is not None, "locator_packet_candidate_mismatch", f"Packet locator {locator_id} is absent from normalized candidate.")
        for field in ("path_id", "heading_path", "document_page", "source_page_label", "mapping_status", "display_id", "displayed_locator", "range_id"):
            if field in assignment or field in canonical:
                require(assignment.get(field) == canonical.get(field), "locator_packet_candidate_mismatch", f"Packet locator {locator_id} differs from normalized candidate field {field}.")
        require(candidate_paths[assignment["path_id"]].get("heading_path") == assignment["heading_path"], "locator_packet_candidate_mismatch", f"Packet path changed for {locator_id}.")


def deterministic_treatment_id(subject_id: str, document_page: int, locator_class: str) -> str:
    return stable_identifier("TREAT", {"subject_id": subject_id, "document_page": document_page, "locator_class": locator_class})


def build_missing_worksets(frozen: dict[str, Any]) -> dict[str, dict[str, Any]]:
    owners = page_owner_map(frozen["chunk_manifest"])
    chunks = frozen["chunks"]
    packet_order = {chunk_id: record["packet_order"] for chunk_id, record in chunks.items()}
    worksets = {
        chunk_id: {
            "evidence_mode": MISSING_ACCESS_EVIDENCE_MODE,
            "source_adjudication_mode": MISSING_ACCESS_SOURCE_ADJUDICATION_MODE,
            "treatment_identity_rule": MISSING_ACCESS_TREATMENT_IDENTITY_RULE,
            "subject_ids": [],
            "reader_task_ids": [],
            "treatments": [],
        }
        for chunk_id in chunks
    }
    subject_owner: dict[str, str] = {}
    subject_priority: dict[str, str] = {}
    scored_subjects: dict[str, dict[str, Any]] = {}
    subjects = frozen["benchmark"].get("subjects")
    require(isinstance(subjects, list), "benchmark_shape", "Frozen benchmark subjects must be an array.")
    for subject in subjects:
        require(isinstance(subject, dict), "benchmark_shape", "Every frozen subject must be an object.")
        priority = subject.get("priority")
        if priority not in PRIORITIES:
            continue
        subject_id = require_nonempty_string(subject.get("subject_id"), "benchmark.subject_id")
        require(subject_id not in scored_subjects, "duplicate_subject_id", f"Frozen benchmark repeats {subject_id}.")
        evidence = subject.get("evidence")
        require(isinstance(evidence, list) and bool(evidence), "missing_access_ownership", f"Scored subject {subject_id} has no evidence for chunk ownership.")
        candidates: list[tuple[int, int, int, str]] = []
        treatments_by_identity: dict[tuple[int, str], dict[str, Any]] = {}
        subject_evidence_ids: set[str] = set()
        for item in evidence:
            require(isinstance(item, dict), "benchmark_shape", f"Subject {subject_id} contains non-object evidence.")
            page = item.get("document_page")
            require(isinstance(page, int) and not isinstance(page, bool) and page in owners, "missing_access_ownership", f"Subject {subject_id} evidence lacks a uniquely owned document page.")
            locator_class = item.get("locator_class", "supporting")
            require(locator_class in LOCATOR_CLASS_RANK, "benchmark_shape", f"Subject {subject_id} evidence has invalid locator_class {locator_class}.")
            chunk_id = owners[page]
            candidates.append((LOCATOR_CLASS_RANK[locator_class], packet_order[chunk_id], page, chunk_id))
            if locator_class != "incidental":
                evidence_id = require_nonempty_string(item.get("evidence_id"), f"benchmark.{subject_id}.evidence_id")
                require(evidence_id not in subject_evidence_ids, "duplicate_benchmark_evidence_id", f"Subject {subject_id} repeats benchmark evidence ID {evidence_id}.")
                subject_evidence_ids.add(evidence_id)
                treatment_id = deterministic_treatment_id(subject_id, page, locator_class)
                key = (page, locator_class)
                treatment = treatments_by_identity.setdefault(key, {
                    "treatment_id": treatment_id,
                    "subject_id": subject_id,
                    "document_page": page,
                    "locator_class": locator_class,
                    "evidence_ids": [],
                    "source_evidence_ids": [],
                })
                require(treatment["treatment_id"] == treatment_id, "treatment_identity_collision", f"Treatment identity collision for {subject_id} page {page} class {locator_class}.")
                treatment["evidence_ids"].append(evidence_id)
                source_evidence_id = item.get("source_evidence_id")
                if isinstance(source_evidence_id, str) and source_evidence_id.strip():
                    treatment["source_evidence_ids"].append(source_evidence_id)
        treatments = list(treatments_by_identity.values())
        for treatment in treatments:
            treatment["evidence_ids"].sort()
            treatment["source_evidence_ids"] = sorted(set(treatment["source_evidence_ids"]))
            treatment["evidence_count"] = len(treatment["evidence_ids"])
        explicit_owner = subject.get("owner_chunk_id")
        if explicit_owner is not None:
            require(explicit_owner in worksets, "missing_access_ownership", f"Subject {subject_id} owner_chunk_id is not a frozen chunk.")
            owner = explicit_owner
        else:
            principal = [item for item in evidence if item.get("locator_class", "supporting") == "principal"]
            eligible = principal or [item for item in evidence if item.get("locator_class", "supporting") != "incidental"]
            require(bool(eligible), "missing_access_ownership", f"Subject {subject_id} has no principal or non-incidental scored evidence for fallback ownership.")
            owner = min(
                (
                    item["document_page"],
                    packet_order[owners[item["document_page"]]],
                    owners[item["document_page"]],
                )
                for item in eligible
            )[2]
        subject_owner[subject_id] = owner
        subject_priority[subject_id] = priority
        scored_subjects[subject_id] = subject
        worksets[owner]["subject_ids"].append(subject_id)
        worksets[owner]["treatments"].extend(treatments)

    tasks = frozen["benchmark"].get("reader_tasks")
    require(isinstance(tasks, list), "benchmark_shape", "Frozen benchmark reader_tasks must be an array.")
    seen_tasks: set[str] = set()
    for task in tasks:
        require(isinstance(task, dict), "benchmark_shape", "Every reader task must be an object.")
        task_id = require_nonempty_string(task.get("task_id"), "benchmark.reader_task.task_id")
        require(task_id not in seen_tasks, "duplicate_reader_task", f"Frozen benchmark repeats {task_id}.")
        seen_tasks.add(task_id)
        subject_ids = task.get("subject_ids")
        require(isinstance(subject_ids, list) and bool(subject_ids), "benchmark_shape", f"Reader task {task_id} must reference subjects.")
        explicit_owner = task.get("owner_chunk_id")
        if explicit_owner is not None:
            require(explicit_owner in worksets, "missing_access_ownership", f"Reader task {task_id} owner_chunk_id is not a frozen chunk.")
            task_owner = explicit_owner
        else:
            first_subject = subject_ids[0]
            require(first_subject in subject_owner, "missing_access_ownership", f"Reader task {task_id}'s first frozen subject has no scored owner.")
            task_owner = subject_owner[first_subject]
        worksets[task_owner]["reader_task_ids"].append(task_id)

    for chunk_id, workset in worksets.items():
        workset["subject_ids"].sort()
        workset["reader_task_ids"].sort()
        workset["treatments"].sort(key=lambda item: item["treatment_id"])
        workset["treatment_ids"] = [item["treatment_id"] for item in workset["treatments"]]
        workset["workset_sha256"] = sha256_bytes(json.dumps(workset, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return worksets


def validate_evidence_ids(value: Any, field: str) -> list[str]:
    require(isinstance(value, list) and bool(value) and all(isinstance(item, str) and bool(item.strip()) for item in value), "parallel_evidence_required", f"{field} must contain one or more evidence IDs.")
    require(not duplicate_values(value), "duplicate_evidence_id", f"{field} contains duplicate evidence IDs.")
    return value


def validate_locator_audit(artifact: dict[str, Any], frozen: dict[str, Any], packet: dict[str, Any], chunk_id: str, parallel: bool = True) -> dict[str, Any]:
    require(artifact.get("schema_version") == LOCATOR_AUDIT_VERSION, "audit_schema", f"Expected {LOCATOR_AUDIT_VERSION}.")
    require(artifact.get("evaluation_id") == frozen["state"].get("evaluation_id"), "audit_identity_mismatch", "Locator audit evaluation ID differs.")
    require(artifact.get("candidate_sha256") == frozen["candidate_sha256"], "audit_identity_mismatch", "Locator audit candidate hash differs.")
    require(artifact.get("chunk_id") == chunk_id, "audit_chunk_mismatch", "Locator audit names a different chunk.")
    if parallel:
        provenance = artifact.get("provenance")
        expected_provenance = {
            "source_sha256": frozen["identities"]["source_sha256"],
            "benchmark_sha256": frozen["benchmark"]["benchmark_sha256"],
            "benchmark_lock_sha256": frozen["benchmark_lock"]["lock_sha256"],
            "policy_sha256": frozen["policy"]["policy_sha256"],
            "page_map_sha256": frozen["page_map"]["page_map_sha256"],
            "chunk_manifest_sha256": frozen["chunk_manifest"]["chunk_manifest_sha256"],
            "normalized_candidate_file_sha256": frozen["candidate_file_sha256"],
            "item_inventory_file_sha256": frozen["inventory_file_sha256"],
            "locator_packet_file_sha256": packet["sha256"],
        }
        require(isinstance(provenance, dict) and all(provenance.get(field) == expected for field, expected in expected_provenance.items()), "audit_provenance_mismatch", "Parallel locator audit provenance does not bind every frozen input.")
    expected = list(packet["assignments"])
    require(artifact.get("expected_locator_ids") == expected or set(artifact.get("expected_locator_ids", [])) == set(expected), "locator_denominator_mismatch", "Locator audit expected IDs differ from the exact packet.")
    require(not duplicate_values(artifact.get("expected_locator_ids", [])), "duplicate_locator_assignment", "Locator audit expected IDs contain duplicates.")
    judgments = artifact.get("judgments")
    require(isinstance(judgments, list), "audit_shape", "Locator audit judgments must be an array.")
    ids: list[str] = []
    judgment_counts = Counter({key: 0 for key in sorted(LOCATOR_STATUSES)})
    severity_counts = Counter({key: 0 for key in sorted(SEVERITIES)})
    error_counts: Counter[str] = Counter()
    for index, judgment in enumerate(judgments):
        require(isinstance(judgment, dict), "audit_shape", f"Locator judgment {index} must be an object.")
        locator_id = require_nonempty_string(judgment.get("locator_id"), f"judgments[{index}].locator_id")
        ids.append(locator_id)
        assignment = packet["assignments"].get(locator_id)
        require(assignment is not None, "foreign_chunk_assignment", f"Locator audit contains foreign assignment {locator_id}.")
        require(judgment.get("path_id") == assignment["path_id"], "complete_path_mismatch", f"Locator judgment {locator_id} path ID differs from packet.")
        require(judgment.get("complete_heading_path") == assignment["heading_path"], "complete_path_mismatch", f"Locator judgment {locator_id} does not preserve the complete heading path.")
        require(judgment.get("document_page") == assignment.get("document_page"), "locator_assignment_mismatch", f"Locator judgment {locator_id} document page differs.")
        require(judgment.get("source_page_label") == assignment.get("source_page_label"), "locator_assignment_mismatch", f"Locator judgment {locator_id} source label differs.")
        require(judgment.get("source_scope_status") in LOCATOR_SCOPE_STATUSES, "audit_judgment", f"Locator {locator_id} has invalid source_scope_status.")
        require(judgment.get("treatment_class") in TREATMENT_CLASSES, "audit_judgment", f"Locator {locator_id} has invalid treatment_class.")
        status = judgment.get("judgment")
        require(status in LOCATOR_STATUSES, "audit_judgment", f"Locator {locator_id} has invalid judgment.")
        require(judgment.get("confidence") in CONFIDENCES, "audit_judgment", f"Locator {locator_id} has invalid confidence.")
        severity = judgment.get("severity")
        require(severity in SEVERITIES, "audit_judgment", f"Locator {locator_id} has invalid severity.")
        require_nonempty_string(judgment.get("evidence_summary"), f"judgments[{index}].evidence_summary", 2000)
        if parallel:
            validate_evidence_ids(judgment.get("evidence_ids"), f"judgments[{index}].evidence_ids")
        codes = judgment.get("error_codes")
        require(isinstance(codes, list) and all(code in LOCATOR_ERROR_CODES for code in codes), "audit_error_code", f"Locator {locator_id} contains a disallowed worker error code.")
        require(not duplicate_values(codes), "audit_error_code", f"Locator {locator_id} repeats an error code.")
        judgment_counts[status] += 1
        severity_counts[severity] += 1
        error_counts.update(codes)
    duplicates = duplicate_values(ids)
    require(not duplicates, "duplicate_locator_assignment", "Locator audit repeats assignment IDs.", duplicates)
    require(set(ids) == set(expected), "missing_locator_assignment", "Locator audit does not judge the exact packet assignment set.", {"missing": sorted(set(expected) - set(ids)), "foreign": sorted(set(ids) - set(expected))})
    completion = artifact.get("completion")
    require(isinstance(completion, dict), "audit_completion", "Locator audit completion record is required.")
    require(completion.get("expected") == len(expected) and completion.get("judged") == len(ids) and completion.get("unique") is True and completion.get("complete") is True, "audit_completion", "Locator audit completion denominators do not recompute.")
    return {
        "locator_ids": ids,
        "path_ids": sorted(packet["paths"]),
        "judgment_counts": dict(sorted(judgment_counts.items())),
        "severity_counts": dict(sorted(severity_counts.items())),
        "error_code_counts": dict(sorted(error_counts.items())),
        "completion": {"expected": len(expected), "judged": len(ids), "unique": True, "complete": True},
    }


def validate_missing_access_audit(artifact: dict[str, Any], frozen: dict[str, Any], workset: dict[str, Any], chunk_id: str, parallel: bool = True, locator_audit_set_sha256: str | None = None) -> dict[str, Any]:
    require(artifact.get("schema_version") == MISSING_AUDIT_VERSION, "audit_schema", f"Expected {MISSING_AUDIT_VERSION}.")
    require(artifact.get("evaluation_id") == frozen["state"].get("evaluation_id"), "audit_identity_mismatch", "Missing-access audit evaluation ID differs.")
    require(artifact.get("candidate_sha256") == frozen["candidate_sha256"], "audit_identity_mismatch", "Missing-access audit candidate hash differs.")
    require(artifact.get("benchmark_sha256") == frozen["benchmark"]["benchmark_sha256"], "audit_identity_mismatch", "Missing-access audit benchmark hash differs.")
    require(artifact.get("chunk_id") == chunk_id, "audit_chunk_mismatch", "Missing-access audit names a different chunk.")
    if parallel:
        provenance = artifact.get("provenance")
        expected_provenance = {
            "source_sha256": frozen["identities"]["source_sha256"],
            "benchmark_file_sha256": frozen["benchmark_file_sha256"],
            "benchmark_lock_sha256": frozen["benchmark_lock"]["lock_sha256"],
            "policy_sha256": frozen["policy"]["policy_sha256"],
            "page_map_sha256": frozen["page_map"]["page_map_sha256"],
            "chunk_manifest_sha256": frozen["chunk_manifest"]["chunk_manifest_sha256"],
            "normalized_candidate_file_sha256": frozen["candidate_file_sha256"],
            "item_inventory_file_sha256": frozen["inventory_file_sha256"],
            "missing_access_ownership_sha256": workset["workset_sha256"],
        }
        if locator_audit_set_sha256 is not None:
            expected_provenance["locator_audit_set_sha256"] = locator_audit_set_sha256
        require(isinstance(provenance, dict) and all(provenance.get(field) == expected for field, expected in expected_provenance.items()), "audit_provenance_mismatch", "Parallel missing-access audit provenance does not bind every frozen input and ownership plan.")
    expected_subjects = workset["subject_ids"]
    expected_tasks = workset["reader_task_ids"]
    expected_treatments = workset["treatment_ids"]
    require(set(artifact.get("expected_subject_ids", [])) == set(expected_subjects) and not duplicate_values(artifact.get("expected_subject_ids", [])), "subject_denominator_mismatch", "Missing-access expected subjects differ from deterministic ownership.")
    require(set(artifact.get("expected_reader_task_ids", [])) == set(expected_tasks) and not duplicate_values(artifact.get("expected_reader_task_ids", [])), "reader_task_denominator_mismatch", "Missing-access reader tasks differ from deterministic ownership.")
    require(set(artifact.get("expected_treatment_ids", [])) == set(expected_treatments) and not duplicate_values(artifact.get("expected_treatment_ids", [])), "treatment_denominator_mismatch", "Missing-access treatments differ from deterministic ownership.")

    subject_index = {item.get("subject_id"): item for item in frozen["benchmark"].get("subjects", []) if isinstance(item, dict)}
    candidate_path_ids = {item.get("path_id") for item in frozen["inventory"].get("paths", []) if isinstance(item, dict)}
    _, candidate_locators = candidate_path_index(frozen["candidate"])
    workset_treatments_by_subject: dict[str, list[dict[str, Any]]] = {}
    for treatment in workset["treatments"]:
        workset_treatments_by_subject.setdefault(treatment["subject_id"], []).append(treatment)
    subject_judgments = artifact.get("subject_judgments")
    require(isinstance(subject_judgments, list), "audit_shape", "Missing-access subject_judgments must be an array.")
    subject_ids: list[str] = []
    coverage_counts = Counter({key: 0 for key in sorted(COVERAGE_STATUSES)})
    access_counts = Counter({key: 0 for key in ("direct_only", "cross_reference_only", "both", "none", "uninspectable")})
    severity_counts = Counter({key: 0 for key in sorted(SEVERITIES)})
    error_code_counts: Counter[str] = Counter()
    subject_recall_records: dict[str, dict[str, Any]] = {}
    reported_missed_treatments: dict[str, set[tuple[int, str]]] = {}
    for index, judgment in enumerate(subject_judgments):
        require(isinstance(judgment, dict), "audit_shape", f"subject_judgments[{index}] must be an object.")
        subject_id = require_nonempty_string(judgment.get("subject_id"), f"subject_judgments[{index}].subject_id")
        subject_ids.append(subject_id)
        require(subject_id in expected_subjects, "foreign_chunk_subject", f"Missing-access audit contains foreign subject {subject_id}.")
        expected_subject = subject_index[subject_id]
        require(judgment.get("priority") == expected_subject.get("priority"), "subject_identity_mismatch", f"Subject {subject_id} priority differs from benchmark.")
        coverage = judgment.get("coverage")
        require(coverage in COVERAGE_STATUSES, "audit_judgment", f"Subject {subject_id} has invalid coverage.")
        require(isinstance(judgment.get("direct_access"), bool) and isinstance(judgment.get("cross_reference_access"), bool), "audit_judgment", f"Subject {subject_id} access-route fields must be boolean.")
        require(judgment.get("stance_preserved") in STANCE_STATUSES, "audit_judgment", f"Subject {subject_id} has invalid stance status.")
        require(judgment.get("severity") in {"none", "minor", "major", "critical"}, "audit_judgment", f"Subject {subject_id} has invalid severity.")
        require(judgment.get("confidence") in CONFIDENCES, "audit_judgment", f"Subject {subject_id} has invalid confidence.")
        if parallel:
            require(judgment.get("realistic_first_lookup_success") in FIRST_LOOKUP_STATUSES, "audit_judgment", f"Subject {subject_id} must record realistic first-lookup success.")
        if parallel:
            validate_evidence_ids(judgment.get("evidence_ids"), f"subject_judgments[{index}].evidence_ids")
        matched = judgment.get("matched_path_ids")
        require(isinstance(matched, list) and not duplicate_values(matched) and set(matched).issubset(candidate_path_ids), "matched_path_mismatch", f"Subject {subject_id} matched paths are invalid.")
        expected_pages = sorted({item["document_page"] for item in workset_treatments_by_subject.get(subject_id, [])})
        found = judgment.get("found_document_pages")
        missed = judgment.get("missed_document_pages")
        require(judgment.get("expected_document_pages") == expected_pages, "treatment_page_mismatch", f"Subject {subject_id} expected pages differ from benchmark.")
        require(isinstance(found, list) and isinstance(missed, list) and not duplicate_values(found) and not duplicate_values(missed), "treatment_page_mismatch", f"Subject {subject_id} page accounting is malformed.")
        require(not (set(found) & set(missed)) and set(found) | set(missed) == set(expected_pages), "treatment_page_mismatch", f"Subject {subject_id} found/missed pages do not partition expected pages.")
        locator_recall = judgment.get("locator_recall")
        require(isinstance(locator_recall, dict), "locator_recall_missing", f"Subject {subject_id} must record locator recall separately from concept coverage.")
        require(locator_recall.get("expected") == len(expected_pages) and locator_recall.get("found") == len(found) and locator_recall.get("missed") == len(missed), "locator_recall_mismatch", f"Subject {subject_id} locator-recall counts do not match its exact page accounting.")
        expected_rate = None if not expected_pages else len(found) / len(expected_pages)
        if "rate" in locator_recall:
            require(locator_recall.get("rate") == expected_rate, "locator_recall_mismatch", f"Subject {subject_id} locator-recall rate does not recompute.")
        treatment_recall = judgment.get("treatment_recall")
        require(isinstance(treatment_recall, dict) and set(treatment_recall) == {"principal", "supporting", "synthesis_or_conclusion"}, "treatment_recall_missing", f"Subject {subject_id} must preserve all three treatment-class denominators.")
        for locator_class in ("principal", "supporting", "synthesis_or_conclusion"):
            class_record = treatment_recall.get(locator_class)
            require(isinstance(class_record, dict), "treatment_recall_missing", f"Subject {subject_id} lacks {locator_class} treatment recall.")
            expected_class_pages = sorted(item["document_page"] for item in workset_treatments_by_subject.get(subject_id, []) if item["locator_class"] == locator_class)
            found_class = class_record.get("found_document_pages")
            missed_class = class_record.get("missed_document_pages")
            uninspectable_class = class_record.get("uninspectable_document_pages")
            require(class_record.get("expected_document_pages") == expected_class_pages, "treatment_recall_mismatch", f"Subject {subject_id} {locator_class} expected pages differ from ownership plan.")
            require(isinstance(found_class, list) and isinstance(missed_class, list) and isinstance(uninspectable_class, list) and not duplicate_values(found_class) and not duplicate_values(missed_class) and not duplicate_values(uninspectable_class), "treatment_recall_mismatch", f"Subject {subject_id} {locator_class} treatment page accounting is malformed.")
            treatment_sets = [set(found_class), set(missed_class), set(uninspectable_class)]
            require(not any(treatment_sets[left] & treatment_sets[right] for left in range(3) for right in range(left + 1, 3)) and set().union(*treatment_sets) == set(expected_class_pages), "treatment_recall_mismatch", f"Subject {subject_id} {locator_class} treatment pages do not partition found, missed, and uninspectable denominators.")
        missing_routes = judgment.get("missing_routes")
        require(isinstance(missing_routes, list), "missing_route_accounting", f"Subject {subject_id} must record missing routes as an array.")
        route_types: list[str] = []
        for route_index, route in enumerate(missing_routes):
            require(isinstance(route, dict) and route.get("route_type") in {"direct", "cross_reference"}, "missing_route_accounting", f"Subject {subject_id} has an invalid missing route.")
            route_types.append(route["route_type"])
            require_nonempty_string(route.get("reason_code"), f"subject_judgments[{index}].missing_routes[{route_index}].reason_code", 128)
            validate_evidence_ids(route.get("evidence_ids"), f"subject_judgments[{index}].missing_routes[{route_index}].evidence_ids")
        require(not duplicate_values(route_types), "missing_route_accounting", f"Subject {subject_id} repeats a missing route type.")
        require(("direct" in route_types) == (not judgment["direct_access"]) and ("cross_reference" in route_types) == (not judgment["cross_reference_access"]), "missing_route_accounting", f"Subject {subject_id} missing routes do not match its access judgments.")
        missed_records = judgment.get("missed_treatments")
        require(isinstance(missed_records, list), "missed_treatment_accounting", f"Subject {subject_id} must record missed treatments as an array.")
        missed_keys: set[tuple[int, str]] = set()
        for missed_index, record in enumerate(missed_records):
            require(isinstance(record, dict) and isinstance(record.get("document_page"), int) and record.get("locator_class") in {"principal", "supporting", "synthesis_or_conclusion"}, "missed_treatment_accounting", f"Subject {subject_id} has an invalid missed-treatment record.")
            key = (record["document_page"], record["locator_class"])
            require(key not in missed_keys, "missed_treatment_accounting", f"Subject {subject_id} repeats a missed treatment.")
            missed_keys.add(key)
            require_nonempty_string(record.get("reason_code"), f"subject_judgments[{index}].missed_treatments[{missed_index}].reason_code", 128)
            validate_evidence_ids(record.get("evidence_ids"), f"subject_judgments[{index}].missed_treatments[{missed_index}].evidence_ids")
        reported_missed_treatments[subject_id] = missed_keys
        uncertainty = judgment.get("uncertainty")
        require(isinstance(uncertainty, dict) and uncertainty.get("status") in UNCERTAINTY_STATUSES, "uncertainty_missing", f"Subject {subject_id} must record uncertainty explicitly.")
        if uncertainty["status"] != "none":
            require_nonempty_string(uncertainty.get("reason"), f"subject_judgments[{index}].uncertainty.reason", 1000)
            validate_evidence_ids(uncertainty.get("evidence_ids"), f"subject_judgments[{index}].uncertainty.evidence_ids")
        codes = judgment.get("error_codes")
        require(isinstance(codes, list) and not duplicate_values(codes) and set(codes).issubset(MISSING_ERROR_CODES), "audit_error_code", f"Subject {subject_id} has invalid error-code accounting.")
        coverage_counts[coverage] += 1
        severity_counts[judgment["severity"]] += 1
        error_code_counts.update(codes)
        direct = judgment["direct_access"]
        cross = judgment["cross_reference_access"]
        access_counts["uninspectable" if coverage == "uninspectable" else "both" if direct and cross else "direct_only" if direct else "cross_reference_only" if cross else "none"] += 1
        subject_recall_records[subject_id] = treatment_recall
    require(not duplicate_values(subject_ids), "duplicate_subject_judgment", "Missing-access audit repeats subject judgments.")
    require(set(subject_ids) == set(expected_subjects), "missing_subject_judgment", "Missing-access audit does not contain the exact owned subject set.")

    task_results = artifact.get("reader_task_results")
    require(isinstance(task_results, list), "audit_shape", "reader_task_results must be an array.")
    task_ids: list[str] = []
    task_counts = Counter({key: 0 for key in sorted(TASK_STATUSES)})
    task_index = {item.get("task_id"): item for item in frozen["benchmark"].get("reader_tasks", []) if isinstance(item, dict)}
    for index, result in enumerate(task_results):
        require(isinstance(result, dict), "audit_shape", f"reader_task_results[{index}] must be an object.")
        task_id = require_nonempty_string(result.get("task_id"), f"reader_task_results[{index}].task_id")
        task_ids.append(task_id)
        require(task_id in expected_tasks, "foreign_chunk_reader_task", f"Missing-access audit contains foreign reader task {task_id}.")
        status = result.get("result")
        require(status in TASK_STATUSES, "audit_judgment", f"Reader task {task_id} has invalid result.")
        if parallel:
            validate_evidence_ids(result.get("evidence_ids"), f"reader_task_results[{index}].evidence_ids")
            require(result.get("subject_ids") == task_index[task_id].get("subject_ids"), "reader_task_identity_mismatch", f"Reader task {task_id} subject order differs from the frozen benchmark.")
            require(result.get("access_mode") in ACCESS_MODES, "audit_judgment", f"Reader task {task_id} must record its tested access mode.")
            matched = result.get("matched_path_ids")
            require(isinstance(matched, list) and not duplicate_values(matched) and set(matched).issubset(candidate_path_ids), "matched_path_mismatch", f"Reader task {task_id} matched paths are invalid.")
            require(result.get("severity") in SEVERITIES and result.get("confidence") in CONFIDENCES, "audit_judgment", f"Reader task {task_id} must record severity and confidence.")
            severity_counts[result["severity"]] += 1
        task_counts[status] += 1
    require(not duplicate_values(task_ids), "duplicate_reader_task_judgment", "Missing-access audit repeats reader tasks.")
    require(set(task_ids) == set(expected_tasks), "missing_reader_task_judgment", "Missing-access audit does not contain the exact owned reader-task set.")

    expected_treatment_index = {item["treatment_id"]: item for item in workset["treatments"]}
    treatment_judgments = artifact.get("treatment_judgments")
    require(isinstance(treatment_judgments, list), "audit_shape", "treatment_judgments must be an array.")
    treatment_ids: list[str] = []
    treatment_counts = Counter({key: 0 for key in sorted(TREATMENT_RECALL_STATUSES)})
    treatment_by_subject: dict[str, dict[str, dict[str, list[int]]]] = {}
    for index, judgment in enumerate(treatment_judgments):
        require(isinstance(judgment, dict), "audit_shape", f"treatment_judgments[{index}] must be an object.")
        treatment_id = require_nonempty_string(judgment.get("treatment_id"), f"treatment_judgments[{index}].treatment_id")
        treatment_ids.append(treatment_id)
        expected = expected_treatment_index.get(treatment_id)
        require(expected is not None, "foreign_chunk_treatment", f"Missing-access audit contains foreign treatment {treatment_id}.")
        for field in ("subject_id", "document_page", "locator_class"):
            require(judgment.get(field) == expected[field], "treatment_identity_mismatch", f"Treatment {treatment_id} field {field} differs from benchmark workset.")
        status = judgment.get("status")
        require(status in TREATMENT_RECALL_STATUSES, "audit_judgment", f"Treatment {treatment_id} has invalid status.")
        if parallel:
            evidence_ids = validate_evidence_ids(judgment.get("evidence_ids"), f"treatment_judgments[{index}].evidence_ids")
            require(
                set(expected["evidence_ids"]).issubset(evidence_ids),
                "treatment_evidence_incomplete",
                f"Treatment {treatment_id} must retain every coalesced benchmark evidence ID.",
                sorted(set(expected["evidence_ids"]) - set(evidence_ids)),
            )
        treatment_counts[status] += 1
        class_counts = treatment_by_subject.setdefault(expected["subject_id"], {}).setdefault(expected["locator_class"], {"found": [], "missed": [], "uninspectable": []})
        class_counts[status].append(expected["document_page"])
    require(not duplicate_values(treatment_ids), "duplicate_treatment_judgment", "Missing-access audit repeats treatment judgments.")
    require(set(treatment_ids) == set(expected_treatments), "missing_treatment_judgment", "Missing-access audit does not contain the exact treatment set.")
    for subject_id in expected_subjects:
        nonfound: set[tuple[int, str]] = set()
        for locator_class in ("principal", "supporting", "synthesis_or_conclusion"):
            actual = treatment_by_subject.get(subject_id, {}).get(locator_class, {"found": [], "missed": [], "uninspectable": []})
            recorded = subject_recall_records[subject_id][locator_class]
            require(sorted(actual["found"]) == sorted(recorded["found_document_pages"]) and sorted(actual["missed"]) == sorted(recorded["missed_document_pages"]) and sorted(actual["uninspectable"]) == sorted(recorded["uninspectable_document_pages"]), "treatment_recall_mismatch", f"Subject {subject_id} {locator_class} summary differs from exact treatment judgments.")
            nonfound.update((page, locator_class) for page in actual["missed"])
        require(reported_missed_treatments[subject_id] == nonfound, "missed_treatment_accounting", f"Subject {subject_id} missed-treatment ledger differs from exact non-found judgments.")

    for field, expected_count, actual_count in (
        ("completion", len(expected_subjects), len(subject_ids)),
        ("reader_task_completion", len(expected_tasks), len(task_ids)),
        ("treatment_completion", len(expected_treatments), len(treatment_ids)),
    ):
        completion = artifact.get(field)
        require(isinstance(completion, dict), "audit_completion", f"{field} is required.")
        require(completion.get("expected") == expected_count and completion.get("judged") == actual_count and completion.get("complete") is True, "audit_completion", f"{field} denominators do not recompute.")
        if "unique" in completion:
            require(completion.get("unique") is True, "audit_completion", f"{field}.unique must be true.")

    dependency_defects = list(artifact.get("dependency_defects", []))
    for subject in subject_judgments:
        nested = subject.get("dependency_defects", [])
        require(isinstance(nested, list), "dependency_defect_shape", "Subject dependency_defects must be an array.")
        dependency_defects.extend(nested)
    require(isinstance(dependency_defects, list) and all(isinstance(item, dict) for item in dependency_defects), "dependency_defect_shape", "dependency_defects must be an array of objects.")
    defect_ids = [item.get("defect_id") for item in dependency_defects]
    require(all(isinstance(item, str) and item for item in defect_ids) and not duplicate_values(defect_ids), "dependency_defect_shape", "Dependency defects require unique IDs.")
    for defect in dependency_defects:
        require(defect.get("dependency_type") == "locator_audit" and defect.get("disposition") == "reported_without_reinterpretation", "dependency_defect_shape", f"Dependency defect {defect.get('defect_id')} must identify locator_audit and prohibit silent reinterpretation.")
        require(defect.get("locator_id") in candidate_locators, "dependency_defect_locator", f"Dependency defect {defect.get('defect_id')} names an unknown locator.")
        coverage_subject_ids = defect.get("coverage_subject_ids")
        require(isinstance(coverage_subject_ids, list) and bool(coverage_subject_ids) and not duplicate_values(coverage_subject_ids) and set(coverage_subject_ids).issubset(expected_subjects), "dependency_defect_shape", f"Dependency defect {defect.get('defect_id')} lacks valid coverage subject IDs.")
        require_nonempty_string(defect.get("observed_conflict"), f"dependency_defect[{defect.get('defect_id')}].observed_conflict", 2000)
        require(defect.get("confidence") in CONFIDENCES, "dependency_defect_shape", f"Dependency defect {defect.get('defect_id')} lacks confidence.")
        require_nonempty_string(defect.get("required_adjudication"), f"dependency_defect[{defect.get('defect_id')}].required_adjudication", 1000)
        validate_evidence_ids(defect.get("evidence_ids"), f"dependency_defect[{defect.get('defect_id')}].evidence_ids")
    locator_expected = sum(len(item.get("expected_document_pages", [])) for item in subject_judgments)
    locator_found = sum(len(item.get("found_document_pages", [])) for item in subject_judgments)
    locator_missed = sum(len(item.get("missed_document_pages", [])) for item in subject_judgments)
    require(locator_expected == locator_found + locator_missed, "locator_recall_mismatch", "Global locator-recall denominator does not partition exactly.")
    treatment_by_class: dict[str, dict[str, int]] = {}
    for locator_class in ("principal", "supporting", "synthesis_or_conclusion"):
        class_judgments = [item for item in treatment_judgments if item["locator_class"] == locator_class]
        treatment_by_class[locator_class] = {"expected": len(class_judgments), "found": sum(item["status"] == "found" for item in class_judgments), "missed": sum(item["status"] == "missed" for item in class_judgments), "uninspectable": sum(item["status"] == "uninspectable" for item in class_judgments)}
    return {
        "subject_ids": subject_ids,
        "reader_task_ids": task_ids,
        "treatment_ids": treatment_ids,
        "concept_coverage_counts": dict(sorted(coverage_counts.items())),
        "access_route_counts": dict(sorted(access_counts.items())),
        "reader_task_result_counts": dict(sorted(task_counts.items())),
        "treatment_recall": dict(sorted(treatment_counts.items())),
        "treatment_recall_by_class": treatment_by_class,
        "locator_recall": {"expected": locator_expected, "found": locator_found, "missed": locator_missed},
        "severity_counts": dict(sorted(severity_counts.items())),
        "error_code_counts": dict(sorted(error_code_counts.items())),
        "dependency_defect_count": len(dependency_defects),
        "completion": {
            "subjects": {"expected": len(expected_subjects), "judged": len(subject_ids), "complete": True},
            "reader_tasks": {"expected": len(expected_tasks), "judged": len(task_ids), "complete": True},
            "treatments": {"expected": len(expected_treatments), "judged": len(treatment_ids), "complete": True},
        },
    }


def validate_repository_state(
    path: Path,
    project: str,
    base_branch: str,
    worker_branch: str,
) -> dict[str, Any]:
    value = exact_keys(
        load_json(path.resolve(), "Candidate repository state"),
        {"schema_version", "candidate_project", "is_empty", "default_branch", "base_commit", "branches", "observed_at"},
        "Candidate repository state",
    )
    require(value["schema_version"] == REPOSITORY_STATE_VERSION, "repository_state_schema", f"Expected {REPOSITORY_STATE_VERSION}.")
    require(value["candidate_project"] == project, "repository_identity_mismatch", "Repository evidence names a different candidate project.")
    require_timestamp(value["observed_at"], "repository_state.observed_at")
    require(value["is_empty"] is False, "empty_candidate_repository", "Candidate-audit workers require an immutable existing base commit.")
    require(value["default_branch"] == base_branch, "base_branch_mismatch", "Requested base branch differs from the observed default branch.")
    base_commit = require_commit(value["base_commit"], "repository_state.base_commit")
    branches = value["branches"]
    require(isinstance(branches, list) and all(isinstance(item, str) and item for item in branches), "repository_state_shape", "Repository branches must be strings.")
    require(not duplicate_values(branches), "repository_state_shape", "Repository branch evidence contains duplicates.")
    require(base_branch in branches, "base_branch_missing", "Observed branches do not contain the requested base branch.")
    require(worker_branch not in branches, "worker_branch_exists", f"Refusing to overwrite existing branch {worker_branch}.")
    return {**value, "base_commit": base_commit}


def load_locator_audit_set(paths: list[str], frozen: dict[str, Any]) -> dict[str, Any]:
    expected_chunks = set(frozen["chunks"])
    require(len(paths) == len(expected_chunks), "locator_audit_set_incomplete", "Exactly one canonical locator audit is required for every frozen chunk.")
    owners = page_owner_map(frozen["chunk_manifest"])
    candidate_paths, candidate_locators = candidate_path_index(frozen["candidate"])
    expected_by_chunk: dict[str, dict[str, dict[str, Any]]] = {chunk_id: {} for chunk_id in expected_chunks}
    for locator_id, assignment in candidate_locators.items():
        if assignment.get("mapping_status") != "resolved":
            continue
        page = assignment.get("document_page")
        require(page in owners, "locator_audit_set_ownership", f"Resolved normalized locator {locator_id} has no frozen chunk owner.")
        expected_by_chunk[owners[page]][locator_id] = assignment
    records: list[dict[str, Any]] = []
    chunks: set[str] = set()
    locator_ids: list[str] = []
    for raw_path in paths:
        path = Path(raw_path).resolve()
        artifact, payload, digest = load_json_snapshot(path, "Canonical locator audit")
        require(artifact.get("schema_version") == LOCATOR_AUDIT_VERSION, "locator_audit_set_schema", f"Expected {LOCATOR_AUDIT_VERSION}.")
        require(artifact.get("evaluation_id") == frozen["state"].get("evaluation_id"), "locator_audit_set_identity", "Locator audit evaluation identity differs.")
        require(artifact.get("candidate_sha256") == frozen["candidate_sha256"], "locator_audit_set_identity", "Locator audit candidate identity differs.")
        chunk_id = validate_chunk_id(artifact.get("chunk_id"))
        require(chunk_id in expected_chunks and chunk_id not in chunks, "locator_audit_set_chunk", f"Unexpected or duplicate locator audit chunk {chunk_id}.")
        manifest_record_for_path(frozen, path)
        assignments = expected_by_chunk[chunk_id]
        path_ids = {item["path_id"] for item in assignments.values()}
        pseudo_packet = {
            "sha256": sha256_bytes(json.dumps({"chunk_id": chunk_id, "assignment_ids": sorted(assignments)}, sort_keys=True, separators=(",", ":")).encode("utf-8")),
            "assignments": assignments,
            "paths": {path_id: candidate_paths[path_id]["heading_path"] for path_id in path_ids},
        }
        result = validate_locator_audit(artifact, frozen, pseudo_packet, chunk_id, parallel=False)
        actual = result["locator_ids"]
        chunks.add(chunk_id)
        locator_ids.extend(actual)
        records.append({"chunk_id": chunk_id, "file_sha256": digest, "byte_length": len(payload), "locator_ids": sorted(actual)})
    require(chunks == expected_chunks, "locator_audit_set_incomplete", "Canonical locator audit set does not cover every frozen chunk.")
    require(not duplicate_values(locator_ids), "duplicate_locator_assignment", "Canonical locator audits duplicate locator-assignment IDs across chunks.")
    records.sort(key=lambda item: item["chunk_id"])
    digest = sha256_bytes(json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return {"records": records, "sha256": digest, "locator_ids": sorted(locator_ids)}


def public_scan(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            require(key.casefold() not in PUBLIC_FORBIDDEN_KEYS, "public_forbidden_key", f"Public report contains forbidden key {path}.{key}.")
            public_scan(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            public_scan(nested, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.casefold()
        require(not re.search(r"(?:^|[\s\"'])(?:/root/|/home/|/users/|[a-z]:\\\\)", value, re.IGNORECASE), "public_absolute_path", f"Public report contains an absolute local path at {path}.")
        require("library://" not in lowered and "library identifier" not in lowered, "public_library_identifier", f"Public report contains a Library identifier at {path}.")
        for pattern in SECRET_PATTERNS:
            require(pattern.search(value) is None, "public_secret", f"Public report appears to contain secret material at {path}.")


def allowed_keys(value: Any, allowed: set[str], required: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), "public_audit_shape", f"{label} must be an object.")
    actual = set(value)
    require(required.issubset(actual) and actual.issubset(allowed), "public_audit_shape", f"{label} has missing or unexpected properties.", {"required": sorted(required), "allowed": sorted(allowed), "actual": sorted(actual)})
    return value


def public_audit_scan(value: Any, path: str = "$") -> None:
    """Reject non-contract fields, secrets, paths, and unbounded text before public audit publication."""
    if isinstance(value, dict):
        for key, nested in value.items():
            require(key.casefold() not in PUBLIC_AUDIT_FORBIDDEN_KEYS, "public_audit_forbidden_key", f"Public canonical audit contains forbidden key {path}.{key}.")
            public_audit_scan(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            public_audit_scan(nested, f"{path}[{index}]")
    elif isinstance(value, str):
        require(len(value) <= 2000, "public_audit_text_too_long", f"Public canonical audit string exceeds 2,000 characters at {path}.")
        lowered = value.casefold()
        require(not re.search(r"(?:^|[\s\"'])(?:/root/|/home/|/users/|[a-z]:\\\\)", value, re.IGNORECASE), "public_absolute_path", f"Public canonical audit contains an absolute local path at {path}.")
        require("library://" not in lowered and "library identifier" not in lowered, "public_library_identifier", f"Public canonical audit contains a Library identifier at {path}.")
        for pattern in SECRET_PATTERNS:
            require(pattern.search(value) is None, "public_secret", f"Public canonical audit appears to contain secret material at {path}.")


def validate_public_locator_audit_shape(artifact: dict[str, Any], chunk_id: str | None = None) -> dict[str, Any]:
    top_required = {"schema_version", "evaluation_id", "candidate_sha256", "chunk_id", "provenance", "expected_locator_ids", "judgments", "completion"}
    allowed_keys(artifact, top_required | {"candidate_id"}, top_required, "Public locator audit")
    require(artifact["schema_version"] == LOCATOR_AUDIT_VERSION, "public_audit_schema", f"Expected {LOCATOR_AUDIT_VERSION}.")
    actual_chunk = validate_chunk_id(artifact["chunk_id"])
    require(chunk_id is None or actual_chunk == chunk_id, "public_audit_chunk", "Public locator audit names a different chunk.")
    provenance_fields = {"source_sha256", "benchmark_sha256", "benchmark_lock_sha256", "policy_sha256", "page_map_sha256", "chunk_manifest_sha256", "normalized_candidate_file_sha256", "item_inventory_file_sha256", "locator_packet_file_sha256"}
    provenance = allowed_keys(artifact["provenance"], provenance_fields, provenance_fields, "Public locator audit provenance")
    for field, value in provenance.items():
        require_sha256(value, f"public_locator_audit.provenance.{field}")
    judgments = artifact["judgments"]
    require(isinstance(judgments, list), "public_audit_shape", "Public locator audit judgments must be an array.")
    judgment_fields = {"locator_id", "path_id", "complete_heading_path", "document_page", "source_page_label", "source_scope_status", "treatment_class", "judgment", "evidence_summary", "evidence_ids", "confidence", "error_codes", "severity"}
    for index, judgment in enumerate(judgments):
        allowed_keys(judgment, judgment_fields, judgment_fields, f"Public locator judgment {index}")
    completion_fields = {"expected", "judged", "unique", "complete"}
    allowed_keys(artifact["completion"], completion_fields, completion_fields, "Public locator audit completion")
    public_audit_scan(artifact)
    return {"audit_kind": "locator", "chunk_id": actual_chunk, "schema_version": LOCATOR_AUDIT_VERSION}


def validate_public_missing_audit_shape(artifact: dict[str, Any], chunk_id: str | None = None) -> dict[str, Any]:
    top_required = {"schema_version", "evaluation_id", "benchmark_sha256", "candidate_sha256", "chunk_id", "missing_access_ownership_sha256", "provenance", "expected_subject_ids", "expected_reader_task_ids", "expected_treatment_ids", "subject_judgments", "reader_task_results", "treatment_judgments", "completion", "reader_task_completion", "treatment_completion"}
    allowed_keys(artifact, top_required | {"dependency_defects"}, top_required, "Public missing-access audit")
    require(artifact["schema_version"] == MISSING_AUDIT_VERSION, "public_audit_schema", f"Expected {MISSING_AUDIT_VERSION}.")
    actual_chunk = validate_chunk_id(artifact["chunk_id"])
    require(chunk_id is None or actual_chunk == chunk_id, "public_audit_chunk", "Public missing-access audit names a different chunk.")
    provenance_fields = {"source_sha256", "benchmark_file_sha256", "benchmark_lock_sha256", "policy_sha256", "page_map_sha256", "chunk_manifest_sha256", "normalized_candidate_file_sha256", "item_inventory_file_sha256", "missing_access_ownership_sha256", "locator_audit_set_sha256"}
    provenance = allowed_keys(artifact["provenance"], provenance_fields, provenance_fields, "Public missing-access audit provenance")
    for field, value in provenance.items():
        require_sha256(value, f"public_missing_access_audit.provenance.{field}")
    completion_fields = {"expected", "judged", "unique", "complete"}
    for field in ("completion", "reader_task_completion", "treatment_completion"):
        allowed_keys(artifact[field], completion_fields, completion_fields, f"Public missing-access audit {field}")
    recall_fields = {"expected", "found", "missed", "rate"}
    treatment_class_fields = {"expected_document_pages", "found_document_pages", "missed_document_pages", "uninspectable_document_pages"}
    route_fields = {"route_type", "reason_code", "evidence_ids"}
    missed_fields = {"document_page", "locator_class", "reason_code", "evidence_ids"}
    uncertainty_allowed = {"status", "reason", "evidence_ids"}
    subject_required = {"subject_id", "priority", "coverage", "direct_access", "cross_reference_access", "realistic_first_lookup_success", "stance_preserved", "severity", "confidence", "evidence_ids", "matched_path_ids", "expected_document_pages", "found_document_pages", "missed_document_pages", "locator_recall", "treatment_recall", "missing_routes", "missed_treatments", "uncertainty", "error_codes"}
    for index, judgment in enumerate(artifact["subject_judgments"]):
        allowed_keys(judgment, subject_required | {"dependency_defects"}, subject_required, f"Public subject judgment {index}")
        allowed_keys(judgment["locator_recall"], recall_fields, {"expected", "found", "missed"}, f"Public subject judgment {index} locator_recall")
        treatment = allowed_keys(judgment["treatment_recall"], set(LOCATOR_CLASS_RANK) - {"incidental"}, set(LOCATOR_CLASS_RANK) - {"incidental"}, f"Public subject judgment {index} treatment_recall")
        for locator_class, record in treatment.items():
            allowed_keys(record, treatment_class_fields, treatment_class_fields, f"Public subject judgment {index} treatment_recall.{locator_class}")
        for route_index, route in enumerate(judgment["missing_routes"]):
            allowed_keys(route, route_fields, route_fields, f"Public subject judgment {index} missing route {route_index}")
        for missed_index, record in enumerate(judgment["missed_treatments"]):
            allowed_keys(record, missed_fields, missed_fields, f"Public subject judgment {index} missed treatment {missed_index}")
        uncertainty = allowed_keys(judgment["uncertainty"], uncertainty_allowed, {"status"}, f"Public subject judgment {index} uncertainty")
        require(uncertainty.get("status") == "none" or {"reason", "evidence_ids"}.issubset(uncertainty), "public_audit_shape", f"Public subject judgment {index} uncertainty lacks its explanation binding.")
    task_fields = {"task_id", "subject_ids", "result", "access_mode", "matched_path_ids", "severity", "confidence", "evidence_ids"}
    for index, result in enumerate(artifact["reader_task_results"]):
        allowed_keys(result, task_fields, task_fields, f"Public reader-task result {index}")
    treatment_fields = {"treatment_id", "subject_id", "document_page", "locator_class", "status", "evidence_ids"}
    for index, judgment in enumerate(artifact["treatment_judgments"]):
        allowed_keys(judgment, treatment_fields, treatment_fields, f"Public treatment judgment {index}")
    defect_fields = {"defect_id", "dependency_type", "disposition", "locator_id", "coverage_subject_ids", "observed_conflict", "confidence", "required_adjudication", "evidence_ids"}
    defects = list(artifact.get("dependency_defects", []))
    for judgment in artifact["subject_judgments"]:
        defects.extend(judgment.get("dependency_defects", []))
    for index, defect in enumerate(defects):
        allowed_keys(defect, defect_fields, defect_fields, f"Public dependency defect {index}")
    public_audit_scan(artifact)
    return {"audit_kind": "missing_access", "chunk_id": actual_chunk, "schema_version": MISSING_AUDIT_VERSION}


def validate_public_canonical_audit(artifact: dict[str, Any], audit_kind: str, chunk_id: str | None = None) -> dict[str, Any]:
    return validate_public_locator_audit_shape(artifact, chunk_id) if audit_kind == "locator" else validate_public_missing_audit_shape(artifact, chunk_id)


def validate_public_artifact(document: dict[str, Any], audit_kind: str, chunk_id: str, publication_profile: str) -> dict[str, Any]:
    if publication_profile == PUBLIC_EVALUATION_ARTIFACTS:
        return validate_public_canonical_audit(document, audit_kind, chunk_id)
    return validate_public_report(document, audit_kind, chunk_id)


def write_public_artifact(path: Path, document: dict[str, Any], source_payload: bytes, publication_profile: str) -> None:
    if publication_profile == PUBLIC_EVALUATION_ARTIFACTS:
        replace_bytes_atomic(path, source_payload)
    else:
        write_json_atomic(path, document)


def validate_count_map(value: Any, keys: set[str], field: str, allow_subset: bool = False) -> dict[str, int]:
    require(isinstance(value, dict), "public_report_shape", f"{field} must be an object.")
    if allow_subset:
        require(set(value).issubset(keys), "public_report_shape", f"{field} contains a disallowed key.")
    else:
        require(set(value) == keys, "public_report_shape", f"{field} must contain the exact count keys.")
    for key, count in value.items():
        require_nonnegative_integer(count, f"{field}.{key}")
    return value


def public_safety_record() -> dict[str, str]:
    return {
        "schema_validation": "passed",
        "path_allowlist": "passed",
        "forbidden_key_scan": "passed",
        "secret_and_path_scan": "passed",
        "result": "passed",
    }


def common_report_identities(frozen: dict[str, Any], reconnect: dict[str, Any] | None = None) -> dict[str, Any]:
    identities = {
        "source_sha256": frozen["identities"]["source_sha256"],
        "candidate_sha256": frozen["candidate_sha256"],
        "benchmark_version": frozen["benchmark"]["version"],
        "benchmark_sha256": frozen["benchmark"]["benchmark_sha256"],
        "benchmark_file_sha256": frozen["benchmark_file_sha256"],
        "benchmark_lock_sha256": frozen["benchmark_lock"]["lock_sha256"],
        "policy_sha256": frozen["policy"]["policy_sha256"],
        "policy_file_sha256": frozen["policy_file_sha256"],
        "page_map_sha256": frozen["page_map"]["page_map_sha256"],
        "page_map_file_sha256": frozen["page_map_file_sha256"],
        "chunk_manifest_sha256": frozen["chunk_manifest"]["chunk_manifest_sha256"],
        "chunk_manifest_file_sha256": frozen["chunk_manifest_file_sha256"],
        "normalized_candidate_file_sha256": frozen["candidate_file_sha256"],
        "item_inventory_file_sha256": frozen["inventory_file_sha256"],
    }
    if reconnect is not None:
        identities.update({
            "source_chunk_file_sha256": reconnect["source_chunk_file_sha256"],
            "source_sidecar_file_sha256": reconnect["source_sidecar_file_sha256"],
        })
    return identities


def build_locator_report(
    frozen: dict[str, Any], chunk_id: str, base_commit: str, reconnect: dict[str, Any],
    packet: dict[str, Any], result: dict[str, Any], audit_sha256: str,
) -> dict[str, Any]:
    identities = common_report_identities(frozen, reconnect)
    identities["locator_packet_file_sha256"] = packet["sha256"]
    record = frozen["chunks"][chunk_id]
    report = {
        "schema_version": LOCATOR_REPORT_VERSION,
        "report_sha256": "",
        "audit_kind": "locator_audit",
        "evaluation_id": frozen["state"]["evaluation_id"],
        "candidate_id": frozen["candidate_id"],
        "chunk_id": chunk_id,
        "source_unit_label": source_unit_label(record),
        "immutable_base_commit": base_commit,
        "identities": identities,
        "owned_document_page_ranges": record["owned_document_page_ranges"],
        "denominators": {
            "packet_assignments": len(packet["assignments"]),
            "judged_assignments": len(result["locator_ids"]),
            "unique_assignments": len(set(result["locator_ids"])),
        },
        "judgment_counts": result["judgment_counts"],
        "severity_counts": result["severity_counts"],
        "error_code_counts": result["error_code_counts"],
        "completion": {"status": "complete", "all_assignments_accounted": True, "foreign_assignments": 0, "duplicate_assignments": 0},
        "private_artifact_sha256": audit_sha256,
        "reconnection_status": {"source": "verified_by_sha256", "candidate": "verified_by_sha256", "source_chunk": "verified_by_sha256", "source_sidecar": "verified_by_sha256"},
        "limitations": [{"code": "uninspectable", "count": result["judgment_counts"].get("uninspectable", 0)}],
        "public_safety": public_safety_record(),
    }
    report["report_sha256"] = canonical_hash(report, "report_sha256")
    validate_public_report(report, "locator", chunk_id)
    return report


def build_missing_report(
    frozen: dict[str, Any], chunk_id: str, base_commit: str,
    workset: dict[str, Any], locator_set: dict[str, Any], result: dict[str, Any],
    artifact: dict[str, Any], audit_sha256: str,
) -> dict[str, Any]:
    identities = common_report_identities(frozen)
    identities["missing_access_ownership_sha256"] = workset["workset_sha256"]
    identities["locator_audit_set_sha256"] = locator_set["sha256"]
    treatment_recall: dict[str, dict[str, int]] = {}
    for locator_class in ("principal", "supporting", "synthesis_or_conclusion"):
        counts = result["treatment_recall_by_class"][locator_class]
        treatment_recall[locator_class] = {
            "expected": counts["expected"],
            "found": counts["found"],
            "missed": counts["missed"],
            "uninspectable": counts["uninspectable"],
        }
    record = frozen["chunks"][chunk_id]
    report = {
        "schema_version": MISSING_REPORT_VERSION,
        "report_sha256": "",
        "audit_kind": "missing_access",
        "evaluation_id": frozen["state"]["evaluation_id"],
        "candidate_id": frozen["candidate_id"],
        "chunk_id": chunk_id,
        "source_unit_label": source_unit_label(record),
        "immutable_base_commit": base_commit,
        "identities": identities,
        "owned_document_page_ranges": record["owned_document_page_ranges"],
        "subject_denominators": {"expected": len(workset["subject_ids"]), "judged": len(result["subject_ids"]), "unique": len(set(result["subject_ids"]))},
        "reader_task_denominators": {"expected": len(workset["reader_task_ids"]), "judged": len(result["reader_task_ids"]), "unique": len(set(result["reader_task_ids"]))},
        "treatment_denominators": {"expected": len(workset["treatment_ids"]), "judged": len(result["treatment_ids"]), "unique": len(set(result["treatment_ids"]))},
        "concept_coverage_counts": result["concept_coverage_counts"],
        "locator_recall": result["locator_recall"],
        "treatment_recall": treatment_recall,
        "access_route_counts": result["access_route_counts"],
        "reader_task_result_counts": result["reader_task_result_counts"],
        "severity_counts": result["severity_counts"],
        "error_code_counts": result["error_code_counts"],
        "dependency_defect_count": result["dependency_defect_count"],
        "completion": {"status": "complete", "subjects_complete": True, "reader_tasks_complete": True, "treatments_complete": True, "foreign_judgments": 0, "duplicate_judgments": 0},
        "private_artifact_sha256": audit_sha256,
        "reconnection_status": {"source": "identity_bound_through_frozen_benchmark", "candidate": "verified_by_sha256", "locator_audit_set": "verified_by_sha256"},
        "limitations": [
            {"code": "uninspectable_concept", "count": result["concept_coverage_counts"].get("uninspectable", 0)},
            {"code": "uninspectable_reader_task", "count": result["reader_task_result_counts"].get("uninspectable", 0)},
            {"code": "uninspectable_treatment", "count": result["treatment_recall"].get("uninspectable", 0)},
        ],
        "public_safety": public_safety_record(),
    }
    report["report_sha256"] = canonical_hash(report, "report_sha256")
    validate_public_report(report, "missing_access", chunk_id)
    return report


def validate_public_report(report: dict[str, Any], audit_kind: str | None = None, chunk_id: str | None = None) -> dict[str, Any]:
    serialized = report.get("audit_kind")
    inferred = "locator" if serialized == "locator_audit" else "missing_access" if serialized == "missing_access" else None
    require(inferred is not None and (audit_kind is None or inferred == audit_kind), "public_report_kind", "Public report audit kind is invalid.")
    expected = LOCATOR_REPORT_REQUIRED if inferred == "locator" else MISSING_REPORT_REQUIRED
    exact_keys(report, expected, "Public worker report")
    require(report["schema_version"] == report_version(inferred), "public_report_schema", "Public report schema version is invalid.")
    validate_self_hash(report, "report_sha256", "Public worker report")
    for field in ("evaluation_id", "candidate_id"):
        require(isinstance(report.get(field), str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", report[field])), "public_report_identity", f"Public report {field} is not a bounded public-safe identifier.")
    actual_chunk = validate_chunk_id(report["chunk_id"])
    require(chunk_id is None or actual_chunk == chunk_id, "public_report_chunk", "Public report names a different chunk.")
    require_commit(report["immutable_base_commit"], "public_report.immutable_base_commit")
    require_nonempty_string(report.get("source_unit_label"), "public_report.source_unit_label", 256)
    flatten_ranges(report["owned_document_page_ranges"], "public_report.owned_document_page_ranges")
    identity_fields = {
        "source_sha256", "candidate_sha256", "benchmark_version", "benchmark_sha256",
        "benchmark_file_sha256", "benchmark_lock_sha256", "policy_sha256", "policy_file_sha256",
        "page_map_sha256", "page_map_file_sha256", "chunk_manifest_sha256", "chunk_manifest_file_sha256",
        "normalized_candidate_file_sha256", "item_inventory_file_sha256",
    }
    if inferred == "locator":
        identity_fields.update({"source_chunk_file_sha256", "source_sidecar_file_sha256"})
    identity_fields.add("locator_packet_file_sha256" if inferred == "locator" else "missing_access_ownership_sha256")
    if inferred == "missing_access":
        identity_fields.add("locator_audit_set_sha256")
    require(set(report["identities"]) == identity_fields, "public_report_identity", "Public report identities do not match the deterministic allowlist.")
    for field in report["identities"]:
        if field == "benchmark_version":
            require(isinstance(report["identities"][field], int) and report["identities"][field] > 0, "public_report_identity", "benchmark_version must be positive.")
        else:
            require_sha256(report["identities"][field], f"public_report.identities.{field}")
    require_sha256(report["private_artifact_sha256"], "public_report.private_artifact_sha256")
    if inferred == "locator":
        validate_count_map(report["judgment_counts"], LOCATOR_STATUSES, "judgment_counts")
        validate_count_map(report["severity_counts"], SEVERITIES, "severity_counts")
        validate_count_map(report["error_code_counts"], LOCATOR_ERROR_CODES, "error_code_counts", allow_subset=True)
        denominators = report["denominators"]
        validate_count_map(denominators, {"packet_assignments", "judged_assignments", "unique_assignments"}, "denominators")
        require(denominators.get("packet_assignments") == denominators.get("judged_assignments") == denominators.get("unique_assignments"), "public_report_denominator", "Locator public denominators differ.")
        judged = denominators["judged_assignments"]
        require(sum(report["judgment_counts"].values()) == judged and sum(report["severity_counts"].values()) == judged, "public_report_denominator", "Locator aggregate status/severity counts do not equal the judged denominator.")
        require(report["completion"] == {"status": "complete", "all_assignments_accounted": True, "foreign_assignments": 0, "duplicate_assignments": 0}, "public_report_completion", "Locator public completion gate is not exact.")
        require(report["reconnection_status"] == {"source": "verified_by_sha256", "candidate": "verified_by_sha256", "source_chunk": "verified_by_sha256", "source_sidecar": "verified_by_sha256"}, "public_report_reconnection", "Locator public reconnection gate is not exact.")
    else:
        validate_count_map(report["concept_coverage_counts"], COVERAGE_STATUSES, "concept_coverage_counts")
        validate_count_map(report["access_route_counts"], {"direct_only", "cross_reference_only", "both", "none", "uninspectable"}, "access_route_counts")
        validate_count_map(report["reader_task_result_counts"], TASK_STATUSES, "reader_task_result_counts")
        validate_count_map(report["severity_counts"], SEVERITIES, "severity_counts")
        validate_count_map(report["error_code_counts"], {"SCP", "COV", "SEL", "CON", "STA", "LOC_POS", "LOC_NEG", "CMP", "HED", "SUB", "XRF", "DEN", "MEC"}, "error_code_counts", allow_subset=True)
        for field in ("subject_denominators", "reader_task_denominators", "treatment_denominators"):
            denominator = report[field]
            validate_count_map(denominator, {"expected", "judged", "unique"}, field)
            require(denominator.get("expected") == denominator.get("judged") == denominator.get("unique"), "public_report_denominator", f"{field} differs.")
        subject_count = report["subject_denominators"]["judged"]
        task_count = report["reader_task_denominators"]["judged"]
        treatment_count = report["treatment_denominators"]["judged"]
        require(sum(report["concept_coverage_counts"].values()) == subject_count and sum(report["access_route_counts"].values()) == subject_count, "public_report_denominator", "Missing-access concept/access aggregates do not equal the subject denominator.")
        require(sum(report["reader_task_result_counts"].values()) == task_count, "public_report_denominator", "Reader-task aggregate counts do not equal the task denominator.")
        require(sum(report["severity_counts"].values()) == subject_count + task_count, "public_report_denominator", "Missing-access severity counts do not equal subject plus task judgments.")
        locator_recall = validate_count_map(report["locator_recall"], {"expected", "found", "missed"}, "locator_recall")
        require(locator_recall["expected"] == locator_recall["found"] + locator_recall["missed"], "public_report_denominator", "Locator recall does not partition exactly.")
        require(set(report["treatment_recall"]) == {"principal", "supporting", "synthesis_or_conclusion"}, "public_report_denominator", "Treatment recall must preserve all three classes.")
        for locator_class, counts in report["treatment_recall"].items():
            validate_count_map(counts, {"expected", "found", "missed", "uninspectable"}, f"treatment_recall.{locator_class}")
            require(counts["expected"] == counts["found"] + counts["missed"] + counts["uninspectable"], "public_report_denominator", f"Treatment recall {locator_class} does not partition exactly.")
        require(sum(counts["expected"] for counts in report["treatment_recall"].values()) == treatment_count, "public_report_denominator", "Treatment-class denominators do not equal the exact treatment denominator.")
        require_nonnegative_integer(report["dependency_defect_count"], "dependency_defect_count")
        require(report["completion"] == {"status": "complete", "subjects_complete": True, "reader_tasks_complete": True, "treatments_complete": True, "foreign_judgments": 0, "duplicate_judgments": 0}, "public_report_completion", "Missing-access public completion gate is not exact.")
        require(report["reconnection_status"] == {"source": "identity_bound_through_frozen_benchmark", "candidate": "verified_by_sha256", "locator_audit_set": "verified_by_sha256"}, "public_report_reconnection", "Missing-access benchmark-first input gate is not exact.")
    require(report["public_safety"] == public_safety_record(), "public_safety_record", "Public report safety record is not complete.")
    limitations = report["limitations"]
    require(isinstance(limitations, list), "public_report_shape", "Public report limitations must be an array.")
    for index, limitation in enumerate(limitations):
        require(isinstance(limitation, dict) and set(limitation) == {"code", "count"}, "public_report_shape", f"limitations[{index}] must contain aggregate code and count only.")
        require_nonempty_string(limitation["code"], f"limitations[{index}].code", 64)
        require_nonnegative_integer(limitation["count"], f"limitations[{index}].count")
    public_scan(report)
    return {"audit_kind": inferred, "chunk_id": actual_chunk, "report_sha256": report["report_sha256"]}


def recovery_identity_subset(identities: dict[str, Any], audit_kind: str) -> dict[str, Any]:
    fields = {
        "source_sha256", "candidate_sha256", "benchmark_sha256", "benchmark_lock_sha256",
        "policy_sha256", "page_map_sha256", "chunk_manifest_sha256",
        "normalized_candidate_file_sha256", "item_inventory_file_sha256",
    }
    fields.add("locator_packet_file_sha256" if audit_kind == "locator" else "missing_access_ownership_sha256")
    if audit_kind == "missing_access":
        fields.add("locator_audit_set_sha256")
    return {field: identities[field] for field in sorted(fields)}


def build_recovery(
    recovery_root: Path,
    recovery_zip: Path,
    audit_kind: str,
    frozen: dict[str, Any],
    chunk_id: str,
    identities: dict[str, Any],
    audit_name: str,
    audit_payload: bytes,
    public_payload: bytes,
    ownership: dict[str, Any],
) -> dict[str, Any]:
    require(not recovery_root.exists() or not any(recovery_root.iterdir()), "recovery_root_not_isolated", "Worker recovery root must be unique and empty.")
    require(not recovery_zip.exists(), "output_exists", f"Refusing to overwrite {recovery_zip}.")
    require_no_symlink_components(recovery_root.parent, "Worker recovery parent")
    require_no_symlink_components(recovery_zip.parent, "Worker recovery archive parent")
    recovery_root.mkdir(parents=True, exist_ok=True)
    publication_profile = frozen.get("publication_profile", publication_profile_for(frozen["state"]))
    public_path = public_path_for(audit_kind, chunk_id, publication_profile)
    checkpoint_ref = stable_identifier("CAR", {"evaluation_id": frozen["state"]["evaluation_id"], "candidate_id": frozen["candidate_id"], "chunk_id": chunk_id, "audit_kind": audit_kind, "identities": identities})
    worker_state = {
        "schema_version": "candidate-audit-worker-state-v1",
        "audit_kind": serialized_audit_kind(audit_kind),
        "evaluation_id": frozen["state"]["evaluation_id"],
        "candidate_id": frozen["candidate_id"],
        "chunk_id": chunk_id,
        "status": "complete_private_work_preserved",
        "checkpoint_ref": checkpoint_ref,
        "canonical_state_updated": False,
        "benchmark_repository_modified": False,
    }
    ownership_name = "locator-assignment-plan.json" if audit_kind == "locator" else "missing-access-ownership-plan.json"
    member_payloads = {
        audit_name: audit_payload,
        "worker-state.json": json_bytes(worker_state),
        ownership_name: json_bytes(ownership),
        public_path: public_payload,
    }
    worker_manifest = {
        "schema_version": "candidate-audit-worker-manifest-v1",
        "evaluation_id": frozen["state"]["evaluation_id"],
        "candidate_id": frozen["candidate_id"],
        "chunk_id": chunk_id,
        "artifacts": [
            {"path": name, "sha256": sha256_bytes(payload), "byte_length": len(payload)}
            for name, payload in sorted(member_payloads.items())
        ],
        "canonical_manifests_updated": False,
    }
    member_payloads["worker-manifest.json"] = json_bytes(worker_manifest)
    artifact_types = {
        audit_name: ("private_audit", "private"),
        "worker-state.json": ("worker_state", "private"),
        "worker-manifest.json": ("worker_manifest", "private"),
        ownership_name: ("ownership_plan", "private"),
        public_path: (
            "public_canonical_audit" if publication_profile == PUBLIC_EVALUATION_ARTIFACTS else "public_report",
            "public",
        ),
    }
    metadata = {
        "schema_version": RECOVERY_VERSION,
        "recovery_metadata_sha256": "",
        "audit_kind": serialized_audit_kind(audit_kind),
        "evaluation_id": frozen["state"]["evaluation_id"],
        "candidate_id": frozen["candidate_id"],
        "chunk_id": chunk_id,
        "identities": recovery_identity_subset(identities, audit_kind),
        "checkpoint_ref": checkpoint_ref,
        "artifacts": [
            {
                "artifact": artifact_types[name][0],
                "path": name,
                "sha256": sha256_bytes(payload),
                "byte_length": len(payload),
                "visibility": artifact_types[name][1],
            }
            for name, payload in sorted(member_payloads.items())
        ],
        "excluded": ["source PDF bytes", "candidate PDF bytes", "raw extraction", "absolute local paths", "Library identifiers", "credentials", "secrets"],
    }
    metadata["recovery_metadata_sha256"] = canonical_hash(metadata, "recovery_metadata_sha256")
    member_payloads["recovery-metadata.json"] = json_bytes(metadata)
    for name, payload in member_payloads.items():
        target = recovery_root.joinpath(*PurePosixPath(name).parts)
        require_safe_output_path(target, recovery_root, "Worker recovery artifact")
        replace_bytes_atomic(target, payload)
    write_zip_atomic(recovery_zip, member_payloads)
    return {
        "metadata": metadata,
        "metadata_sha256": metadata["recovery_metadata_sha256"],
        "checkpoint_ref": checkpoint_ref,
        "archive_sha256": sha256_file(recovery_zip),
        "archive_byte_length": recovery_zip.stat().st_size,
        "archive_path": recovery_zip,
    }


def validate_recovery_archive(
    root: Path, archive: Path, receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require(root.is_dir(), "recovery_root_missing", f"Private recovery root does not exist: {root}")
    require(archive.is_file(), "recovery_archive_missing", f"Private recovery archive does not exist: {archive}")
    archive_size = archive.stat().st_size
    require(archive_size <= MAX_RECOVERY_ARCHIVE_BYTES, "recovery_archive_too_large", "Worker recovery archive exceeds the safety limit.")
    members: dict[str, bytes] = {}
    total = 0
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            require(bool(infos) and not duplicate_values(info.filename for info in infos), "recovery_archive_shape", "Recovery archive is empty or repeats member names.")
            for info in infos:
                name = safe_relative_path(info.filename)
                require(not name.endswith("/"), "recovery_archive_shape", "Recovery archive cannot contain directory entries.")
                mode = (info.external_attr >> 16) & 0o170000
                require(mode in {0, stat.S_IFREG}, "recovery_archive_member_type", f"Recovery archive member is not a regular file: {name}")
                require(info.file_size <= MAX_RECOVERY_MEMBER_BYTES, "recovery_member_too_large", f"Recovery member is too large: {name}")
                ratio = info.file_size / max(info.compress_size, 1)
                require(ratio <= MAX_RECOVERY_COMPRESSION_RATIO, "recovery_compression_ratio", f"Recovery member has an unsafe compression ratio: {name}")
                total += info.file_size
                require(total <= MAX_RECOVERY_TOTAL_BYTES, "recovery_total_too_large", "Recovery members exceed the uncompressed safety limit.")
                members[name] = bundle.read(info)
    except zipfile.BadZipFile as exc:
        raise PreparationError("recovery_archive_invalid", "Worker recovery archive is not a valid ZIP.") from exc
    require("recovery-metadata.json" in members, "recovery_metadata_missing", "Recovery archive lacks recovery-metadata.json.")
    try:
        metadata = json.loads(members["recovery-metadata.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreparationError("recovery_metadata_invalid", "Recovery metadata is not valid UTF-8 JSON.") from exc
    require(isinstance(metadata, dict) and metadata.get("schema_version") == RECOVERY_VERSION, "recovery_metadata_schema", f"Expected {RECOVERY_VERSION}.")
    validate_self_hash(metadata, "recovery_metadata_sha256", "Worker recovery metadata")
    expected_names = {"recovery-metadata.json"}
    for record in metadata.get("artifacts", []):
        require(isinstance(record, dict), "recovery_metadata_shape", "Recovery artifact entries must be objects.")
        name = safe_relative_path(str(record.get("path", "")))
        expected_names.add(name)
        require(name in members, "recovery_member_missing", f"Recovery archive lacks recorded member {name}.")
        require(record.get("sha256") == sha256_bytes(members[name]) and record.get("byte_length") == len(members[name]), "recovery_member_mismatch", f"Recovery member differs from metadata: {name}")
        root_path = root.joinpath(*PurePosixPath(name).parts)
        require(root_path.is_file() and sha256_file(root_path) == record["sha256"], "recovery_root_incomplete", f"Recovery root does not contain exact member {name}.")
    require(set(members) == expected_names, "recovery_archive_extra_member", "Recovery archive contains an unrecorded member.")
    if receipt is not None:
        require(receipt["private_recovery"]["sha256"] == sha256_file(archive), "recovery_archive_hash_mismatch", "Receipt recovery archive hash differs.")
        require(receipt["private_recovery"]["metadata_sha256"] == metadata["recovery_metadata_sha256"], "recovery_metadata_hash_mismatch", "Receipt recovery metadata hash differs.")
        require(receipt["private_recovery"]["checkpoint_ref"] == metadata["checkpoint_ref"], "recovery_checkpoint_mismatch", "Receipt recovery checkpoint differs.")
    return {"metadata": metadata, "members": members, "archive_sha256": sha256_file(archive)}


def receipt_source_reconnection(audit_kind: str) -> dict[str, Any]:
    if audit_kind == "locator":
        return {"status": "verified", "source_sha256_verified": True, "source_chunk_verified": True, "source_sidecar_verified": True, "candidate_sha256_verified": True}
    return {
        "status": "not_required_benchmark_first",
        "source_identity_bound": True,
        "source_bytes_inspected": False,
        "source_chunk_required": False,
        "source_sidecar_required": False,
        "candidate_sha256_verified": True,
    }


def validation_gates(audit_kind: str) -> dict[str, Any]:
    common = {"identity_gate": "passed", "denominator_gate": "passed", "private_artifact_gate": "passed", "recovery_gate": "passed", "public_safety_gate": "passed", "complete": True}
    if audit_kind == "locator":
        return {**common, "packet_exact_set": "passed", "complete_path_gate": "passed", "owned_page_gate": "passed"}
    return {**common, "locator_stage_gate": "passed", "locator_set_gate": "passed", "ownership_gate": "passed", "subject_exact_set": "passed", "reader_task_exact_set": "passed", "treatment_exact_set": "passed"}


def make_receipt(
    audit_kind: str, frozen: dict[str, Any], chunk_id: str, project: str, base_branch: str,
    base_commit: str, worker_branch: str, identities: dict[str, Any], audit_name: str,
    audit_payload: bytes, result: dict[str, Any], recovery: dict[str, Any],
    recovery_root_ref: str, public_payload: bytes,
) -> dict[str, Any]:
    prefix = "LAW" if audit_kind == "locator" else "MAW"
    chunk = frozen["chunks"][chunk_id]
    publication_profile = frozen.get("publication_profile", publication_profile_for(frozen["state"]))
    public_path = public_path_for(audit_kind, chunk_id, publication_profile)
    private_artifact: dict[str, Any] = {
        "path": audit_name,
        "sha256": sha256_bytes(audit_payload),
        "byte_length": len(audit_payload),
        "schema_version": LOCATOR_AUDIT_VERSION if audit_kind == "locator" else MISSING_AUDIT_VERSION,
    }
    if audit_kind == "locator":
        private_artifact.update({"expected_count": result["completion"]["expected"], "judged_count": result["completion"]["judged"]})
    else:
        private_artifact.update({
            "expected_subject_count": result["completion"]["subjects"]["expected"],
            "judged_subject_count": result["completion"]["subjects"]["judged"],
            "expected_reader_task_count": result["completion"]["reader_tasks"]["expected"],
            "judged_reader_task_count": result["completion"]["reader_tasks"]["judged"],
            "expected_treatment_count": result["completion"]["treatments"]["expected"],
            "judged_treatment_count": result["completion"]["treatments"]["judged"],
        })
    receipt = {
        "schema_version": receipt_version(audit_kind),
        "receipt_id": stable_identifier(prefix, {"evaluation_id": frozen["state"]["evaluation_id"], "candidate_id": frozen["candidate_id"], "chunk_id": chunk_id, "audit_kind": audit_kind, "base_commit": base_commit, "private_artifact_sha256": private_artifact["sha256"]}),
        "receipt_sha256": "",
        "created_at": now(),
        "status": "ready_for_pull_request",
        "audit_kind": serialized_audit_kind(audit_kind),
        "evaluation_id": frozen["state"]["evaluation_id"],
        "candidate_id": frozen["candidate_id"],
        "chunk": {"chunk_id": chunk_id, "source_unit_label": source_unit_label(chunk), "owned_document_page_ranges": chunk["owned_document_page_ranges"]},
        "repositories": {
            "candidate_project": project,
            "candidate_base_branch": base_branch,
            "immutable_worker_base_commit": base_commit,
            "worker_branch": worker_branch,
            "public_report_path": public_path,
        },
        "identities": identities,
        "source_reconnection": receipt_source_reconnection(audit_kind),
        "private_artifact": private_artifact,
        "private_recovery": {
            "root_ref": safe_relative_path(recovery_root_ref),
            "archive_path": safe_relative_path(recovery["archive_path"].name),
            "sha256": recovery["archive_sha256"],
            "byte_length": recovery["archive_byte_length"],
            "metadata_sha256": recovery["metadata_sha256"],
            "checkpoint_ref": recovery["checkpoint_ref"],
        },
        "public_projection": {"path": public_path, "sha256": sha256_bytes(public_payload), "outgoing_safety_scan": "passed"},
        "validation": validation_gates(audit_kind),
        "publication": {"status": "not_yet_published", "pull_request": None, "head_commit": None},
        "limitations": ["GitHub publication and pull-request creation are orchestrator operations."],
    }
    receipt["receipt_sha256"] = canonical_hash(receipt, "receipt_sha256")
    publication_profile = frozen.get("publication_profile", publication_profile_for(frozen["state"]))
    validate_receipt(receipt, audit_kind, publication_profile)
    return receipt


def validate_receipt(receipt: dict[str, Any], audit_kind: str | None = None, publication_profile: str | None = None) -> str:
    exact_keys(receipt, RECEIPT_REQUIRED, "Worker receipt")
    inferred = "locator" if receipt.get("audit_kind") == "locator_audit" else "missing_access" if receipt.get("audit_kind") == "missing_access" else None
    require(inferred is not None and (audit_kind is None or inferred == audit_kind), "receipt_kind", "Worker receipt audit kind is invalid.")
    require(receipt["schema_version"] == receipt_version(inferred), "receipt_schema", "Worker receipt schema version is invalid.")
    validate_self_hash(receipt, "receipt_sha256", "Worker receipt")
    require_timestamp(receipt["created_at"], "receipt.created_at")
    chunk_id = validate_chunk_id(receipt.get("chunk", {}).get("chunk_id"))
    expected_branch = branch_for(inferred, chunk_id)
    repositories = receipt.get("repositories", {})
    require_github_project(repositories.get("candidate_project"), "receipt.repositories.candidate_project")
    require(repositories.get("worker_branch") == expected_branch, "receipt_branch", "Worker receipt branch is not the deterministic chunk branch.")
    inferred_profile = publication_profile_from_path(inferred, chunk_id, repositories.get("public_report_path"))
    require(publication_profile is None or inferred_profile == publication_profile, "publication_profile_mismatch", "Worker receipt publication path differs from the frozen evaluation profile.")
    expected_public = public_path_for(inferred, chunk_id, inferred_profile)
    require_commit(repositories.get("immutable_worker_base_commit"), "receipt.repositories.immutable_worker_base_commit")
    require_sha256(receipt.get("private_artifact", {}).get("sha256"), "receipt.private_artifact.sha256")
    require_sha256(receipt.get("private_recovery", {}).get("sha256"), "receipt.private_recovery.sha256")
    require_sha256(receipt.get("public_projection", {}).get("sha256"), "receipt.public_projection.sha256")
    require(receipt["public_projection"].get("path") == expected_public, "receipt_public_path", "Receipt public projection path differs.")
    require(receipt.get("status") in {"ready_for_pull_request", "published_unmerged", "publication_blocked"}, "receipt_status", "Worker receipt status is invalid.")
    identity_fields = {
        "source_sha256", "candidate_sha256", "benchmark_version", "benchmark_sha256", "benchmark_file_sha256",
        "benchmark_lock_sha256", "policy_sha256", "policy_file_sha256", "page_map_sha256", "page_map_file_sha256",
        "chunk_manifest_sha256", "chunk_manifest_file_sha256", "normalized_candidate_file_sha256", "item_inventory_file_sha256",
    }
    if inferred == "locator":
        identity_fields.update({"source_chunk_file_sha256", "source_sidecar_file_sha256"})
    identity_fields.add("locator_packet_file_sha256" if inferred == "locator" else "missing_access_ownership_sha256")
    if inferred == "missing_access":
        identity_fields.add("locator_audit_set_sha256")
    require(set(receipt.get("identities", {})) == identity_fields, "receipt_identity", "Worker receipt identities do not match the exact parallel-worker allowlist.")
    for field, value in receipt["identities"].items():
        if field == "benchmark_version":
            require(isinstance(value, int) and value > 0, "receipt_identity", "Receipt benchmark version must be positive.")
        else:
            require_sha256(value, f"receipt.identities.{field}")
    require(receipt.get("source_reconnection") == receipt_source_reconnection(inferred), "receipt_reconnection", "Worker receipt source/candidate input gate is incomplete.")
    require(receipt.get("validation") == validation_gates(inferred), "receipt_validation", "Worker receipt validation gates differ from the strict profile.")
    return inferred


def canonical_publication_migration_path(frozen: dict[str, Any], audit_kind: str, chunk_id: str) -> Path:
    parent = canonical_candidate_parent(frozen)
    directory = parent / ("locator-audits" if audit_kind == "locator" else "missing-access-audits") / "provenance"
    stem = "locator-audit" if audit_kind == "locator" else "missing-access-audit"
    return directory / f"{stem}-publication-migration.{chunk_id}.json"


def validate_publication_migration(
    migration: dict[str, Any],
    audit_kind: str,
    chunk_id: str,
    frozen: dict[str, Any],
    receipt: dict[str, Any],
    canonical_audit_sha256: str,
    canonical_audit_byte_length: int,
) -> None:
    exact_keys(
        migration,
        {
            "schema_version", "migration_sha256", "evaluation_id", "candidate_id", "audit_kind", "chunk_id",
            "migrated_at", "transition", "legacy_receipt", "canonical_public_artifact", "normalization",
        },
        "Publication migration",
    )
    require(migration["schema_version"] == PUBLICATION_MIGRATION_VERSION, "publication_migration_schema", f"Expected {PUBLICATION_MIGRATION_VERSION}.")
    validate_self_hash(migration, "migration_sha256", "Publication migration")
    require_timestamp(migration["migrated_at"], "publication_migration.migrated_at")
    require(migration["evaluation_id"] == frozen["state"].get("evaluation_id"), "publication_migration_identity", "Publication migration evaluation identity differs.")
    require(migration["candidate_id"] == frozen["state"].get("candidate", {}).get("candidate_id"), "publication_migration_identity", "Publication migration candidate identity differs.")
    require(migration["audit_kind"] == serialized_audit_kind(audit_kind) and migration["chunk_id"] == chunk_id, "publication_migration_identity", "Publication migration kind or chunk differs.")
    require(migration["transition"] == {"from": AGGREGATE_ONLY, "to": PUBLIC_EVALUATION_ARTIFACTS}, "publication_migration_transition", "Publication migration must be aggregate_only to public_evaluation_artifacts.")

    legacy = exact_keys(migration["legacy_receipt"], {"receipt_sha256", "private_artifact_sha256", "public_report_sha256"}, "Publication migration legacy receipt")
    require(legacy["receipt_sha256"] == receipt["receipt_sha256"], "publication_migration_receipt", "Publication migration binds a different legacy receipt.")
    require(legacy["private_artifact_sha256"] == receipt["private_artifact"]["sha256"], "publication_migration_receipt", "Publication migration binds a different legacy private audit.")
    require(legacy["public_report_sha256"] == receipt["public_projection"]["sha256"], "publication_migration_receipt", "Publication migration binds a different legacy aggregate report.")

    public = exact_keys(migration["canonical_public_artifact"], {"repository_path", "sha256", "byte_length", "commit", "blob_sha"}, "Publication migration canonical public artifact")
    require(public["repository_path"] == public_path_for(audit_kind, chunk_id, PUBLIC_EVALUATION_ARTIFACTS), "publication_migration_path", "Publication migration names the wrong canonical public path.")
    require_sha256(public["sha256"], "publication_migration.canonical_public_artifact.sha256")
    require_commit(public["commit"], "publication_migration.canonical_public_artifact.commit")
    require_commit(public["blob_sha"], "publication_migration.canonical_public_artifact.blob_sha")
    require(public["sha256"] == canonical_audit_sha256 and public["byte_length"] == canonical_audit_byte_length, "publication_migration_public_binding", "Publication migration does not bind the canonical audit bytes.")

    normalization = exact_keys(migration["normalization"], {"method", "judgment_count", "semantic_fields_preserved", "legacy_artifact_retained_in_recovery"}, "Publication migration normalization")
    require(normalization["method"] == "strict_public_allowlist_v1", "publication_migration_normalization", "Publication migration normalization method differs.")
    require(isinstance(normalization["judgment_count"], int) and normalization["judgment_count"] >= 0, "publication_migration_normalization", "Publication migration judgment count is invalid.")
    require(normalization["semantic_fields_preserved"] is True and normalization["legacy_artifact_retained_in_recovery"] is True, "publication_migration_normalization", "Publication migration must preserve semantic fields and legacy recovery bytes.")


def command_build_worker(args: argparse.Namespace, audit_kind: str) -> None:
    project = require_github_project(args.project, "project")
    chunk_id = validate_chunk_id(args.chunk_id)
    worker_branch = args.branch or branch_for(audit_kind, chunk_id)
    require(worker_branch == branch_for(audit_kind, chunk_id), "worker_branch_invalid", "Parallel candidate-audit branches use the deterministic kind/chunk branch exactly.")
    repository_state = validate_repository_state(Path(args.repository_state), project, args.base_branch, worker_branch)
    frozen = load_frozen_inputs(args, audit_kind)
    require(chunk_id in frozen["chunks"], "unknown_chunk", f"Chunk {chunk_id} is absent from the frozen manifest.")
    audit, audit_payload, audit_sha256 = load_json_snapshot(Path(args.audit).resolve(), "Private candidate audit")
    if audit_kind == "locator":
        reconnect = validate_source_reconnection(args, frozen, chunk_id)
        packet = validate_locator_packet(Path(args.locator_packet).resolve(), frozen, chunk_id)
        compare_packet_to_candidate(packet, frozen)
        result = validate_locator_audit(audit, frozen, packet, chunk_id, parallel=True)
        identities = {**common_report_identities(frozen, reconnect), "locator_packet_file_sha256": packet["sha256"]}
        report = build_locator_report(frozen, chunk_id, repository_state["base_commit"], reconnect, packet, result, audit_sha256)
        ownership = {"schema_version": "locator-assignment-plan-v1", "chunk_id": chunk_id, "locator_packet_file_sha256": packet["sha256"], "assignment_ids": sorted(packet["assignments"]), "assignment_count": len(packet["assignments"])}
        audit_name = f"locator-audit.{chunk_id}.json"
    else:
        locator_set = load_locator_audit_set(args.locator_audit, frozen)
        worksets = build_missing_worksets(frozen)
        workset = worksets[chunk_id]
        require(audit.get("missing_access_ownership_sha256") == workset["workset_sha256"], "missing_access_ownership_mismatch", "Private missing-access audit is not bound to the deterministic workset.")
        result = validate_missing_access_audit(audit, frozen, workset, chunk_id, parallel=True, locator_audit_set_sha256=locator_set["sha256"])
        identities = {**common_report_identities(frozen), "missing_access_ownership_sha256": workset["workset_sha256"], "locator_audit_set_sha256": locator_set["sha256"]}
        report = build_missing_report(frozen, chunk_id, repository_state["base_commit"], workset, locator_set, result, audit, audit_sha256)
        ownership = {"schema_version": "missing-access-ownership-plan-v1", **workset, "locator_audit_set_sha256": locator_set["sha256"]}
        audit_name = f"missing-access-audit.{chunk_id}.json"
    publication_profile = frozen.get("publication_profile", publication_profile_for(frozen["state"]))
    if publication_profile == PUBLIC_EVALUATION_ARTIFACTS:
        validate_public_canonical_audit(audit, audit_kind, chunk_id)
        public_document = audit
        public_payload = audit_payload
    else:
        public_document = report
        public_payload = json_bytes(report)
    expected_public_path = public_path_for(audit_kind, chunk_id, publication_profile)
    public_output = Path(args.public_output).resolve()
    require(public_output.as_posix().endswith("/" + expected_public_path) or public_output.as_posix() == expected_public_path, "public_output_path", f"Public output must end in {expected_public_path}.")
    recovery_root = Path(args.recovery_root).resolve()
    recovery_zip = Path(args.recovery_zip).resolve() if args.recovery_zip else recovery_root / (("locator-audit-worker" if audit_kind == "locator" else "missing-access-worker") + "-recovery.zip")
    receipt_output = Path(args.receipt_output).resolve() if args.receipt_output else recovery_root / (("locator-audit-worker-receipt.json" if audit_kind == "locator" else "missing-access-worker-receipt.json"))
    require(len({public_output, recovery_zip, receipt_output}) == 3, "worker_output_collision", "Public report, private receipt, and recovery ZIP outputs must be distinct.")
    require(not path_is_within(public_output, recovery_root), "privacy_boundary_collision", "Public candidate-repository report must be outside the private worker recovery root.")
    require(path_is_within(recovery_zip, recovery_root) and path_is_within(receipt_output, recovery_root), "privacy_boundary_collision", "Private recovery ZIP and worker receipt must remain beneath the isolated recovery root.")
    for path, label in ((public_output, "Public report"), (receipt_output, "Worker receipt")):
        require(not path.exists(), "output_exists", f"Refusing to overwrite {label}: {path}")
        require_no_symlink_components(path.parent, f"{label} parent")
    recovery = build_recovery(recovery_root, recovery_zip, audit_kind, frozen, chunk_id, identities, audit_name, audit_payload, public_payload, ownership)
    receipt = make_receipt(
        audit_kind, frozen, chunk_id, project, args.base_branch, repository_state["base_commit"], worker_branch,
        identities, audit_name, audit_payload, result, recovery,
        f"workers/{'locator-audit' if audit_kind == 'locator' else 'missing-access-audit'}/{chunk_id}", public_payload,
    )
    write_public_artifact(public_output, public_document, public_payload, publication_profile)
    write_json_atomic(receipt_output, receipt)
    validate_recovery_archive(recovery_root, recovery_zip, receipt)
    emit({"ok": True, "operation": f"build-{audit_kind}-worker", "chunk_id": chunk_id, "branch": worker_branch, "base_commit": repository_state["base_commit"], "publication_profile": publication_profile, "public_artifact": str(public_output), "public_report": str(public_output), "receipt": str(receipt_output), "recovery_archive": str(recovery_zip), "publish_allowlist": [expected_public_path], "canonical_state_updated": False})


def evidence_sha256(value: dict[str, Any]) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def validate_publication_evidence(
    evidence: dict[str, Any], receipt: dict[str, Any], public_payload: bytes,
    merged: bool, prior_open: dict[str, Any] | None = None,
) -> dict[str, Any]:
    audit_kind = validate_receipt(receipt)
    required = {
        "schema_version", "evidence_source", "audit_kind", "candidate_project", "pull_request",
        "pull_request_url", "state", "merged", "base_branch", "observed_base_head_commit",
        "head_branch", "head_commit", "worker_base_commit", "merge_base_commit", "commit_count",
        "changed_files", "observed_at",
    }
    if merged:
        required.add("merge_commit")
    exact_keys(evidence, required, "GitHub publication evidence")
    expected_schema = MERGE_EVIDENCE_VERSION if merged else OPEN_EVIDENCE_VERSION
    require(evidence["schema_version"] == expected_schema, "publication_evidence_schema", f"Expected {expected_schema}.")
    # evidence_source is intentionally only a format discriminator. Authentication
    # belongs to the orchestrator that captures this direct GitHub API snapshot.
    require(evidence["evidence_source"] == "github_api", "publication_evidence_source", "GitHub evidence must have direct API shape.")
    repositories = receipt["repositories"]
    require(evidence["audit_kind"] == serialized_audit_kind(audit_kind), "publication_evidence_kind", "GitHub evidence audit kind differs from receipt.")
    require(evidence["candidate_project"] == repositories["candidate_project"], "publication_project_mismatch", "GitHub evidence names a different candidate project.")
    require(evidence["base_branch"] == repositories["candidate_base_branch"], "publication_base_mismatch", "GitHub evidence targets a different base branch.")
    require(evidence["head_branch"] == repositories["worker_branch"], "publication_branch_mismatch", "GitHub evidence names a different worker branch.")
    worker_base = repositories["immutable_worker_base_commit"]
    require(require_commit(evidence["worker_base_commit"], "publication_evidence.worker_base_commit") == worker_base, "publication_base_mismatch", "Worker base commit differs from receipt.")
    require(require_commit(evidence["merge_base_commit"], "publication_evidence.merge_base_commit") == worker_base, "publication_base_mismatch", "PR merge base differs from immutable worker base.")
    # The observed target head may advance as earlier explicit batches merge.
    # Worker ancestry remains frozen by worker_base_commit and merge_base_commit;
    # binding target-head equality here would make collision-safe batches impossible.
    require_commit(evidence["observed_base_head_commit"], "publication_evidence.observed_base_head_commit")
    require_commit(evidence["head_commit"], "publication_evidence.head_commit")
    if merged:
        require(evidence["state"] == "closed" and evidence["merged"] is True, "pull_request_not_merged", "Fresh evidence does not show a merged pull request.")
        require_commit(evidence["merge_commit"], "publication_evidence.merge_commit")
    else:
        require(evidence["state"] == "open" and evidence["merged"] is False, "pull_request_not_open", "Fresh evidence does not show an open, unmerged pull request.")
    require(evidence["commit_count"] == 1, "publication_commit_count", "Worker branch must contain exactly one commit.")
    pull_request = evidence["pull_request"]
    require(isinstance(pull_request, int) and not isinstance(pull_request, bool) and pull_request > 0, "publication_pr", "Pull-request number is invalid.")
    expected_url = f"https://github.com/{repositories['candidate_project']}/pull/{pull_request}"
    require(evidence["pull_request_url"] == expected_url, "publication_pr_url", "Pull-request URL does not match project and number.")
    changed = evidence["changed_files"]
    require(isinstance(changed, list) and len(changed) == 1 and isinstance(changed[0], dict) and set(changed[0]) == {"path", "blob_sha", "file_sha256"}, "publication_allowlist", "Worker PR must change exactly one regular report file.")
    file_record = changed[0]
    require(file_record["path"] == repositories["public_report_path"], "publication_allowlist", "Worker PR changes an unexpected public path.")
    public_file_sha = sha256_bytes(public_payload)
    require(file_record["file_sha256"] == public_file_sha == receipt["public_projection"]["sha256"], "publication_file_mismatch", "Published report bytes differ from receipt/public projection.")
    blob_sha = str(file_record["blob_sha"]).lower()
    require(bool(re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", blob_sha)), "publication_blob", "Published Git blob identity is invalid.")
    require(git_blob_sha_bytes(public_payload, blob_sha) == blob_sha, "publication_blob_mismatch", "Published Git blob does not match exact public report bytes.")
    observed_at = require_timestamp(evidence["observed_at"], "publication_evidence.observed_at")
    if prior_open is not None:
        require(evidence["pull_request"] == prior_open.get("pull_request") and evidence["head_commit"] == prior_open.get("head_commit"), "merge_evidence_identity", "Merged evidence does not identify the same PR/head commit.")
        require(evidence["changed_files"] == prior_open.get("changed_files"), "merge_evidence_identity", "Merged evidence changed the reviewed file identity.")
        require(observed_at >= require_timestamp(prior_open.get("observed_at"), "open_pr_evidence.observed_at"), "merge_evidence_chronology", "Merged evidence predates open-PR evidence.")
    return {"audit_kind": audit_kind, "chunk_id": receipt["chunk"]["chunk_id"], "evidence_sha256": evidence_sha256(evidence), "observed_at": observed_at}


def command_validate_public(args: argparse.Namespace) -> None:
    document, payload, file_sha = load_json_snapshot(Path(args.report).resolve(), "Public worker artifact")
    expected = args.audit_kind
    if expected is None:
        expected = "locator" if document.get("schema_version") in {LOCATOR_AUDIT_VERSION, LOCATOR_REPORT_VERSION} else "missing_access"
    chunk_id = args.chunk_id or document.get("chunk_id")
    chunk_id = validate_chunk_id(chunk_id)
    profile = args.publication_profile
    if profile is None and args.expected_path:
        profile = publication_profile_from_path(expected, chunk_id, safe_relative_path(args.expected_path))
    if profile is None:
        profile = PUBLIC_EVALUATION_ARTIFACTS if document.get("schema_version") in {LOCATOR_AUDIT_VERSION, MISSING_AUDIT_VERSION} else AGGREGATE_ONLY
    result = validate_public_artifact(document, expected, chunk_id, profile)
    if args.expected_path:
        require(safe_relative_path(args.expected_path) == public_path_for(expected, chunk_id, profile), "public_output_path", "Expected public path is not the exact allowlisted path.")
    emit({"ok": True, "operation": "validate-public", "publication_profile": profile, **result, "file_sha256": file_sha, "byte_length": len(payload)})


def command_validate_worker(args: argparse.Namespace) -> None:
    receipt_path = Path(args.receipt).resolve()
    public_path = Path(args.public_report).resolve()
    receipt, _, _ = load_json_snapshot(receipt_path, "Private worker receipt")
    audit_kind = validate_receipt(receipt, args.audit_kind)
    chunk_id = receipt["chunk"]["chunk_id"]
    profile = publication_profile_from_path(audit_kind, chunk_id, receipt["public_projection"]["path"])
    public_document, public_payload, public_sha = load_json_snapshot(public_path, "Public worker artifact")
    result = validate_public_artifact(public_document, audit_kind, chunk_id, profile)
    require(public_sha == receipt["public_projection"]["sha256"], "public_projection_hash_mismatch", "Public artifact file hash differs from receipt.")
    if profile == AGGREGATE_ONLY:
        require(public_document["private_artifact_sha256"] == receipt["private_artifact"]["sha256"], "private_public_binding_mismatch", "Public report is not bound to the receipt's private artifact.")
    else:
        require(public_sha == receipt["private_artifact"]["sha256"], "private_public_binding_mismatch", "Published canonical audit is not the exact validated audit bound by the receipt.")
    root = Path(args.recovery_root).resolve()
    archive = Path(args.recovery_zip).resolve() if args.recovery_zip else root / receipt["private_recovery"]["archive_path"]
    recovery = validate_recovery_archive(root, archive, receipt)
    metadata = recovery["metadata"]
    require(metadata["audit_kind"] == receipt["audit_kind"] and metadata["chunk_id"] == receipt["chunk"]["chunk_id"], "recovery_receipt_identity", "Recovery metadata differs from receipt.")
    private_records = [item for item in metadata["artifacts"] if item.get("artifact") == "private_audit"]
    require(len(private_records) == 1 and private_records[0]["sha256"] == receipt["private_artifact"]["sha256"], "recovery_private_artifact_mismatch", "Recovery archive is not bound to the exact private audit.")
    emit({"ok": True, "operation": "validate-worker", "audit_kind": audit_kind, "chunk_id": result["chunk_id"], "publication_profile": profile, "receipt_sha256": receipt["receipt_sha256"], "public_file_sha256": public_sha, "recovery_sha256": recovery["archive_sha256"]})


def command_bind_publication(args: argparse.Namespace) -> None:
    receipt_path = Path(args.receipt).resolve()
    report_path = Path(args.public_report).resolve()
    evidence_path = Path(args.publication_evidence).resolve()
    output = Path(args.output).resolve()
    require(not output.exists(), "output_exists", f"Refusing to overwrite {output}.")
    receipt, _, receipt_file_sha = load_json_snapshot(receipt_path, "Private worker receipt")
    audit_kind = validate_receipt(receipt)
    chunk_id = receipt["chunk"]["chunk_id"]
    profile = publication_profile_from_path(audit_kind, chunk_id, receipt["public_projection"]["path"])
    public_document, public_payload, public_file_sha = load_json_snapshot(report_path, "Public worker artifact")
    validate_public_artifact(public_document, audit_kind, chunk_id, profile)
    require(public_file_sha == receipt["public_projection"]["sha256"], "public_projection_hash_mismatch", "Public artifact differs from receipt.")
    evidence, _, evidence_file_sha = load_json_snapshot(evidence_path, "Current-attempt open-PR evidence")
    evidence_result = validate_publication_evidence(evidence, receipt, public_payload, merged=False)
    recovery_root = Path(args.recovery_root).resolve()
    recovery_zip = Path(args.recovery_zip).resolve() if args.recovery_zip else recovery_root / receipt["private_recovery"]["archive_path"]
    recovery = validate_recovery_archive(recovery_root, recovery_zip, receipt)
    if args.selection:
        selection = parse_selection(args.selection, receipt["repositories"]["candidate_project"], audit_kind)
        if selection["type"] == "branch":
            require(selection["branch"] == receipt["repositories"]["worker_branch"], "binding_selection", "Selected branch differs from receipt/evidence head branch.")
        else:
            require(selection["pull_request"] == evidence["pull_request"], "binding_selection", "Selected PR differs from evidence.")
    else:
        selection = {"type": "pull_request", "pull_request": evidence["pull_request"], "pull_request_url": evidence["pull_request_url"]}
    binding = {
        "schema_version": BINDING_VERSION,
        "audit_kind": receipt["audit_kind"],
        "candidate_project": receipt["repositories"]["candidate_project"],
        "selection": selection,
        "receipt": {"path": str(receipt_path), "sha256": receipt_file_sha},
        "recovery": {"root": str(recovery_root), "archive_path": str(recovery_zip), "archive_sha256": recovery["archive_sha256"]},
        "public_report": {"path": str(report_path), "sha256": public_file_sha},
        "open_pr_evidence": {"path": str(evidence_path), "sha256": evidence_file_sha},
    }
    write_json_atomic(output, binding)
    emit({"ok": True, "operation": "bind-publication", "binding": str(output), "audit_kind": audit_kind, "chunk_id": chunk_id, "publication_profile": profile, "pull_request": evidence["pull_request"], "receipt_sha256": receipt["receipt_sha256"], "open_evidence_sha256": evidence_result["evidence_sha256"], "recovery_root_explicit": True})


def resolve_bound_path(binding_path: Path, value: Any, field: str) -> Path:
    require(isinstance(value, str) and bool(value), "binding_path", f"{field} must explicitly identify one path.")
    candidate = Path(value)
    return candidate.resolve() if candidate.is_absolute() else (binding_path.parent / candidate).resolve()


def load_file_binding(binding_path: Path, record: Any, field: str) -> tuple[dict[str, Any], bytes, str, Path]:
    require(isinstance(record, dict) and set(record) == {"path", "sha256"}, "binding_shape", f"{field} must contain path and sha256 only.")
    path = resolve_bound_path(binding_path, record["path"], f"{field}.path")
    document, payload, digest = load_json_snapshot(path, field)
    require(digest == require_sha256(record["sha256"], f"{field}.sha256"), "binding_file_hash_mismatch", f"{field} bytes differ from explicit binding.")
    return document, payload, digest, path


def parse_selection(value: str, project: str, audit_kind: str) -> dict[str, Any]:
    match = re.fullmatch(r"https://github\.com/([^/]+/[^/]+)/pull/([1-9][0-9]*)", value)
    if match:
        require(match.group(1).casefold() == project.casefold(), "selection_project_mismatch", "Selected pull request belongs to a different project.")
        return {"type": "pull_request", "pull_request": int(match.group(2)), "pull_request_url": value}
    require(value.startswith(("locator-audit/" if audit_kind == "locator" else "missing-access-audit/")), "selection_invalid", "Selection must be an explicit PR URL or audit-kind worker branch.")
    return {"type": "branch", "branch": value}


def canonical_candidate_parent(frozen: dict[str, Any]) -> Path:
    normalized = frozen["state"].get("candidate", {}).get("normalized_path")
    require(isinstance(normalized, str), "candidate_state_shape", "State candidate.normalized_path is required.")
    return resolve_manifest_path(frozen["root"], normalized).parent


def canonical_worker_paths(frozen: dict[str, Any], audit_kind: str, chunk_id: str) -> dict[str, Path]:
    parent = canonical_candidate_parent(frozen)
    directory = parent / ("locator-audits" if audit_kind == "locator" else "missing-access-audits")
    stem = "locator-audit" if audit_kind == "locator" else "missing-access-audit"
    return {
        "audit": directory / f"{stem}.{chunk_id}.v1.json",
        "receipt": directory / "provenance" / f"{stem}-worker-receipt.{chunk_id}.json",
        "open_evidence": directory / "provenance" / f"{stem}-open-pr-evidence.{chunk_id}.json",
        "merge_evidence": directory / "provenance" / f"{stem}-merge-evidence.{chunk_id}.json",
        "public_report": directory / "provenance" / f"{stem}-public-report.{chunk_id}.json",
    }


def coordinator_identity_subset(frozen: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_sha256": frozen["identities"]["source_sha256"],
        "candidate_sha256": frozen["candidate_sha256"],
        "benchmark_sha256": frozen["benchmark"]["benchmark_sha256"],
        "benchmark_lock_sha256": frozen["benchmark_lock"]["lock_sha256"],
        "policy_sha256": frozen["policy"]["policy_sha256"],
        "page_map_sha256": frozen["page_map"]["page_map_sha256"],
        "chunk_manifest_sha256": frozen["chunk_manifest"]["chunk_manifest_sha256"],
        "normalized_candidate_file_sha256": frozen["candidate_file_sha256"],
        "item_inventory_file_sha256": frozen["inventory_file_sha256"],
    }


def load_packet_set(paths: list[str], frozen: dict[str, Any]) -> dict[str, Any]:
    require(bool(paths), "locator_packet_set_required", "Coordinator requires an explicit locator packet for every frozen chunk.")
    packets: dict[str, dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    locator_ids: list[str] = []
    for raw_path in paths:
        document = load_json(Path(raw_path), "Locator packet")
        chunk_id = validate_chunk_id(document.get("chunk_id"))
        require(chunk_id not in packets, "duplicate_locator_packet", f"Duplicate packet for {chunk_id}.")
        packet = validate_locator_packet(Path(raw_path).resolve(), frozen, chunk_id)
        compare_packet_to_candidate(packet, frozen)
        packets[chunk_id] = packet
        locator_ids.extend(packet["assignments"])
        records.append({"chunk_id": chunk_id, "file_sha256": packet["sha256"], "assignment_ids": sorted(packet["assignments"])})
    require(set(packets) == set(frozen["chunks"]), "locator_packet_set_incomplete", "Coordinator packet inputs do not cover every frozen chunk exactly once.")
    require(not duplicate_values(locator_ids), "duplicate_locator_assignment", "Locator packets repeat assignment IDs across chunks.")
    records.sort(key=lambda item: item["chunk_id"])
    return {"packets": packets, "sha256": sha256_bytes(json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")), "assignment_ids": sorted(locator_ids)}


def load_worker_binding(path: Path, selection: dict[str, Any], project: str, audit_kind: str, frozen: dict[str, Any], kind_inputs: dict[str, Any]) -> dict[str, Any]:
    path = path.resolve()
    binding = exact_keys(load_json(path, "Worker integration binding"), {"schema_version", "audit_kind", "candidate_project", "selection", "receipt", "recovery", "public_report", "open_pr_evidence"}, "Worker integration binding")
    require(binding["schema_version"] == BINDING_VERSION, "binding_schema", f"Expected {BINDING_VERSION}.")
    require(binding["audit_kind"] == serialized_audit_kind(audit_kind), "binding_kind", "Worker binding audit kind differs.")
    require(binding["candidate_project"] == project, "binding_project", "Worker binding names a different project.")
    require(binding["selection"] == selection, "binding_selection", "Explicit selection does not match the worker binding selection.")
    receipt, receipt_payload, receipt_file_sha, receipt_path = load_file_binding(path, binding["receipt"], "binding.receipt")
    publication_profile = frozen.get("publication_profile", publication_profile_for(frozen["state"]))
    validate_receipt(receipt, audit_kind, publication_profile)
    chunk_id = receipt["chunk"]["chunk_id"]
    if selection["type"] == "branch":
        require(selection["branch"] == receipt["repositories"]["worker_branch"], "binding_selection", "Selected branch is not the exact receipt worker branch.")
    report, report_payload, report_file_sha, report_path = load_file_binding(path, binding["public_report"], "binding.public_report")
    validate_public_artifact(report, audit_kind, chunk_id, publication_profile)
    require(report_file_sha == receipt["public_projection"]["sha256"], "binding_public_private_mismatch", "Bound public artifact does not match receipt.")
    if publication_profile == AGGREGATE_ONLY:
        require(report["private_artifact_sha256"] == receipt["private_artifact"]["sha256"], "binding_public_private_mismatch", "Bound aggregate report does not identify the private audit.")
    else:
        require(report_file_sha == receipt["private_artifact"]["sha256"], "binding_public_private_mismatch", "Bound public canonical audit is not byte-identical to the validated worker audit.")
    open_evidence, open_payload, open_file_sha, open_path = load_file_binding(path, binding["open_pr_evidence"], "binding.open_pr_evidence")
    open_result = validate_publication_evidence(open_evidence, receipt, report_payload, merged=False)
    if selection["type"] == "pull_request":
        require(selection["pull_request"] == open_evidence["pull_request"] and selection["pull_request_url"] == open_evidence["pull_request_url"], "binding_selection", "Selected pull request is not the exact publication evidence PR.")
    recovery_binding = binding["recovery"]
    require(isinstance(recovery_binding, dict) and set(recovery_binding) == {"root", "archive_path", "archive_sha256"}, "binding_shape", "Binding recovery must explicitly identify one root and archive.")
    recovery_root = resolve_bound_path(path, recovery_binding["root"], "binding.recovery.root")
    recovery_archive = resolve_bound_path(path, recovery_binding["archive_path"], "binding.recovery.archive_path")
    require(sha256_file(recovery_archive) == recovery_binding["archive_sha256"], "binding_recovery_hash", "Explicit recovery archive differs from binding.")
    recovery = validate_recovery_archive(recovery_root, recovery_archive, receipt)
    metadata = recovery["metadata"]
    require(metadata.get("audit_kind") == receipt["audit_kind"] and metadata.get("evaluation_id") == receipt["evaluation_id"] and metadata.get("candidate_id") == receipt["candidate_id"] and metadata.get("chunk_id") == chunk_id, "recovery_receipt_identity", "Recovery metadata does not identify the exact receipt worker.")
    require(metadata.get("identities") == recovery_identity_subset(receipt["identities"], audit_kind), "recovery_receipt_identity", "Recovery metadata frozen identities differ from receipt.")
    private_records = [item for item in recovery["metadata"]["artifacts"] if item.get("artifact") == "private_audit"]
    require(len(private_records) == 1, "recovery_private_artifact_missing", "Recovery must contain exactly one private audit.")
    audit_record = private_records[0]
    audit_payload = recovery["members"][audit_record["path"]]
    require(sha256_bytes(audit_payload) == receipt["private_artifact"]["sha256"], "recovery_private_artifact_mismatch", "Recovered private audit differs from receipt.")
    try:
        audit = json.loads(audit_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreparationError("private_audit_invalid", "Recovered private audit is not valid UTF-8 JSON.") from exc
    require(isinstance(audit, dict), "private_audit_invalid", "Recovered private audit must be an object.")
    public_record_type = "public_canonical_audit" if publication_profile == PUBLIC_EVALUATION_ARTIFACTS else "public_report"
    public_records = [item for item in metadata["artifacts"] if item.get("artifact") == public_record_type]
    require(len(public_records) == 1, "recovery_public_report_missing", "Recovery must contain exactly one public artifact snapshot.")
    require(recovery["members"][public_records[0]["path"]] == report_payload, "recovery_public_report_mismatch", "Recovered public artifact differs from the explicitly bound bytes.")
    reconnect_identities = None
    if audit_kind == "locator":
        reconnect_identities = {"source_chunk_file_sha256": receipt["identities"]["source_chunk_file_sha256"], "source_sidecar_file_sha256": receipt["identities"]["source_sidecar_file_sha256"]}
    expected_common = common_report_identities(frozen, reconnect_identities)
    for field, expected in expected_common.items():
        require(receipt["identities"].get(field) == expected, "worker_frozen_identity_mismatch", f"Worker receipt differs from canonical identity {field}.")
    if audit_kind == "locator":
        packet = kind_inputs["packets"][chunk_id]
        require(receipt["identities"].get("locator_packet_file_sha256") == packet["sha256"], "locator_packet_hash_mismatch", "Worker receipt locator packet differs from coordinator packet.")
        result = validate_locator_audit(audit, frozen, packet, chunk_id, parallel=True)
        owned_ids = result["locator_ids"]
        expected_report = build_locator_report(
            frozen, chunk_id, receipt["repositories"]["immutable_worker_base_commit"],
            {"source_chunk_file_sha256": receipt["identities"]["source_chunk_file_sha256"], "source_sidecar_file_sha256": receipt["identities"]["source_sidecar_file_sha256"]},
            packet, result, sha256_bytes(audit_payload),
        )
    else:
        workset = kind_inputs["worksets"][chunk_id]
        require(receipt["identities"].get("missing_access_ownership_sha256") == workset["workset_sha256"], "missing_access_ownership_mismatch", "Worker receipt ownership plan differs.")
        require(receipt["identities"].get("locator_audit_set_sha256") == kind_inputs["locator_set"]["sha256"], "locator_audit_set_mismatch", "Worker receipt locator-audit dependency set differs.")
        require(audit.get("missing_access_ownership_sha256") == workset["workset_sha256"], "missing_access_ownership_mismatch", "Private audit ownership hash differs.")
        result = validate_missing_access_audit(audit, frozen, workset, chunk_id, parallel=True, locator_audit_set_sha256=kind_inputs["locator_set"]["sha256"])
        owned_ids = result["subject_ids"] + result["reader_task_ids"] + result["treatment_ids"]
        expected_report = build_missing_report(
            frozen, chunk_id, receipt["repositories"]["immutable_worker_base_commit"],
            workset, kind_inputs["locator_set"], result, audit, sha256_bytes(audit_payload),
        )
    if publication_profile == AGGREGATE_ONLY:
        require(json_bytes(expected_report) == report_payload, "public_projection_recompute_mismatch", "Bound public report is not the deterministic projection of the recovered private audit and frozen inputs.")
    else:
        require(audit_payload == report_payload, "public_projection_recompute_mismatch", "Bound public canonical audit is not byte-identical to the recovered validated audit.")
    canonical = canonical_worker_paths(frozen, audit_kind, chunk_id)
    existing = {name: output.is_file() for name, output in canonical.items()}
    if any(existing.values()):
        require(all(existing.values()), "incomplete_existing_integration", f"Canonical chunk {chunk_id} has incomplete provenance.")
        expected_payloads = {"audit": audit_payload, "receipt": receipt_payload, "open_evidence": open_payload, "public_report": report_payload}
        for name, payload in expected_payloads.items():
            require(sha256_file(canonical[name]) == sha256_bytes(payload), "conflicting_reintegration", f"Canonical chunk {chunk_id} conflicts at {name}.")
        disposition = "idempotent"
    else:
        disposition = "new"
    return {
        "binding_path": path, "binding": binding, "selection": selection, "chunk_id": chunk_id,
        "receipt": receipt, "receipt_payload": receipt_payload, "receipt_file_sha256": receipt_file_sha,
        "report": report, "report_payload": report_payload, "report_file_sha256": report_file_sha,
        "open_evidence": open_evidence, "open_payload": open_payload, "open_file_sha256": open_file_sha,
        "open_evidence_sha256": open_result["evidence_sha256"], "recovery": recovery,
        "audit": audit, "audit_payload": audit_payload, "result": result, "owned_ids": owned_ids,
        "canonical": canonical, "disposition": disposition,
    }


def preflight_batch(args: argparse.Namespace) -> dict[str, Any]:
    audit_kind = args.audit_kind
    project = require_github_project(args.project, "project")
    selections = args.selection or []
    binding_paths = args.worker_binding or []
    require(bool(selections) and len(selections) == len(binding_paths), "explicit_batch_required", "Provide one --selection and one --worker-binding for every selected worker.")
    frozen = load_frozen_inputs(args, audit_kind)
    if audit_kind == "locator":
        packet_set = load_packet_set(args.locator_packet or [], frozen)
        kind_inputs: dict[str, Any] = {**packet_set}
    else:
        locator_set = load_locator_audit_set(args.locator_audit or [], frozen)
        kind_inputs = {"locator_set": locator_set, "worksets": build_missing_worksets(frozen)}
    parsed = [parse_selection(value, project, audit_kind) for value in selections]
    require(not duplicate_values(json.dumps(item, sort_keys=True) for item in parsed), "duplicate_selection", "Selected batch repeats a PR or branch.")
    workers = [load_worker_binding(Path(path), selection, project, audit_kind, frozen, kind_inputs) for path, selection in zip(binding_paths, parsed)]
    chunk_ids = [item["chunk_id"] for item in workers]
    require(not duplicate_values(chunk_ids), "duplicate_chunk", "Selected batch contains more than one worker for a chunk.")
    page_sets = [set(flatten_ranges(frozen["chunks"][chunk_id]["owned_document_page_ranges"], f"{chunk_id}.owned_document_page_ranges")) for chunk_id in chunk_ids]
    for left in range(len(page_sets)):
        for right in range(left + 1, len(page_sets)):
            require(not page_sets[left].intersection(page_sets[right]), "overlapping_worker_ownership", "Selected workers overlap document-page ownership.")
    owned_ids = [owned for worker in workers for owned in worker["owned_ids"]]
    require(not duplicate_values(owned_ids), "duplicate_batch_judgment", "Selected workers duplicate owned judgments.")
    repositories = {(worker["receipt"]["repositories"]["candidate_base_branch"], worker["receipt"]["repositories"]["immutable_worker_base_commit"]) for worker in workers}
    require(len(repositories) == 1, "batch_base_mismatch", "Selected workers do not share one immutable candidate base.")
    return {"audit_kind": audit_kind, "project": project, "frozen": frozen, "kind_inputs": kind_inputs, "workers": workers, "chunk_ids": sorted(chunk_ids), "base_branch": next(iter(repositories))[0], "base_commit": next(iter(repositories))[1]}


def command_preflight_batch(args: argparse.Namespace) -> None:
    batch = preflight_batch(args)
    emit({"ok": True, "operation": "preflight-batch", "audit_kind": batch["audit_kind"], "candidate_project": batch["project"], "selected_chunk_ids": batch["chunk_ids"], "selected_workers": len(batch["workers"]), "new_workers": sum(item["disposition"] == "new" for item in batch["workers"]), "idempotent_workers": sum(item["disposition"] == "idempotent" for item in batch["workers"]), "transaction_ready": True, "merge_none_on_failure": True})


def artifact_record(path: Path, root: Path, stage: str, artifact_type: str, visibility: str, stamp: str) -> dict[str, Any]:
    relative = path.resolve().relative_to(root.resolve()).as_posix()
    digest = sha256_file(path)
    return {
        "artifact_id": artifact_id(relative, digest),
        "stage": stage,
        "artifact_type": artifact_type,
        "path": relative,
        "sha256": digest,
        "media_type": "application/json",
        "visibility": visibility,
        "retention": "required",
        "frozen": True,
        "recorded_at": stamp,
    }


def active_canonical_chunks(frozen: dict[str, Any], audit_kind: str) -> list[str]:
    active: list[str] = []
    publication_profile = frozen.get("publication_profile", publication_profile_for(frozen["state"]))
    for chunk_id in frozen["chunks"]:
        paths = canonical_worker_paths(frozen, audit_kind, chunk_id)
        present = {name: path.is_file() for name, path in paths.items()}
        if not any(present.values()):
            continue
        require(all(present.values()), "incomplete_existing_integration", f"Canonical chunk {chunk_id} lacks its complete audit/provenance set.", present)
        for path in paths.values():
            manifest_record_for_path(frozen, path)
        receipt = load_json(paths["receipt"], "Canonical worker receipt")
        receipt_profile = publication_profile_from_path(audit_kind, chunk_id, receipt.get("repositories", {}).get("public_report_path"))
        require(validate_receipt(receipt, audit_kind, receipt_profile) == audit_kind, "canonical_receipt_kind", f"Canonical receipt kind differs for {chunk_id}.")
        require(receipt["chunk"]["chunk_id"] == chunk_id, "canonical_receipt_chunk", f"Canonical receipt names a different chunk at {chunk_id}.")
        audit, audit_payload, audit_sha = load_json_snapshot(paths["audit"], "Canonical candidate audit")
        report, report_payload, report_file_sha = load_json_snapshot(paths["public_report"], "Canonical public worker report")
        validate_public_artifact(report, audit_kind, chunk_id, receipt_profile)
        if receipt_profile == publication_profile:
            require(receipt["private_artifact"]["sha256"] == audit_sha, "canonical_private_binding", f"Canonical audit binding differs for {chunk_id}.")
        else:
            require(receipt_profile == AGGREGATE_ONLY and publication_profile == PUBLIC_EVALUATION_ARTIFACTS, "publication_profile_mismatch", f"Canonical receipt publication path differs from the frozen evaluation profile for {chunk_id}.")
            migration_path = canonical_publication_migration_path(frozen, audit_kind, chunk_id)
            require(migration_path.is_file(), "publication_migration_missing", f"Canonical chunk {chunk_id} lacks its publication migration record.")
            manifest_record_for_path(frozen, migration_path)
            validate_public_artifact(audit, audit_kind, chunk_id, PUBLIC_EVALUATION_ARTIFACTS)
            migration = load_json(migration_path, "Publication migration")
            validate_publication_migration(migration, audit_kind, chunk_id, frozen, receipt, audit_sha, len(audit_payload))
            require(migration["normalization"]["judgment_count"] == len(audit.get("judgments", audit.get("subject_judgments", []))), "publication_migration_normalization", f"Publication migration judgment count differs for {chunk_id}.")
        if receipt_profile == AGGREGATE_ONLY:
            require(receipt["private_artifact"]["sha256"] == report["private_artifact_sha256"], "canonical_private_binding", f"Canonical legacy private audit binding differs for {chunk_id}.")
            if receipt_profile == publication_profile:
                require(audit_sha == report["private_artifact_sha256"], "canonical_private_binding", f"Canonical private audit binding differs for {chunk_id}.")
        else:
            require(audit_sha == report_file_sha, "canonical_private_binding", f"Canonical public audit snapshot differs for {chunk_id}.")
        require(receipt["public_projection"]["sha256"] == report_file_sha, "canonical_public_binding", f"Canonical public report binding differs for {chunk_id}.")
        open_evidence = load_json(paths["open_evidence"], "Canonical open-PR evidence")
        merge_evidence = load_json(paths["merge_evidence"], "Canonical merge evidence")
        validate_publication_evidence(open_evidence, receipt, report_payload, merged=False)
        validate_publication_evidence(merge_evidence, receipt, report_payload, merged=True, prior_open=open_evidence)
        active.append(chunk_id)
    return sorted(active)


def build_cumulative_checkpoint(output: Path, frozen: dict[str, Any]) -> dict[str, Any]:
    require(not output.exists(), "output_exists", f"Refusing to overwrite cumulative checkpoint {output}.")
    require_safe_output_path(output, frozen["root"], "Cumulative private checkpoint")
    state_payload = frozen["state_path"].read_bytes()
    manifest_payload = frozen["manifest_path"].read_bytes()
    members: dict[str, bytes] = {
        "evaluation-state.json": state_payload,
        "artifact-manifest.json": manifest_payload,
    }
    excluded: list[dict[str, str]] = []
    for record in frozen["manifest"].get("artifacts", []):
        if not isinstance(record, dict):
            continue
        relative = safe_relative_path(str(record.get("path", "")))
        source = resolve_manifest_path(frozen["root"], relative)
        suffix = source.suffix.casefold()
        if record.get("visibility") == "restricted" or suffix == ".pdf":
            excluded.append({"path": relative, "reason": "restricted_or_pdf"})
            continue
        if not source.is_file():
            excluded.append({"path": relative, "reason": "not_locally_accessible"})
            continue
        payload = source.read_bytes()
        require(record.get("sha256") == sha256_bytes(payload), "checkpoint_artifact_hash", f"Registered artifact changed before checkpoint: {relative}")
        members[f"artifacts/{relative}"] = payload
    metadata = {
        "schema_version": "candidate-audit-cumulative-checkpoint-v1",
        "evaluation_id": frozen["state"]["evaluation_id"],
        "state_sha256": sha256_bytes(state_payload),
        "manifest_sha256": sha256_bytes(manifest_payload),
        "members": [{"path": name, "sha256": sha256_bytes(payload), "byte_length": len(payload)} for name, payload in sorted(members.items())],
        "excluded": excluded,
        "restricted_pdfs_included": False,
    }
    members["checkpoint-metadata.json"] = json_bytes(metadata)
    write_zip_atomic(output, members)
    return {"path": output.resolve().relative_to(frozen["root"].resolve()).as_posix(), "sha256": sha256_file(output)}


def completion_accounting(frozen: dict[str, Any], audit_kind: str, kind_inputs: dict[str, Any]) -> dict[str, Any]:
    expected_chunks = sorted(frozen["chunks"])
    active = active_canonical_chunks(frozen, audit_kind)
    missing = sorted(set(expected_chunks) - set(active))
    if audit_kind == "locator":
        expected_ids = set(kind_inputs["assignment_ids"])
        accepted: list[str] = []
        for chunk_id in active:
            artifact = load_json(canonical_worker_paths(frozen, audit_kind, chunk_id)["audit"], "Canonical locator audit")
            packet = kind_inputs["packets"][chunk_id]
            result = validate_locator_audit(artifact, frozen, packet, chunk_id, parallel=True)
            accepted.extend(result["locator_ids"])
        require(not duplicate_values(accepted), "duplicate_locator_assignment", "Canonical locator audits duplicate assignments.")
        require(set(accepted).issubset(expected_ids), "foreign_chunk_assignment", "Canonical locator audits contain foreign assignments.")
        return {"expected_chunk_ids": expected_chunks, "active_chunk_ids": active, "missing_chunk_ids": missing, "complete": not missing and set(accepted) == expected_ids, "expected_assignments": len(expected_ids), "accepted_assignments": len(accepted)}
    expected_subjects = {subject for workset in kind_inputs["worksets"].values() for subject in workset["subject_ids"]}
    expected_tasks = {task for workset in kind_inputs["worksets"].values() for task in workset["reader_task_ids"]}
    expected_treatments = {treatment for workset in kind_inputs["worksets"].values() for treatment in workset["treatment_ids"]}
    subjects: list[str] = []
    tasks: list[str] = []
    treatments: list[str] = []
    for chunk_id in active:
        artifact = load_json(canonical_worker_paths(frozen, audit_kind, chunk_id)["audit"], "Canonical missing-access audit")
        result = validate_missing_access_audit(artifact, frozen, kind_inputs["worksets"][chunk_id], chunk_id, parallel=True, locator_audit_set_sha256=kind_inputs["locator_set"]["sha256"])
        subjects.extend(result["subject_ids"])
        tasks.extend(result["reader_task_ids"])
        treatments.extend(result["treatment_ids"])
    require(not duplicate_values(subjects + tasks + treatments), "duplicate_batch_judgment", "Canonical missing-access audits duplicate judgments.")
    require(set(subjects).issubset(expected_subjects) and set(tasks).issubset(expected_tasks) and set(treatments).issubset(expected_treatments), "foreign_batch_judgment", "Canonical missing-access audits contain foreign judgments.")
    complete = not missing and set(subjects) == expected_subjects and set(tasks) == expected_tasks and set(treatments) == expected_treatments
    return {"expected_chunk_ids": expected_chunks, "active_chunk_ids": active, "missing_chunk_ids": missing, "complete": complete, "expected_subjects": len(expected_subjects), "accepted_subjects": len(subjects), "expected_reader_tasks": len(expected_tasks), "accepted_reader_tasks": len(tasks), "expected_treatments": len(expected_treatments), "accepted_treatments": len(treatments)}


def integrate_batch(args: argparse.Namespace) -> dict[str, Any]:
    batch = preflight_batch(args)
    merge_paths = args.merge_evidence or []
    require(len(merge_paths) == len(batch["workers"]), "merge_evidence_count", "Provide one post-merge --merge-evidence for every selected worker.")
    merges_by_pr: dict[int, tuple[dict[str, Any], bytes, str]] = {}
    for raw_path in merge_paths:
        evidence, payload, digest = load_json_snapshot(Path(raw_path).resolve(), "Fresh merged-PR evidence")
        pr = evidence.get("pull_request")
        require(isinstance(pr, int) and pr not in merges_by_pr, "duplicate_merge_evidence", "Merged-PR evidence repeats a pull request.")
        merges_by_pr[pr] = (evidence, payload, digest)
    for worker in batch["workers"]:
        pr = worker["open_evidence"]["pull_request"]
        require(pr in merges_by_pr, "merge_evidence_missing", f"Missing merged-PR evidence for PR {pr}.")
        merge, merge_payload, merge_file_sha = merges_by_pr[pr]
        result = validate_publication_evidence(merge, worker["receipt"], worker["report_payload"], merged=True, prior_open=worker["open_evidence"])
        worker.update({"merge_evidence": merge, "merge_payload": merge_payload, "merge_file_sha256": merge_file_sha, "merge_evidence_sha256": result["evidence_sha256"]})

    state_path = batch["frozen"]["state_path"]
    with evaluation_integration_lock(state_path):
        # Re-run every read-only gate while holding the canonical mutation lock.
        batch = preflight_batch(args)
        for worker in batch["workers"]:
            pr = worker["open_evidence"]["pull_request"]
            merge, merge_payload, merge_file_sha = merges_by_pr[pr]
            result = validate_publication_evidence(merge, worker["receipt"], worker["report_payload"], merged=True, prior_open=worker["open_evidence"])
            worker.update({"merge_evidence": merge, "merge_payload": merge_payload, "merge_file_sha256": merge_file_sha, "merge_evidence_sha256": result["evidence_sha256"]})
        frozen = batch["frozen"]
        root = frozen["root"]
        original_state = frozen["state_bytes"]
        original_manifest = frozen["manifest_bytes"]
        state_before_sha = frozen["state_file_sha256"]
        manifest_before_sha = frozen["manifest_file_sha256"]
        previously_integrated = active_canonical_chunks(frozen, batch["audit_kind"])
        checkpoint_output = Path(args.checkpoint_output).resolve()
        require(not checkpoint_output.exists(), "output_exists", f"Refusing to overwrite {checkpoint_output}.")
        stamp = now()
        written: list[Path] = []
        manifest_replaced = False
        state_replaced = False
        try:
            for worker in batch["workers"]:
                if worker["disposition"] == "idempotent":
                    continue
                payloads = {
                    "audit": worker["audit_payload"],
                    "receipt": worker["receipt_payload"],
                    "open_evidence": worker["open_payload"],
                    "merge_evidence": worker["merge_payload"],
                    "public_report": worker["report_payload"],
                }
                for name, payload in payloads.items():
                    output = worker["canonical"][name]
                    require_safe_output_path(output, root, "Canonical candidate-audit artifact")
                    require(not output.exists(), "canonical_chunk_exists", f"Refusing to overwrite {output}.")
                    replace_bytes_atomic(output, payload)
                    written.append(output)
            manifest = deepcopy(frozen["manifest"])
            state = deepcopy(frozen["state"])
            all_idempotent = all(worker["disposition"] == "idempotent" for worker in batch["workers"])
            existing_paths = {item.get("path") for item in manifest.get("artifacts", []) if isinstance(item, dict)}
            for worker in batch["workers"]:
                for name, visibility, artifact_type in (
                    ("audit", "public" if frozen.get("publication_profile", publication_profile_for(frozen["state"])) == PUBLIC_EVALUATION_ARTIFACTS else "private", f"parallel_{batch['audit_kind']}_audit"),
                    ("receipt", "private", f"parallel_{batch['audit_kind']}_receipt"),
                    ("open_evidence", "private", "github_open_pr_evidence"),
                    ("merge_evidence", "private", "github_merge_evidence"),
                    ("public_report", "public", f"parallel_{batch['audit_kind']}_public_report"),
                ):
                    output = worker["canonical"][name]
                    relative = output.relative_to(root).as_posix()
                    if relative in existing_paths:
                        continue
                    record = artifact_record(output, root, audit_stage(batch["audit_kind"]), artifact_type, visibility, stamp)
                    manifest["artifacts"].append(record)
                    state["artifacts"].append(deepcopy(record))
                    existing_paths.add(relative)
            active_after = sorted(set(previously_integrated) | set(batch["chunk_ids"]))
            if all_idempotent:
                stage_status = state["stages"][audit_stage(batch["audit_kind"])]["status"]
                require(stage_status in {"in_progress", "completed"}, "idempotent_stage_mismatch", "Identical canonical chunks exist but the stage is not active/completed.")
            else:
                manifest["artifacts"] = sorted(manifest["artifacts"], key=lambda item: item["path"])
                state["artifacts"] = sorted(state["artifacts"], key=lambda item: item["path"])
                stage_status = "completed" if set(active_after) == set(frozen["chunks"]) else "in_progress"
                state["stages"][audit_stage(batch["audit_kind"])] = {"status": stage_status, "updated_at": stamp, "notes": [f"Coordinator-integrated {len(batch['workers'])} explicit parallel worker selection(s); {len(active_after)}/{len(frozen['chunks'])} chunks accepted."]}
                state["updated_at"] = stamp
                manifest["updated_at"] = stamp
                # Shared control ordering is an invariant: manifest first, state last.
                replace_bytes_atomic(frozen["manifest_path"], json_bytes(manifest))
                manifest_replaced = True
                replace_bytes_atomic(frozen["state_path"], json_bytes(state))
                state_replaced = True
            errors, _ = validate_state(state, state_path=frozen["state_path"], check_files=True, manifest_document=manifest)
            require(not errors, "canonical_validation_failed", "Integrated canonical evaluation failed validation.", errors)
            refreshed = {**frozen, **load_canonical_run(frozen["state_path"])}
            checkpoint = build_cumulative_checkpoint(checkpoint_output, refreshed)
            written.append(checkpoint_output)
            accounting = completion_accounting(refreshed, batch["audit_kind"], batch["kind_inputs"])
            require(accounting["complete"] == (stage_status == "completed"), "stage_completion_mismatch", "Stage status does not match exact full-chunk/denominator accounting.")
            manifest_after_sha = sha256_file(frozen["manifest_path"])
            state_after_sha = sha256_file(frozen["state_path"])
            if batch["audit_kind"] == "locator":
                identities = {**coordinator_identity_subset(frozen), "locator_packet_set_sha256": batch["kind_inputs"]["sha256"]}
                coverage = {"expected_chunk_ids": accounting["expected_chunk_ids"], "previously_integrated_chunk_ids": previously_integrated, "selected_chunk_ids": batch["chunk_ids"], "active_chunk_ids": accounting["active_chunk_ids"], "missing_chunk_ids": accounting["missing_chunk_ids"], "expected_assignments": accounting["expected_assignments"], "accepted_assignments": accounting["accepted_assignments"], "duplicate_assignments": 0, "foreign_assignments": 0}
                prefix = "LABI"
            else:
                ownership_records = [{"chunk_id": chunk, "sha256": workset["workset_sha256"]} for chunk, workset in sorted(batch["kind_inputs"]["worksets"].items())]
                ownership_sha = sha256_bytes(json.dumps(ownership_records, sort_keys=True, separators=(",", ":")).encode("utf-8"))
                identities = {**coordinator_identity_subset(frozen), "missing_access_ownership_sha256": ownership_sha, "locator_audit_set_sha256": batch["kind_inputs"]["locator_set"]["sha256"]}
                coverage = {"expected_chunk_ids": accounting["expected_chunk_ids"], "previously_integrated_chunk_ids": previously_integrated, "selected_chunk_ids": batch["chunk_ids"], "active_chunk_ids": accounting["active_chunk_ids"], "missing_chunk_ids": accounting["missing_chunk_ids"], "expected_subjects": accounting["expected_subjects"], "accepted_subjects": accounting["accepted_subjects"], "expected_reader_tasks": accounting["expected_reader_tasks"], "accepted_reader_tasks": accounting["accepted_reader_tasks"], "expected_treatments": accounting["expected_treatments"], "accepted_treatments": accounting["accepted_treatments"], "duplicate_judgments": 0, "foreign_judgments": 0}
                prefix = "MABI"
            selected_workers = []
            for worker in batch["workers"]:
                selected_workers.append({
                    "pull_request": worker["open_evidence"]["pull_request"], "pull_request_url": worker["open_evidence"]["pull_request_url"], "chunk_id": worker["chunk_id"],
                    "receipt_sha256": worker["receipt"]["receipt_sha256"], "recovery_sha256": worker["recovery"]["archive_sha256"], "public_report_sha256": worker["report_file_sha256"], "private_artifact_sha256": worker["receipt"]["private_artifact"]["sha256"],
                    "open_evidence_sha256": worker["open_evidence_sha256"], "merge_evidence_sha256": worker["merge_evidence_sha256"], "head_commit": worker["open_evidence"]["head_commit"], "merge_commit": worker["merge_evidence"]["merge_commit"], "canonical_path": worker["canonical"]["audit"].relative_to(root).as_posix(),
                })
            report = {
                "schema_version": integration_version(batch["audit_kind"]), "integration_id": stable_identifier(prefix, {"selected": [(item["chunk_id"], item["receipt_sha256"], item["merge_evidence_sha256"]) for item in selected_workers], "state_before": state_before_sha}), "integration_sha256": "", "audit_kind": serialized_audit_kind(batch["audit_kind"]),
                "status": "idempotent" if all_idempotent else "integrated_complete" if stage_status == "completed" else "integrated_partial", "integrated_at": stamp,
                "evaluation_id": frozen["state"]["evaluation_id"], "candidate_id": frozen["candidate_id"], "candidate_project": batch["project"], "base_branch": batch["base_branch"], "identities": identities, "selected_workers": selected_workers, "coverage": coverage,
                "transaction_order": ["validate_selected_batch", "verify_merged_pull_requests", "materialize_private_artifacts", "write_integration_provenance", "update_manifest", "update_state_last", "validate_canonical_evaluation", "create_cumulative_checkpoint", "commit_shared_control_once"],
                "manifest_before_sha256": manifest_before_sha, "manifest_after_sha256": manifest_after_sha, "state_before_sha256": state_before_sha, "state_after_sha256": state_after_sha, "stage_status": stage_status, "checkpoint": checkpoint, "benchmark_repository_modified": False,
            }
            report["integration_sha256"] = canonical_hash(report, "integration_sha256")
            report_output = Path(args.integration_report).resolve() if args.integration_report else root / "validation" / f"{batch['audit_kind'].replace('_', '-')}-batch-integration.{report['integration_id']}.json"
            require_safe_output_path(report_output, root, "Batch integration report")
            require(not report_output.exists(), "output_exists", f"Refusing to overwrite {report_output}.")
            write_json_atomic(report_output, report)
            written.append(report_output)
            return {"report": report, "report_path": report_output, "checkpoint_path": checkpoint_output}
        except Exception:
            if state_replaced:
                replace_bytes_atomic(frozen["state_path"], original_state)
            if manifest_replaced:
                replace_bytes_atomic(frozen["manifest_path"], original_manifest)
            for output in reversed(written):
                if output.is_file():
                    output.unlink()
            raise


def command_integrate_batch(args: argparse.Namespace) -> None:
    result = integrate_batch(args)
    report = result["report"]
    emit({"ok": True, "operation": "integrate-batch", "audit_kind": args.audit_kind, "status": report["status"], "stage_status": report["stage_status"], "selected_chunk_ids": report["coverage"]["selected_chunk_ids"], "missing_chunk_ids": report["coverage"]["missing_chunk_ids"], "integration_report": str(result["report_path"]), "checkpoint": str(result["checkpoint_path"]), "manifest_before_state": True, "shared_control_commit_required": True})


def command_completion(args: argparse.Namespace) -> None:
    args.allow_completed_boundary = True
    frozen = load_frozen_inputs(args, args.audit_kind)
    if args.audit_kind == "locator":
        kind_inputs = load_packet_set(args.locator_packet or [], frozen)
    else:
        kind_inputs = {"locator_set": load_locator_audit_set(args.locator_audit or [], frozen), "worksets": build_missing_worksets(frozen)}
    accounting = completion_accounting(frozen, args.audit_kind, kind_inputs)
    recorded = frozen["state"]["stages"][audit_stage(args.audit_kind)]["status"]
    require((recorded == "completed") == accounting["complete"], "stage_completion_mismatch", "Canonical stage status differs from exact completion accounting.")
    emit({"ok": True, "operation": "completion", "audit_kind": args.audit_kind, "recorded_stage_status": recorded, **accounting})


def add_frozen_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state", required=True, help="Canonical evaluation-state.json (v4).")
    parser.add_argument("--page-map", required=True, help="Frozen page-map-v1 JSON.")
    parser.add_argument("--chunk-manifest", required=True, help="Frozen chunk-manifest-v1 JSON.")
    parser.add_argument("--policy", required=True, help="Frozen subject-index-evaluation-policy-v2 JSON.")
    parser.add_argument("--benchmark", required=True, help="Frozen source-subject-benchmark-v2 JSON.")
    parser.add_argument("--benchmark-lock", required=True, help="Candidate benchmark-lock JSON.")
    parser.add_argument("--normalized-candidate", required=True, help="Integrated candidate-index-v2 JSON.")
    parser.add_argument("--item-inventory", required=True, help="Integrated item-inventory-v2 JSON.")


def add_reconnection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-file", required=True, help="Restricted complete source reconnected by SHA-256.")
    parser.add_argument("--source-chunk", required=True, help="Exact restricted source chunk.")
    parser.add_argument("--source-sidecar", required=True, help="Exact source-chunk page sidecar.")


def add_worker_arguments(parser: argparse.ArgumentParser, audit_kind: str) -> None:
    add_frozen_arguments(parser)
    if audit_kind == "locator":
        add_reconnection_arguments(parser)
    parser.add_argument("--chunk-id", required=True, help="One exact CHUNK-* identifier.")
    parser.add_argument("--audit", required=True, help="Model-authored canonical v1 private audit JSON.")
    parser.add_argument("--project", required=True, help="Exact public candidate GitHub owner/repository.")
    parser.add_argument("--repository-state", required=True, help="Fresh direct GitHub repository-state evidence JSON.")
    parser.add_argument("--base-branch", default="main", help="Expected candidate repository base branch (default: main).")
    parser.add_argument("--branch", help="Worker branch; if supplied it must equal the deterministic default.")
    parser.add_argument("--recovery-root", required=True, help="Unique empty private candidate/chunk recovery root.")
    parser.add_argument("--recovery-zip", help="Private recovery ZIP output (default: beneath recovery root).")
    parser.add_argument("--receipt-output", help="Private receipt output (default: beneath recovery root).")
    parser.add_argument("--public-output", required=True, help="Exact allowlisted aggregate report output in candidate repository checkout.")
    if audit_kind == "locator":
        parser.add_argument("--locator-packet", required=True, help="Exact locator-only packet for this chunk.")
    else:
        parser.add_argument("--locator-audit", action="append", required=True, help="Canonical locator audit; repeat once for every frozen chunk.")


def add_batch_arguments(parser: argparse.ArgumentParser) -> None:
    add_frozen_arguments(parser)
    parser.add_argument("--audit-kind", choices=sorted(AUDIT_KINDS), required=True)
    parser.add_argument("--project", required=True, help="Exact public candidate GitHub owner/repository.")
    parser.add_argument("--selection", action="append", required=True, help="Explicit selected PR URL or worker branch; repeat per worker.")
    parser.add_argument("--worker-binding", "--binding", dest="worker_binding", action="append", required=True, help="Explicit private receipt/recovery/public/evidence binding; repeat per worker.")
    parser.add_argument("--locator-packet", action="append", help="Locator packet; locator batches require exact coverage of every frozen chunk.")
    parser.add_argument("--locator-audit", action="append", help="Canonical locator audit; missing-access batches require exact coverage of every frozen chunk.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)

    locator = subparsers.add_parser("build-locator-worker", help="Validate one private locator audit and create its isolated recovery/receipt/public projection.")
    add_worker_arguments(locator, "locator")
    locator.set_defaults(handler=lambda args: command_build_worker(args, "locator"))

    missing = subparsers.add_parser("build-missing-access-worker", help="Validate one private missing-access audit after full canonical locator integration.")
    add_worker_arguments(missing, "missing_access")
    missing.set_defaults(handler=lambda args: command_build_worker(args, "missing_access"))

    public = subparsers.add_parser("validate-public", help="Validate the allowlisted public artifact selected by a publication profile.")
    public.add_argument("--report", required=True)
    public.add_argument("--audit-kind", choices=sorted(AUDIT_KINDS))
    public.add_argument("--chunk-id")
    public.add_argument("--publication-profile", choices=sorted(PUBLICATION_PROFILES))
    public.add_argument("--expected-path", help="Expected repository-relative allowlisted path.")
    public.set_defaults(handler=command_validate_public)

    worker = subparsers.add_parser("validate-worker", help="Validate one receipt, exact public report, and explicitly identified private recovery root/archive.")
    worker.add_argument("--receipt", required=True)
    worker.add_argument("--recovery-root", required=True)
    worker.add_argument("--recovery-zip")
    worker.add_argument("--public-report", required=True)
    worker.add_argument("--audit-kind", choices=sorted(AUDIT_KINDS))
    worker.set_defaults(handler=command_validate_worker)

    bind = subparsers.add_parser("bind-publication", help="Bind one explicit PR/branch selection to one receipt, recovery root, report, and current-attempt open-PR observation.")
    bind.add_argument("--receipt", required=True)
    bind.add_argument("--recovery-root", required=True)
    bind.add_argument("--recovery-zip")
    bind.add_argument("--public-report", required=True)
    bind.add_argument("--publication-evidence", required=True)
    bind.add_argument("--selection", help="Explicit PR URL or worker branch (default: PR URL in evidence).")
    bind.add_argument("--output", required=True, help="Private candidate-audit-integration-binding-v1 output.")
    bind.set_defaults(handler=command_bind_publication)

    preflight = subparsers.add_parser("preflight-batch", help="Transactionally validate an explicit selected batch without mutation or sweeping.")
    add_batch_arguments(preflight)
    preflight.set_defaults(handler=command_preflight_batch)

    integrate = subparsers.add_parser("integrate-batch", help="Integrate an already-preflighted explicit batch after current-attempt merged-PR evidence.")
    add_batch_arguments(integrate)
    integrate.add_argument("--merge-evidence", action="append", required=True, help="Fresh direct merged-PR evidence; repeat per selected worker.")
    integrate.add_argument("--checkpoint-output", required=True, help="New cumulative private checkpoint ZIP beneath evaluation root.")
    integrate.add_argument("--integration-report", help="Private batch integration report output beneath evaluation root.")
    integrate.set_defaults(handler=command_integrate_batch)

    completion = subparsers.add_parser("completion", help="Recompute exact partial/full canonical stage completion without mutation.")
    add_frozen_arguments(completion)
    completion.add_argument("--audit-kind", choices=sorted(AUDIT_KINDS), required=True)
    completion.add_argument("--locator-packet", action="append", help="Locator packet; locator completion requires every frozen chunk.")
    completion.add_argument("--locator-audit", action="append", help="Canonical locator audit; missing-access completion requires every frozen chunk.")
    completion.set_defaults(handler=command_completion)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.handler(args)
    except PreparationError as exc:
        payload: dict[str, Any] = {"ok": False, "error": {"code": exc.code, "message": exc.message}}
        if exc.details is not None:
            payload["error"]["details"] = exc.details
        emit(payload, 1)


if __name__ == "__main__":
    main()
