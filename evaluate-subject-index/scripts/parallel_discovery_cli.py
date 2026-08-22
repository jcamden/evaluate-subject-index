#!/usr/bin/env python3
"""Validate parallel source-discovery workers and integrate their artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


STATE_SCHEMA_VERSION = "subject-index-evaluation-state-v3"
MANIFEST_SCHEMA_VERSION = "subject-index-artifact-manifest-v1"
CHUNK_SCHEMA_VERSION = "source-subject-chunk-v1"
RECEIPT_SCHEMA_VERSION = "parallel-source-discovery-receipt-v1"
VALID_PRIORITIES = {"essential", "major", "optional", "exclude_by_default"}
VALID_LOCATOR_CLASSES = {"principal", "supporting", "synthesis_or_conclusion", "incidental"}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def emit(payload: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(exit_code)


def fail(code: str, message: str, details: Any = None) -> None:
    payload: dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    emit(payload, 1)


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail("file_not_found", f"{label} does not exist: {path}")
    except json.JSONDecodeError as exc:
        fail("invalid_json", f"{label} is invalid JSON: {exc}")
    if not isinstance(value, dict):
        fail("invalid_document", f"{label} must be a JSON object.")
    return value


def save_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact_id(path: str, sha256: str) -> str:
    identity = hashlib.sha256(f"{path}\0{sha256}".encode("utf-8")).hexdigest()
    return f"ART-{identity[:12].upper()}"


def safe_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value in {"", "."} or "\\" in value:
        fail("unsafe_path", f"Path is not a safe relative POSIX path: {value}")
    return str(path)


def load_run(state_path: Path) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    state_path = state_path.resolve()
    state = load_json(state_path, "Evaluation state")
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        fail("unsupported_state", f"Expected {STATE_SCHEMA_VERSION}.")
    root = state_path.parent
    manifest_path = root / safe_relative_path(str(state.get("artifact_manifest_path", "artifact-manifest.json")))
    manifest = load_json(manifest_path, "Artifact manifest")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        fail("unsupported_manifest", f"Expected {MANIFEST_SCHEMA_VERSION}.")
    if manifest.get("evaluation_id") != state.get("evaluation_id"):
        fail("identity_mismatch", "State and artifact manifest evaluation IDs differ.")
    return state, manifest, root, manifest_path


def chunk_records(chunk_manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = chunk_manifest.get("chunks")
    if not isinstance(records, list):
        fail("invalid_chunk_manifest", "chunk-manifest.json must contain a chunks array.")
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("chunk_id"), str):
            fail("invalid_chunk_manifest", "Every chunk record must have a string chunk_id.")
        chunk_id = record["chunk_id"]
        if chunk_id in result:
            fail("duplicate_chunk_id", f"Duplicate chunk ID in manifest: {chunk_id}")
        result[chunk_id] = record
    return result


def flatten_ranges(ranges: Any, label: str) -> list[int]:
    if not isinstance(ranges, list):
        fail("invalid_chunk_manifest", f"{label} must be an array of inclusive pairs.")
    pages: list[int] = []
    for value in ranges:
        if not (
            isinstance(value, list)
            and len(value) == 2
            and all(isinstance(item, int) for item in value)
            and value[0] <= value[1]
        ):
            fail("invalid_chunk_manifest", f"Invalid range in {label}: {value}")
        pages.extend(range(value[0], value[1] + 1))
    return pages


def expected_chunk_pages(record: dict[str, Any]) -> tuple[list[int], list[int]]:
    return (
        flatten_ranges(record.get("owned_document_page_ranges"), "owned_document_page_ranges"),
        flatten_ranges(record.get("context_document_page_ranges", []), "context_document_page_ranges"),
    )


def active_policy_hash(state: dict[str, Any], manifest: dict[str, Any]) -> str | None:
    records = [
        item for item in manifest.get("artifacts", [])
        if isinstance(item, dict) and item.get("artifact_type") == "evaluation_policy"
    ]
    if not records:
        return None
    path = records[-1].get("path")
    if not isinstance(path, str):
        return None
    root = Path(state["_state_path"]).resolve().parent
    policy = load_json(root / safe_relative_path(path), "Evaluation policy")
    value = policy.get("policy_sha256")
    return value if isinstance(value, str) else None


def validate_subject_artifact(
    artifact: dict[str, Any],
    artifact_path: Path,
    state: dict[str, Any],
    manifest: dict[str, Any],
    chunk_manifest: dict[str, Any],
    require_blindness: bool,
) -> dict[str, Any]:
    errors: list[str] = []
    if artifact.get("schema_version") != CHUNK_SCHEMA_VERSION:
        errors.append(f"schema_version must be {CHUNK_SCHEMA_VERSION}.")
    if artifact.get("evaluation_id") != state.get("evaluation_id"):
        errors.append("evaluation_id does not match canonical state.")
    chunk = artifact.get("chunk")
    if not isinstance(chunk, dict):
        errors.append("chunk must be an object.")
        chunk = {}
    chunk_id = chunk.get("chunk_id")
    records = chunk_records(chunk_manifest)
    expected = records.get(chunk_id)
    if expected is None:
        errors.append(f"chunk_id is not present in the canonical chunk manifest: {chunk_id}")
        expected_owned: list[int] = []
        expected_context: list[int] = []
    else:
        expected_owned, expected_context = expected_chunk_pages(expected)
        if chunk.get("owned_document_pages") != expected_owned:
            errors.append("owned_document_pages do not match the canonical chunk manifest.")
        if chunk.get("context_document_pages") != expected_context:
            errors.append("context_document_pages do not match the canonical chunk manifest.")

    blindness = artifact.get("candidate_blindness")
    if require_blindness and blindness != "preserved":
        errors.append("worker discovery requires candidate_blindness=preserved.")
    elif blindness not in {"preserved", "compromised", "not_claimed"}:
        errors.append("candidate_blindness has an invalid value.")

    page_review = artifact.get("page_review")
    if not isinstance(page_review, dict):
        errors.append("page_review must be an object.")
        page_review = {}
    expected_count = len(expected_owned)
    if page_review.get("expected_owned_pages") != expected_count:
        errors.append("page_review.expected_owned_pages does not match chunk ownership.")
    if page_review.get("reviewed_owned_pages") != expected_count:
        errors.append("Every owned page must be recorded as reviewed.")
    if page_review.get("complete") is not True:
        errors.append("page_review.complete must be true.")
    word_count = page_review.get("indexable_source_words")
    if not isinstance(word_count, int) or word_count < 0:
        errors.append("page_review.indexable_source_words must be a nonnegative integer.")

    provenance = artifact.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("provenance must be an object for parallel discovery.")
        provenance = {}
    expected_hashes = {
        "source_sha256": state.get("source", {}).get("sha256"),
        "page_map_sha256": chunk_manifest.get("page_map_sha256"),
        "chunk_manifest_sha256": chunk_manifest.get("chunk_manifest_sha256"),
        "policy_sha256": active_policy_hash(state, manifest),
    }
    for key, value in expected_hashes.items():
        if value and provenance.get(key) != value:
            errors.append(f"provenance.{key} does not match the canonical run.")

    subjects = artifact.get("subjects")
    if not isinstance(subjects, list):
        errors.append("subjects must be an array.")
        subjects = []
    identifiers: set[str] = set()
    priorities = {key: 0 for key in ("essential", "major", "optional", "exclude_by_default")}
    evidence_count = 0
    owned_set = set(expected_owned)
    for index, subject in enumerate(subjects):
        if not isinstance(subject, dict):
            errors.append(f"subjects[{index}] must be an object.")
            continue
        required = ("local_subject_id", "label", "priority", "meaning", "stance", "acceptable_access", "evidence")
        missing = [key for key in required if key not in subject]
        if missing:
            errors.append(f"subjects[{index}] is missing required fields: {missing}")
        identifier = subject.get("local_subject_id")
        if not isinstance(identifier, str) or not identifier:
            errors.append(f"subjects[{index}].local_subject_id must be a nonempty string.")
        elif identifier in identifiers:
            errors.append(f"Duplicate local_subject_id: {identifier}")
        else:
            identifiers.add(identifier)
        priority = subject.get("priority")
        if priority not in VALID_PRIORITIES:
            errors.append(f"subjects[{index}].priority is invalid: {priority}")
        else:
            priorities[priority] += 1
        if not isinstance(subject.get("acceptable_access"), list):
            errors.append(f"subjects[{index}].acceptable_access must be an array.")
        evidence = subject.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"subjects[{index}].evidence must be a nonempty array.")
            continue
        for evidence_index, item in enumerate(evidence):
            evidence_count += 1
            if not isinstance(item, dict):
                errors.append(f"subjects[{index}].evidence[{evidence_index}] must be an object.")
                continue
            page = item.get("document_page")
            if page not in owned_set:
                errors.append(f"Evidence page must be owned by {chunk_id}: {page}")
            label = item.get("source_page_label")
            if label is not None and not isinstance(label, str):
                errors.append(f"source_page_label must be a string or null at subjects[{index}].evidence[{evidence_index}].")
            if item.get("locator_class") not in VALID_LOCATOR_CLASSES:
                errors.append(f"Invalid locator_class at subjects[{index}].evidence[{evidence_index}].")
            if not isinstance(item.get("evidence_summary"), str) or not item.get("evidence_summary"):
                errors.append(f"evidence_summary must be a nonempty paraphrase at subjects[{index}].evidence[{evidence_index}].")

    assessment = artifact.get("discovery_assessment")
    if isinstance(assessment, dict):
        if assessment.get("subject_count") not in {None, len(subjects)}:
            errors.append("discovery_assessment.subject_count does not match subjects.")
        recorded_priorities = assessment.get("priority_counts")
        if isinstance(recorded_priorities, dict):
            for key, value in priorities.items():
                if recorded_priorities.get(key, 0) != value:
                    errors.append(f"discovery_assessment.priority_counts.{key} does not match subjects.")
        if assessment.get("density_used_as_subject_quota") not in {None, False}:
            errors.append("Parallel discovery must not use density as a subject quota.")

    for key in ("exclusions", "uncertainties"):
        if not isinstance(artifact.get(key), list):
            errors.append(f"{key} must be an array.")
    if errors:
        fail(
            "invalid_worker_artifact",
            f"Source-subject artifact failed validation: {artifact_path}",
            errors,
        )
    return {
        "chunk_id": chunk_id,
        "artifact_sha256": sha256_file(artifact_path),
        "candidate_blindness": blindness,
        "expected_owned_pages": expected_count,
        "reviewed_owned_pages": page_review.get("reviewed_owned_pages"),
        "indexable_source_words": word_count,
        "subject_count": len(subjects),
        "priority_counts": priorities,
        "evidence_count": evidence_count,
        "uncertainty_count": len(artifact.get("uncertainties", [])),
        "exclusion_count": len(artifact.get("exclusions", [])),
        "provenance": provenance,
    }


def default_branch(chunk_id: str) -> str:
    return f"source-discovery/{chunk_id.lower()}"


def command_worker_receipt(args: argparse.Namespace) -> None:
    state_path = Path(args.state).resolve()
    state, manifest, _, _ = load_run(state_path)
    state["_state_path"] = str(state_path)
    chunk_manifest = load_json(Path(args.chunk_manifest).resolve(), "Chunk manifest")
    artifact_path = Path(args.artifact).resolve()
    artifact = load_json(artifact_path, "Source-subject artifact")
    summary = validate_subject_artifact(
        artifact, artifact_path, state, manifest, chunk_manifest, require_blindness=True
    )
    chunk_id = summary["chunk_id"]
    if args.chunk_id and args.chunk_id != chunk_id:
        fail("chunk_id_mismatch", f"Requested {args.chunk_id}, but artifact contains {chunk_id}.")
    if not (len(args.base_commit) == 40 and all(ch in "0123456789abcdefABCDEF" for ch in args.base_commit)):
        fail("invalid_base_commit", "base-commit must be a 40-character hexadecimal Git commit SHA.")
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "evaluation_id": state["evaluation_id"],
        "created_at": now(),
        "status": "ready_for_pull_request",
        "chunk_id": chunk_id,
        "project": {
            "repository": args.project,
            "base_commit": args.base_commit.lower(),
            "base_branch": args.base_branch,
            "worker_branch": args.branch or default_branch(chunk_id),
            "mergeable_path": f"source/source-subject-chunk.{chunk_id}.json",
        },
        "source_sha256": state.get("source", {}).get("sha256"),
        "validation": {"ok": True, **summary},
        "publication_scope": {
            "allowed_paths": [f"source/source-subject-chunk.{chunk_id}.json"],
            "forbidden_content": [
                "source PDFs",
                "chunk PDFs",
                "PDF sidecars",
                "portable checkpoints",
                "canonical control files",
                "raw extracted source text",
                "verbatim source-text fields",
                "credentials or secrets",
            ],
        },
    }
    output = Path(args.output).resolve()
    if output.exists() and not args.force:
        fail("output_exists", f"Refusing to overwrite existing receipt: {output}")
    save_json(output, receipt)
    emit({
        "command": "worker-discovery",
        "ok": True,
        "evaluation_id": state["evaluation_id"],
        "chunk_id": chunk_id,
        "worker_branch": receipt["project"]["worker_branch"],
        "mergeable_path": receipt["project"]["mergeable_path"],
        "artifacts_written": [
            {"path": str(output), "sha256": sha256_file(output)},
            {"path": str(artifact_path), "sha256": summary["artifact_sha256"]},
        ],
        "validation": summary,
        "next_actions": ["create_branch", "commit_worker_artifact", "open_pull_request"],
        "warnings": [],
    })


def active_discovery_chunk_ids(manifest: dict[str, Any], root: Path) -> set[str]:
    active: set[str] = set()
    for item in manifest.get("artifacts", []):
        if not isinstance(item, dict) or item.get("artifact_type") != "source_subject_chunk":
            continue
        path = item.get("path")
        if not isinstance(path, str):
            continue
        local = root / safe_relative_path(path)
        if not local.is_file() or sha256_file(local) != item.get("sha256"):
            continue
        artifact = load_json(local, "Registered source-subject artifact")
        chunk_id = artifact.get("chunk", {}).get("chunk_id")
        if isinstance(chunk_id, str):
            active.add(chunk_id)
    return active


def command_integrate(args: argparse.Namespace) -> None:
    state_path = Path(args.state).resolve()
    state, manifest, root, manifest_path = load_run(state_path)
    state["_state_path"] = str(state_path)
    chunk_manifest = load_json(Path(args.chunk_manifest).resolve(), "Chunk manifest")
    expected_ids = set(chunk_records(chunk_manifest))
    supplied: list[tuple[Path, dict[str, Any], dict[str, Any]]] = []
    seen: set[str] = set()
    for value in args.artifact:
        source = Path(value).resolve()
        artifact = load_json(source, "Source-subject artifact")
        summary = validate_subject_artifact(
            artifact, source, state, manifest, chunk_manifest, require_blindness=not args.allow_compromised
        )
        chunk_id = summary["chunk_id"]
        if chunk_id in seen:
            fail("duplicate_integration_chunk", f"Chunk supplied more than once: {chunk_id}")
        seen.add(chunk_id)
        supplied.append((source, artifact, summary))

    new_state = deepcopy(state)
    new_state.pop("_state_path", None)
    new_manifest = deepcopy(manifest)
    stamp = now()
    planned_copies: list[tuple[Path, Path]] = []
    integrated: list[dict[str, Any]] = []
    for source, _, summary in supplied:
        chunk_id = summary["chunk_id"]
        relative = f"source/source-subject-chunk.{chunk_id}.json"
        destination = root / PurePosixPath(relative)
        digest = summary["artifact_sha256"]
        existing = next(
            (item for item in new_manifest.get("artifacts", []) if item.get("path") == relative),
            None,
        )
        if existing and existing.get("sha256") != digest:
            fail(
                "frozen_artifact_conflict",
                f"A different artifact is already registered at {relative}; use adjudication and a versioned path.",
                {"recorded": existing.get("sha256"), "incoming": digest},
            )
        if destination.exists() and sha256_file(destination) != digest:
            fail(
                "destination_conflict",
                f"A different file already exists at {relative}.",
                {"existing": sha256_file(destination), "incoming": digest},
            )
        if not destination.exists():
            planned_copies.append((source, destination))
        record = {
            "artifact_id": artifact_id(relative, digest),
            "stage": "source_subject_discovery",
            "artifact_type": "source_subject_chunk",
            "path": relative,
            "sha256": digest,
            "media_type": mimetypes.guess_type(relative)[0] or "application/json",
            "visibility": "private",
            "retention": "required",
            "frozen": True,
            "recorded_at": existing.get("recorded_at", stamp) if existing else stamp,
        }
        state_record = {key: record[key] for key in (
            "artifact_id", "stage", "artifact_type", "path", "sha256",
            "visibility", "retention", "frozen", "recorded_at"
        )}
        new_manifest["artifacts"] = [item for item in new_manifest.get("artifacts", []) if item.get("path") != relative]
        new_manifest["artifacts"].append(record)
        new_state["artifacts"] = [item for item in new_state.get("artifacts", []) if item.get("path") != relative]
        new_state["artifacts"].append(state_record)
        integrated.append({"chunk_id": chunk_id, "path": relative, "sha256": digest})

    for source, destination in planned_copies:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    new_manifest["artifacts"].sort(key=lambda item: item.get("path", ""))
    new_state["artifacts"].sort(key=lambda item: item.get("path", ""))
    active_ids = active_discovery_chunk_ids(new_manifest, root)
    missing = sorted(expected_ids - active_ids)
    stage = new_state["stages"]["source_subject_discovery"]
    stage["status"] = "completed" if not missing else "in_progress"
    stage["updated_at"] = stamp
    note = f"Integrated parallel source discoveries: {', '.join(sorted(seen))}."
    if note not in stage.setdefault("notes", []):
        stage["notes"].append(note)
    new_manifest["updated_at"] = stamp
    new_state["updated_at"] = stamp
    save_json(manifest_path, new_manifest)
    save_json(state_path, new_state)

    emit({
        "command": "integrate-discoveries",
        "ok": True,
        "evaluation_id": new_state["evaluation_id"],
        "integrated": sorted(integrated, key=lambda item: item["chunk_id"]),
        "source_subject_discovery_status": stage["status"],
        "active_chunk_count": len(active_ids),
        "expected_chunk_count": len(expected_ids),
        "missing_chunks": missing,
        "artifacts_written": [str(manifest_path), str(state_path)] + [item["path"] for item in integrated],
        "next_actions": ["checkpoint"] if not missing else ["review_more_worker_pull_requests"],
        "warnings": [],
    })


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    worker = subparsers.add_parser("worker-receipt")
    worker.add_argument("--state", required=True)
    worker.add_argument("--chunk-manifest", required=True)
    worker.add_argument("--artifact", required=True)
    worker.add_argument("--chunk-id")
    worker.add_argument("--project", required=True)
    worker.add_argument("--base-commit", required=True)
    worker.add_argument("--base-branch", default="main")
    worker.add_argument("--branch")
    worker.add_argument("--output", required=True)
    worker.add_argument("--force", action="store_true")
    worker.set_defaults(func=command_worker_receipt)

    integrate = subparsers.add_parser("integrate")
    integrate.add_argument("--state", required=True)
    integrate.add_argument("--chunk-manifest", required=True)
    integrate.add_argument("--artifact", action="append", required=True)
    integrate.add_argument("--allow-compromised", action="store_true")
    integrate.set_defaults(func=command_integrate)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
