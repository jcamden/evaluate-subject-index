#!/usr/bin/env python3
"""Validate and register current candidate-audit chunks from parallel chats."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from candidate_preparation_cli import (
    PreparationError,
    artifact_id,
    load_json,
    load_json_snapshot,
    path_is_within,
    replace_bytes_atomic,
    require,
    require_safe_output_path,
    require_sha256,
    safe_relative_path,
    sha256_bytes,
    sha256_file,
    validate_self_hash,
)
from state_cli import (
    STAGES,
    evaluation_mutation_lock,
    save_state,
    validate_state,
)
from schema_validation import schema_errors


AUDIT_KINDS = {"locator", "missing_access"}
LOCATOR_STATUSES = {"supported", "partially_supported", "unsupported", "uninspectable"}
SEVERITIES = {"none", "cosmetic", "minor", "major", "critical"}
COVERAGE_STATUSES = {"complete", "partial", "missing", "uninspectable"}
TASK_STATUSES = {"succeeds", "partially_succeeds", "fails", "uninspectable"}
TREATMENT_RECALL_STATUSES = {"found", "missed", "uninspectable"}
PRIORITIES = {"essential", "major", "optional"}
LOCATOR_CLASS_RANK = {"principal": 0, "synthesis_or_conclusion": 1, "supporting": 2, "incidental": 3}
MISSING_ACCESS_EVIDENCE_MODE = "frozen_benchmark_and_canonical_locator_audits"
MISSING_ACCESS_SOURCE_ADJUDICATION_MODE = "exception_only"
MISSING_ACCESS_TREATMENT_IDENTITY_RULE = "unique_subject_document_page_locator_class"

def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def emit(payload: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(exit_code)


def require_nonempty_string(value: Any, field: str, maximum: int = 512) -> str:
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= maximum, "invalid_string", f"{field} must be a bounded nonempty string.")
    return value


def duplicate_values(values: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    duplicates: list[Any] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def stable_identifier(prefix: str, identity: Any) -> str:
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{prefix}-{sha256_bytes(encoded)[:12].upper()}"


def audit_stage(audit_kind: str) -> str:
    require(audit_kind in AUDIT_KINDS, "invalid_audit_kind", f"Unknown audit kind: {audit_kind}")
    return "locator_audit" if audit_kind == "locator" else "missing_access_audit"


def validate_chunk_id(value: Any) -> str:
    require(isinstance(value, str) and bool(re.fullmatch(r"CHUNK-[A-Za-z0-9._-]+", value)), "invalid_chunk_id", "chunk-id must be a CHUNK-* identifier.")
    return value


def flatten_ranges(value: Any, field: str) -> list[int]:
    pages: list[int] = []
    for pair in value:
        start, end = pair
        require(start <= end, "invalid_ranges", f"{field} must contain ascending pairs.")
        pages.extend(range(start, end + 1))
    require(not duplicate_values(pages), "overlapping_ranges", f"{field} contains overlapping ranges.")
    return pages


def chunk_records(chunk_manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    orders: set[int] = set()
    for record in chunk_manifest["chunks"]:
        chunk_id = record["chunk_id"]
        require(chunk_id not in result, "duplicate_chunk_id", f"Duplicate chunk ID: {chunk_id}")
        order = record["packet_order"]
        require(order not in orders, "invalid_packet_order", f"Chunk {chunk_id} repeats a packet order.")
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


def resolve_state_path(root: Path, value: str) -> Path:
    return root.joinpath(*PurePosixPath(safe_relative_path(value)).parts)


def load_canonical_run(state_path: Path) -> dict[str, Any]:
    state_path = state_path.resolve()
    state, state_bytes, state_file_sha256 = load_json_snapshot(state_path, "Canonical evaluation state")
    root = state_path.parent
    errors, warnings = validate_state(state, state_path=state_path, check_files=True)
    require(not errors, "canonical_state_invalid", "Canonical evaluation state failed validation.", errors)
    return {
        "state_path": state_path,
        "state": state,
        "state_bytes": state_bytes,
        "state_file_sha256": state_file_sha256,
        "root": root,
        "warnings": warnings,
    }


def state_record_for_path(run: dict[str, Any], path: Path, required: bool = True) -> dict[str, Any] | None:
    root = run["root"]
    require(path_is_within(path, root), "canonical_artifact_outside_root", f"Canonical artifact is outside the evaluation root: {path}")
    relative = path.resolve().relative_to(root.resolve()).as_posix()
    matches = [item for item in run["state"].get("artifacts", []) if isinstance(item, dict) and item.get("path") == relative]
    if required:
        require(len(matches) == 1, "canonical_artifact_not_registered", f"Expected exactly one state artifact record for {relative}.")
    elif len(matches) > 1:
        raise PreparationError("duplicate_artifact_path", f"State contains duplicate path {relative}.")
    if not matches:
        return None
    return matches[0]


def validate_json_identity_file(path: Path, label: str, schema_name: str, own_hash_field: str | None = None) -> tuple[dict[str, Any], bytes, str]:
    document, payload, digest = load_json_snapshot(path.resolve(), label)
    errors = schema_errors(document, schema_name)
    require(not errors, "schema_validation_failed", f"{label} is structurally invalid.", errors)
    if own_hash_field is not None:
        validate_self_hash(document, own_hash_field, label)
    return document, payload, digest


def load_frozen_inputs(args: argparse.Namespace, audit_kind: str) -> dict[str, Any]:
    run = load_canonical_run(Path(args.state))
    state = run["state"]
    page_map, page_map_bytes, page_map_file_sha = validate_json_identity_file(Path(args.page_map), "Page map", "page-map.schema.json", "page_map_sha256")
    chunks, chunk_bytes, chunk_file_sha = validate_json_identity_file(Path(args.chunk_manifest), "Chunk manifest", "chunk-manifest.schema.json", "chunk_manifest_sha256")
    policy, policy_bytes, policy_file_sha = validate_json_identity_file(Path(args.policy), "Evaluation policy", "evaluation-policy-v3.schema.json", "policy_sha256")
    benchmark, benchmark_bytes, benchmark_file_sha = validate_json_identity_file(Path(args.benchmark), "Frozen benchmark", "source-benchmark.schema.json", "benchmark_sha256")
    candidate, candidate_bytes, candidate_file_sha = validate_json_identity_file(Path(args.normalized_candidate), "Normalized candidate", "candidate-index-v2.schema.json")
    inventory, inventory_bytes, inventory_file_sha = validate_json_identity_file(Path(args.item_inventory), "Item inventory", "item-inventory-v2.schema.json")

    for path in (Path(args.page_map), Path(args.chunk_manifest), Path(args.policy), Path(args.benchmark), Path(args.normalized_candidate), Path(args.item_inventory)):
        state_record_for_path(run, path.resolve())

    source_sha = require_sha256(state.get("source", {}).get("sha256"), "state.source.sha256")
    candidate_state = state.get("candidate")
    require(isinstance(candidate_state, dict), "candidate_not_integrated", "Canonical candidate preparation has not been integrated.")
    for state_field, supplied, label in (
        ("normalized_path", Path(args.normalized_candidate).resolve(), "normalized candidate"),
        ("item_inventory_path", Path(args.item_inventory).resolve(), "item inventory"),
        ("benchmark_path", Path(args.benchmark).resolve(), "frozen benchmark"),
    ):
        stored = candidate_state.get(state_field)
        require(isinstance(stored, str) and resolve_state_path(run["root"], stored).resolve() == supplied, "canonical_checkpoint_path_mismatch", f"Supplied {label} is not the exact path recorded by the integrated candidate checkpoint.")
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


def packet_assignment_index(packet: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    assignments: dict[str, dict[str, Any]] = {}
    paths: dict[str, list[str]] = {}
    packet_paths = packet["paths"]
    for record in packet_paths:
        path_id = record["path_id"]
        heading_path = record["heading_path"]
        require(path_id not in paths or paths[path_id] == heading_path, "locator_packet_shape", f"Packet path ID {path_id} has conflicting heading paths.")
        paths[path_id] = heading_path
        for assignment in record["locator_assignments"]:
            locator_id = assignment["locator_id"]
            require(locator_id not in assignments, "duplicate_locator_assignment", f"Locator packet repeats assignment {locator_id}.")
            assignments[locator_id] = {**assignment, "path_id": path_id, "heading_path": heading_path}
    summary = packet["summary"]
    require(summary.get("path_count") == len(packet_paths), "locator_packet_count_mismatch", "Locator packet path count does not recompute.")
    require(summary.get("locator_assignment_count") == len(assignments), "locator_packet_count_mismatch", "Locator packet assignment count does not recompute.")
    return assignments, paths


def validate_locator_packet(path: Path, frozen: dict[str, Any], chunk_id: str) -> dict[str, Any]:
    packet, payload, digest = validate_json_identity_file(path, "Candidate locator packet", "candidate-locator-chunk.schema.json")
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
    for record in candidate["records"]:
        path_id = record["path_id"]
        require(path_id not in paths, "candidate_shape", f"Duplicate candidate path ID: {path_id}")
        paths[path_id] = record
        for assignment in record["locator_assignments"]:
            locator_id = assignment["locator_id"]
            require(locator_id not in locators, "candidate_shape", f"Duplicate candidate locator ID: {locator_id}")
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
    subjects = frozen["benchmark"]["subjects"]
    for subject in subjects:
        priority = subject.get("priority")
        if priority not in PRIORITIES:
            continue
        subject_id = subject["subject_id"]
        require(subject_id not in scored_subjects, "duplicate_subject_id", f"Frozen benchmark repeats {subject_id}.")
        evidence = subject["evidence"]
        candidates: list[tuple[int, int, int, str]] = []
        treatments_by_identity: dict[tuple[int, str], dict[str, Any]] = {}
        subject_evidence_ids: set[str] = set()
        for item in evidence:
            page = item["document_page"]
            require(page in owners, "missing_access_ownership", f"Subject {subject_id} evidence lacks a uniquely owned document page.")
            locator_class = item.get("locator_class", "supporting")
            chunk_id = owners[page]
            candidates.append((LOCATOR_CLASS_RANK[locator_class], packet_order[chunk_id], page, chunk_id))
            if locator_class != "incidental":
                evidence_id = item["evidence_id"]
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
                if source_evidence_id is not None:
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

    tasks = frozen["benchmark"]["reader_tasks"]
    seen_tasks: set[str] = set()
    for task in tasks:
        task_id = task["task_id"]
        require(task_id not in seen_tasks, "duplicate_reader_task", f"Frozen benchmark repeats {task_id}.")
        seen_tasks.add(task_id)
        subject_ids = task["subject_ids"]
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


def validate_locator_audit(artifact: dict[str, Any], frozen: dict[str, Any], packet: dict[str, Any], chunk_id: str) -> dict[str, Any]:
    errors = schema_errors(artifact, "locator-audit-v2.schema.json")
    require(not errors, "schema_validation_failed", "Locator audit is structurally invalid.", errors)
    require(artifact.get("evaluation_id") == frozen["state"].get("evaluation_id"), "audit_identity_mismatch", "Locator audit evaluation ID differs.")
    require(artifact.get("candidate_sha256") == frozen["candidate_sha256"], "audit_identity_mismatch", "Locator audit candidate hash differs.")
    require(artifact.get("chunk_id") == chunk_id, "audit_chunk_mismatch", "Locator audit names a different chunk.")
    expected = list(packet["assignments"])
    require(artifact.get("expected_locator_ids") == expected or set(artifact.get("expected_locator_ids", [])) == set(expected), "locator_denominator_mismatch", "Locator audit expected IDs differ from the exact packet.")
    judgments = artifact["judgments"]
    ids: list[str] = []
    judgment_counts = Counter({key: 0 for key in sorted(LOCATOR_STATUSES)})
    severity_counts = Counter({key: 0 for key in sorted(SEVERITIES)})
    error_counts: Counter[str] = Counter()
    for judgment in judgments:
        locator_id = judgment["locator_id"]
        ids.append(locator_id)
        assignment = packet["assignments"].get(locator_id)
        require(assignment is not None, "foreign_chunk_assignment", f"Locator audit contains foreign assignment {locator_id}.")
        require(judgment.get("path_id") == assignment["path_id"], "complete_path_mismatch", f"Locator judgment {locator_id} path ID differs from packet.")
        require(judgment.get("complete_heading_path") == assignment["heading_path"], "complete_path_mismatch", f"Locator judgment {locator_id} does not preserve the complete heading path.")
        require(judgment.get("document_page") == assignment.get("document_page"), "locator_assignment_mismatch", f"Locator judgment {locator_id} document page differs.")
        require(judgment.get("source_page_label") == assignment.get("source_page_label"), "locator_assignment_mismatch", f"Locator judgment {locator_id} source label differs.")
        status = judgment["judgment"]
        severity = judgment["severity"]
        codes = judgment["error_codes"]
        judgment_counts[status] += 1
        severity_counts[severity] += 1
        error_counts.update(codes)
    duplicates = duplicate_values(ids)
    require(not duplicates, "duplicate_locator_assignment", "Locator audit repeats assignment IDs.", duplicates)
    require(set(ids) == set(expected), "missing_locator_assignment", "Locator audit does not judge the exact packet assignment set.", {"missing": sorted(set(expected) - set(ids)), "foreign": sorted(set(ids) - set(expected))})
    completion = artifact["completion"]
    require(completion.get("expected") == len(expected) and completion.get("judged") == len(ids) and completion.get("unique") is True and completion.get("complete") is True, "audit_completion", "Locator audit completion denominators do not recompute.")
    return {
        "locator_ids": ids,
        "path_ids": sorted(packet["paths"]),
        "judgment_counts": dict(sorted(judgment_counts.items())),
        "severity_counts": dict(sorted(severity_counts.items())),
        "error_code_counts": dict(sorted(error_counts.items())),
        "completion": {"expected": len(expected), "judged": len(ids), "unique": True, "complete": True},
    }


def validate_missing_access_audit(artifact: dict[str, Any], frozen: dict[str, Any], workset: dict[str, Any], chunk_id: str) -> dict[str, Any]:
    errors = schema_errors(artifact, "missing-access-audit.schema.json")
    require(not errors, "schema_validation_failed", "Missing-access audit is structurally invalid.", errors)
    require(artifact.get("evaluation_id") == frozen["state"].get("evaluation_id"), "audit_identity_mismatch", "Missing-access audit evaluation ID differs.")
    require(artifact.get("candidate_sha256") == frozen["candidate_sha256"], "audit_identity_mismatch", "Missing-access audit candidate hash differs.")
    require(artifact.get("benchmark_sha256") == frozen["benchmark"]["benchmark_sha256"], "audit_identity_mismatch", "Missing-access audit benchmark hash differs.")
    require(artifact.get("chunk_id") == chunk_id, "audit_chunk_mismatch", "Missing-access audit names a different chunk.")
    expected_subjects = workset["subject_ids"]
    expected_tasks = workset["reader_task_ids"]
    expected_treatments = workset["treatment_ids"]
    require(set(artifact["expected_subject_ids"]) == set(expected_subjects), "subject_denominator_mismatch", "Missing-access expected subjects differ from deterministic ownership.")
    require(set(artifact["expected_reader_task_ids"]) == set(expected_tasks), "reader_task_denominator_mismatch", "Missing-access reader tasks differ from deterministic ownership.")
    require(set(artifact["expected_treatment_ids"]) == set(expected_treatments), "treatment_denominator_mismatch", "Missing-access treatments differ from deterministic ownership.")

    subject_index = {item.get("subject_id"): item for item in frozen["benchmark"].get("subjects", []) if isinstance(item, dict)}
    candidate_path_ids = {item.get("path_id") for item in frozen["inventory"].get("paths", []) if isinstance(item, dict)}
    _, candidate_locators = candidate_path_index(frozen["candidate"])
    workset_treatments_by_subject: dict[str, list[dict[str, Any]]] = {}
    for treatment in workset["treatments"]:
        workset_treatments_by_subject.setdefault(treatment["subject_id"], []).append(treatment)
    subject_judgments = artifact["subject_judgments"]
    subject_ids: list[str] = []
    coverage_counts = Counter({key: 0 for key in sorted(COVERAGE_STATUSES)})
    access_counts = Counter({key: 0 for key in ("direct_only", "cross_reference_only", "both", "none", "uninspectable")})
    severity_counts = Counter({key: 0 for key in sorted(SEVERITIES)})
    error_code_counts: Counter[str] = Counter()
    subject_recall_records: dict[str, dict[str, Any]] = {}
    reported_missed_treatments: dict[str, set[tuple[int, str]]] = {}
    for judgment in subject_judgments:
        subject_id = judgment["subject_id"]
        subject_ids.append(subject_id)
        require(subject_id in expected_subjects, "foreign_chunk_subject", f"Missing-access audit contains foreign subject {subject_id}.")
        expected_subject = subject_index[subject_id]
        require(judgment.get("priority") == expected_subject.get("priority"), "subject_identity_mismatch", f"Subject {subject_id} priority differs from benchmark.")
        coverage = judgment["coverage"]
        matched = judgment["matched_path_ids"]
        require(set(matched).issubset(candidate_path_ids), "matched_path_mismatch", f"Subject {subject_id} matched paths are invalid.")
        expected_pages = sorted({item["document_page"] for item in workset_treatments_by_subject.get(subject_id, [])})
        found = judgment["found_document_pages"]
        missed = judgment["missed_document_pages"]
        require(judgment.get("expected_document_pages") == expected_pages, "treatment_page_mismatch", f"Subject {subject_id} expected pages differ from benchmark.")
        require(not (set(found) & set(missed)) and set(found) | set(missed) == set(expected_pages), "treatment_page_mismatch", f"Subject {subject_id} found/missed pages do not partition expected pages.")
        locator_recall = judgment["locator_recall"]
        require(locator_recall.get("expected") == len(expected_pages) and locator_recall.get("found") == len(found) and locator_recall.get("missed") == len(missed), "locator_recall_mismatch", f"Subject {subject_id} locator-recall counts do not match its exact page accounting.")
        expected_rate = None if not expected_pages else len(found) / len(expected_pages)
        if "rate" in locator_recall:
            require(locator_recall.get("rate") == expected_rate, "locator_recall_mismatch", f"Subject {subject_id} locator-recall rate does not recompute.")
        treatment_recall = judgment["treatment_recall"]
        for locator_class in ("principal", "supporting", "synthesis_or_conclusion"):
            class_record = treatment_recall[locator_class]
            expected_class_pages = sorted(item["document_page"] for item in workset_treatments_by_subject.get(subject_id, []) if item["locator_class"] == locator_class)
            found_class = class_record.get("found_document_pages")
            missed_class = class_record.get("missed_document_pages")
            uninspectable_class = class_record.get("uninspectable_document_pages")
            require(class_record.get("expected_document_pages") == expected_class_pages, "treatment_recall_mismatch", f"Subject {subject_id} {locator_class} expected pages differ from ownership plan.")
            treatment_sets = [set(found_class), set(missed_class), set(uninspectable_class)]
            require(not any(treatment_sets[left] & treatment_sets[right] for left in range(3) for right in range(left + 1, 3)) and set().union(*treatment_sets) == set(expected_class_pages), "treatment_recall_mismatch", f"Subject {subject_id} {locator_class} treatment pages do not partition found, missed, and uninspectable denominators.")
        missing_routes = judgment["missing_routes"]
        route_types: list[str] = []
        for route in missing_routes:
            route_types.append(route["route_type"])
        require(not duplicate_values(route_types), "missing_route_accounting", f"Subject {subject_id} repeats a missing route type.")
        require(("direct" in route_types) == (not judgment["direct_access"]) and ("cross_reference" in route_types) == (not judgment["cross_reference_access"]), "missing_route_accounting", f"Subject {subject_id} missing routes do not match its access judgments.")
        missed_records = judgment["missed_treatments"]
        missed_keys: set[tuple[int, str]] = set()
        for record in missed_records:
            key = (record["document_page"], record["locator_class"])
            require(key not in missed_keys, "missed_treatment_accounting", f"Subject {subject_id} repeats a missed treatment.")
            missed_keys.add(key)
        reported_missed_treatments[subject_id] = missed_keys
        codes = judgment["error_codes"]
        coverage_counts[coverage] += 1
        severity_counts[judgment["severity"]] += 1
        error_code_counts.update(codes)
        direct = judgment["direct_access"]
        cross = judgment["cross_reference_access"]
        access_counts["uninspectable" if coverage == "uninspectable" else "both" if direct and cross else "direct_only" if direct else "cross_reference_only" if cross else "none"] += 1
        subject_recall_records[subject_id] = treatment_recall
    require(not duplicate_values(subject_ids), "duplicate_subject_judgment", "Missing-access audit repeats subject judgments.")
    require(set(subject_ids) == set(expected_subjects), "missing_subject_judgment", "Missing-access audit does not contain the exact owned subject set.")

    task_results = artifact["reader_task_results"]
    task_ids: list[str] = []
    task_counts = Counter({key: 0 for key in sorted(TASK_STATUSES)})
    task_index = {item.get("task_id"): item for item in frozen["benchmark"].get("reader_tasks", []) if isinstance(item, dict)}
    for result in task_results:
        task_id = result["task_id"]
        task_ids.append(task_id)
        require(task_id in expected_tasks, "foreign_chunk_reader_task", f"Missing-access audit contains foreign reader task {task_id}.")
        status = result["result"]
        require(result.get("subject_ids") == task_index[task_id].get("subject_ids"), "reader_task_identity_mismatch", f"Reader task {task_id} subject order differs from the frozen benchmark.")
        require(result.get("access_mode") in ACCESS_MODES, "audit_judgment", f"Reader task {task_id} must record its tested access mode.")
        matched = result["matched_path_ids"]
        require(set(matched).issubset(candidate_path_ids), "matched_path_mismatch", f"Reader task {task_id} matched paths are invalid.")
        severity_counts[result["severity"]] += 1
        task_counts[status] += 1
    require(not duplicate_values(task_ids), "duplicate_reader_task_judgment", "Missing-access audit repeats reader tasks.")
    require(set(task_ids) == set(expected_tasks), "missing_reader_task_judgment", "Missing-access audit does not contain the exact owned reader-task set.")

    expected_treatment_index = {item["treatment_id"]: item for item in workset["treatments"]}
    treatment_judgments = artifact["treatment_judgments"]
    treatment_ids: list[str] = []
    treatment_counts = Counter({key: 0 for key in sorted(TREATMENT_RECALL_STATUSES)})
    treatment_by_subject: dict[str, dict[str, dict[str, list[int]]]] = {}
    for judgment in treatment_judgments:
        treatment_id = judgment["treatment_id"]
        treatment_ids.append(treatment_id)
        expected = expected_treatment_index.get(treatment_id)
        require(expected is not None, "foreign_chunk_treatment", f"Missing-access audit contains foreign treatment {treatment_id}.")
        for field in ("subject_id", "document_page", "locator_class"):
            require(judgment.get(field) == expected[field], "treatment_identity_mismatch", f"Treatment {treatment_id} field {field} differs from benchmark workset.")
        status = judgment["status"]
        evidence_ids = judgment["evidence_ids"]
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
        completion = artifact[field]
        require(completion.get("expected") == expected_count and completion.get("judged") == actual_count and completion.get("complete") is True, "audit_completion", f"{field} denominators do not recompute.")
        if "unique" in completion:
            require(completion.get("unique") is True, "audit_completion", f"{field}.unique must be true.")

    dependency_defects = list(artifact.get("dependency_defects", []))
    for subject in subject_judgments:
        dependency_defects.extend(subject.get("dependency_defects", []))
    defect_ids = [item.get("defect_id") for item in dependency_defects]
    require(all(isinstance(item, str) and item for item in defect_ids) and not duplicate_values(defect_ids), "dependency_defect_shape", "Dependency defects require unique IDs.")
    for defect in dependency_defects:
        require(defect.get("locator_id") in candidate_locators, "dependency_defect_locator", f"Dependency defect {defect.get('defect_id')} names an unknown locator.")
        coverage_subject_ids = defect.get("coverage_subject_ids")
        require(set(coverage_subject_ids).issubset(expected_subjects), "dependency_defect_shape", f"Dependency defect {defect.get('defect_id')} lacks valid coverage subject IDs.")
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
        errors = schema_errors(artifact, "locator-audit-v2.schema.json")
        require(not errors, "schema_validation_failed", "Canonical locator audit is structurally invalid.", errors)
        require(artifact.get("evaluation_id") == frozen["state"].get("evaluation_id"), "locator_audit_set_identity", "Locator audit evaluation identity differs.")
        require(artifact.get("candidate_sha256") == frozen["candidate_sha256"], "locator_audit_set_identity", "Locator audit candidate identity differs.")
        chunk_id = validate_chunk_id(artifact.get("chunk_id"))
        require(chunk_id in expected_chunks and chunk_id not in chunks, "locator_audit_set_chunk", f"Unexpected or duplicate locator audit chunk {chunk_id}.")
        state_record_for_path(frozen, path)
        assignments = expected_by_chunk[chunk_id]
        path_ids = {item["path_id"] for item in assignments.values()}
        pseudo_packet = {
            "sha256": sha256_bytes(json.dumps({"chunk_id": chunk_id, "assignment_ids": sorted(assignments)}, sort_keys=True, separators=(",", ":")).encode("utf-8")),
            "assignments": assignments,
            "paths": {path_id: candidate_paths[path_id]["heading_path"] for path_id in path_ids},
        }
        result = validate_locator_audit(artifact, frozen, pseudo_packet, chunk_id)
        actual = result["locator_ids"]
        chunks.add(chunk_id)
        locator_ids.extend(actual)
        records.append({"chunk_id": chunk_id, "file_sha256": digest, "byte_length": len(payload), "locator_ids": sorted(actual)})
    require(chunks == expected_chunks, "locator_audit_set_incomplete", "Canonical locator audit set does not cover every frozen chunk.")
    require(not duplicate_values(locator_ids), "duplicate_locator_assignment", "Canonical locator audits duplicate locator-assignment IDs across chunks.")
    records.sort(key=lambda item: item["chunk_id"])
    digest = sha256_bytes(json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return {"records": records, "sha256": digest, "locator_ids": sorted(locator_ids)}


def canonical_candidate_parent(frozen: dict[str, Any]) -> Path:
    normalized = frozen["state"].get("candidate", {}).get("normalized_path")
    require(isinstance(normalized, str), "candidate_state_shape", "State candidate.normalized_path is required.")
    return resolve_state_path(frozen["root"], normalized).parent


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


def validate_local_audit(
    audit: dict[str, Any], frozen: dict[str, Any], audit_kind: str,
    packet_by_chunk: dict[str, dict[str, Any]], locator_set: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    """Validate judgment coverage without requiring worker provenance packaging."""
    chunk_id = validate_chunk_id(audit.get("chunk_id"))
    require(chunk_id in frozen["chunks"], "unknown_chunk", f"Chunk {chunk_id} is absent from the frozen manifest.")
    if audit_kind == "locator":
        packet = packet_by_chunk.get(chunk_id)
        require(packet is not None, "locator_packet_missing", f"Provide the locator packet for {chunk_id}.")
        compare_packet_to_candidate(packet, frozen)
        result = validate_locator_audit(audit, frozen, packet, chunk_id)
    else:
        require(locator_set is not None, "locator_audit_set_incomplete", "Missing-access validation requires the complete locator-audit set.")
        workset = build_missing_worksets(frozen)[chunk_id]
        result = validate_missing_access_audit(audit, frozen, workset, chunk_id)
    return chunk_id, result


def load_local_validation_inputs(
    args: argparse.Namespace, frozen: dict[str, Any], audit_kind: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    packets: dict[str, dict[str, Any]] = {}
    if audit_kind == "locator":
        for raw_path in args.locator_packet or []:
            document = load_json(Path(raw_path).resolve(), "Locator packet")
            chunk_id = validate_chunk_id(document.get("chunk_id"))
            require(chunk_id not in packets, "duplicate_chunk", f"More than one locator packet was supplied for {chunk_id}.")
            packets[chunk_id] = validate_locator_packet(Path(raw_path).resolve(), frozen, chunk_id)
        return packets, None
    return {}, load_locator_audit_set(args.locator_audit or [], frozen)


def command_validate_local(args: argparse.Namespace) -> None:
    args.allow_completed_boundary = True
    frozen = load_frozen_inputs(args, args.audit_kind)
    packets, locator_set = load_local_validation_inputs(args, frozen, args.audit_kind)
    results = []
    for raw_path in args.audit:
        audit = load_json(Path(raw_path).resolve(), "Candidate audit")
        chunk_id, result = validate_local_audit(audit, frozen, args.audit_kind, packets, locator_set)
        results.append({"chunk_id": chunk_id, "path": str(Path(raw_path).resolve()), "completion": result["completion"]})
    emit({"ok": True, "operation": "validate-audits", "audit_kind": args.audit_kind, "audits": results})


def _registered_chunks(state: dict[str, Any], state_path: Path, artifact_type: str) -> set[str]:
    chunks: set[str] = set()
    for record in state.get("artifacts", []):
        if not isinstance(record, dict) or record.get("artifact_type") != artifact_type:
            continue
        path = resolve_state_path(state_path.parent, str(record.get("path", "")))
        if not path.is_file():
            continue
        document = load_json(path, "Registered candidate audit")
        chunks.add(validate_chunk_id(document.get("chunk_id")))
    return chunks


def command_register_local(args: argparse.Namespace) -> None:
    state_path = Path(args.state).resolve()
    with evaluation_mutation_lock(state_path):
        args.allow_completed_boundary = True
        frozen = load_frozen_inputs(args, args.audit_kind)
        packets, locator_set = load_local_validation_inputs(args, frozen, args.audit_kind)
        state = deepcopy(frozen["state"])
        stage_name = audit_stage(args.audit_kind)
        stage_index = STAGES.index(stage_name)
        unmet = [name for name in STAGES[:stage_index] if state["stages"][name]["status"] != "completed"]
        require(not unmet, "stage_dependencies_incomplete", f"Complete these stages before {stage_name}: {', '.join(unmet)}")
        active = [name for name, value in state["stages"].items() if value.get("status") == "in_progress" and name != stage_name]
        require(not active, "another_stage_in_progress", f"Another stage is in progress: {', '.join(active)}")

        parent = canonical_candidate_parent(frozen) / ("locator-audits" if args.audit_kind == "locator" else "missing-access-audits")
        artifact_type = "locator_audit" if args.audit_kind == "locator" else "missing_access_audit"
        registered: list[dict[str, Any]] = []
        for raw_path in args.audit:
            source = Path(raw_path).resolve()
            audit, payload, digest = load_json_snapshot(source, "Candidate audit")
            chunk_id, result = validate_local_audit(audit, frozen, args.audit_kind, packets, locator_set)
            suffix = "v2" if args.audit_kind == "locator" else "v1"
            stem = "locator-audit" if args.audit_kind == "locator" else "missing-access-audit"
            destination = parent / f"{stem}.{chunk_id}.{suffix}.json"
            require_safe_output_path(destination, frozen["root"], "Canonical candidate audit")
            if destination.is_file():
                require(sha256_file(destination) == digest, "canonical_chunk_exists", f"A different audit is already registered for {chunk_id}: {destination}")
            else:
                replace_bytes_atomic(destination, payload)
            stamp = now()
            record = artifact_record(destination, frozen["root"], stage_name, artifact_type, "private", stamp)
            record["schema_version"] = audit["schema_version"]
            existing = [item for item in state["artifacts"] if item.get("path") == record["path"]]
            if not existing:
                state["artifacts"].append(record)
            registered.append({"chunk_id": chunk_id, "path": str(destination), "completion": result["completion"]})

        chunks = _registered_chunks(state, state_path, artifact_type)
        missing = sorted(set(frozen["chunks"]) - chunks)
        stamp = now()
        state["artifacts"].sort(key=lambda item: item["path"])
        state["stages"][stage_name] = {
            "status": "in_progress" if missing else "completed",
            "updated_at": stamp,
            "notes": [f"Registered {len(chunks)}/{len(frozen['chunks'])} current audit chunks."],
        }
        state["updated_at"] = stamp
        errors, warnings = validate_state(state, state_path=state_path, check_files=True)
        require(not errors, "canonical_validation_failed", "Updated evaluation state failed validation.", errors)
        save_state(state_path, state)
    emit({
        "ok": True, "operation": "register-audits", "audit_kind": args.audit_kind,
        "registered": registered, "stage_status": state["stages"][stage_name]["status"],
        "missing_chunk_ids": missing, "warnings": warnings,
        "checkpoint_required": False,
    })


def add_frozen_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state", required=True, help="Canonical evaluation-state.json (v5).")
    parser.add_argument("--page-map", required=True, help="Frozen page-map-v1 JSON.")
    parser.add_argument("--chunk-manifest", required=True, help="Frozen chunk-manifest-v1 JSON.")
    parser.add_argument("--policy", required=True, help="Frozen subject-index-evaluation-policy-v3 JSON.")
    parser.add_argument("--benchmark", required=True, help="Frozen source-subject-benchmark-v2 JSON.")
    parser.add_argument("--normalized-candidate", required=True, help="Integrated candidate-index-v2 JSON.")
    parser.add_argument("--item-inventory", required=True, help="Integrated item-inventory-v2 JSON.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)

    for name, help_text, handler in (
        ("validate-audits", "Validate current audit chunks without changing canonical state.", command_validate_local),
        ("register-audits", "Validate and register current audit chunks in the single state file.", command_register_local),
    ):
        command = subparsers.add_parser(name, help=help_text)
        add_frozen_arguments(command)
        command.add_argument("--audit-kind", choices=sorted(AUDIT_KINDS), required=True)
        command.add_argument("--audit", action="append", required=True, help="Audit JSON; repeat for any chunks handled in this invocation.")
        command.add_argument("--locator-packet", action="append", help="For locator audits, provide the corresponding packet for each supplied chunk.")
        command.add_argument("--locator-audit", action="append", help="For missing-access audits, provide the complete registered locator-audit set.")
        command.set_defaults(handler=handler)
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
