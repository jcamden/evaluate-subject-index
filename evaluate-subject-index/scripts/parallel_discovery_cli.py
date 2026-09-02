#!/usr/bin/env python3
"""Validate and register parallel source-discovery artifacts locally."""

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

from state_cli import evaluation_mutation_lock, save_state
from schema_validation import schema_errors


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


def load_run(state_path: Path) -> tuple[dict[str, Any], Path]:
    state_path = state_path.resolve()
    state = load_json(state_path, "Evaluation state")
    errors = schema_errors(state, "evaluation-state.schema.json")
    if errors:
        fail("invalid_state", "Evaluation state is structurally invalid.", errors)
    root = state_path.parent
    return state, root


def chunk_records(chunk_manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in chunk_manifest["chunks"]:
        chunk_id = record["chunk_id"]
        if chunk_id in result:
            fail("duplicate_chunk_id", f"Duplicate chunk ID in manifest: {chunk_id}")
        result[chunk_id] = record
    return result


def flatten_ranges(ranges: Any, label: str) -> list[int]:
    pages: list[int] = []
    for value in ranges:
        if value[0] > value[1]:
            fail("invalid_chunk_manifest", f"Invalid range in {label}: {value}")
        pages.extend(range(value[0], value[1] + 1))
    return pages


def expected_chunk_pages(record: dict[str, Any]) -> tuple[list[int], list[int]]:
    return (
        flatten_ranges(record.get("owned_document_page_ranges"), "owned_document_page_ranges"),
        flatten_ranges(record.get("context_document_page_ranges", []), "context_document_page_ranges"),
    )


def validate_subject_artifact(
    artifact: dict[str, Any],
    artifact_path: Path,
    state: dict[str, Any],
    chunk_manifest: dict[str, Any],
    require_blindness: bool,
) -> dict[str, Any]:
    errors = schema_errors(artifact, "source-subject-chunk.schema.json")
    if errors:
        fail("invalid_worker_artifact", f"Source-subject artifact is structurally invalid: {artifact_path}", errors)
    errors = []
    if artifact.get("evaluation_id") != state.get("evaluation_id"):
        errors.append("evaluation_id does not match canonical state.")
    chunk = artifact["chunk"]
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

    page_review = artifact["page_review"]
    expected_count = len(expected_owned)
    if page_review.get("expected_owned_pages") != expected_count:
        errors.append("page_review.expected_owned_pages does not match chunk ownership.")
    if page_review.get("reviewed_owned_pages") != expected_count:
        errors.append("Every owned page must be recorded as reviewed.")
    if page_review.get("complete") is not True:
        errors.append("page_review.complete must be true.")
    word_count = page_review["indexable_source_words"]

    provenance = artifact["provenance"]
    subjects = artifact["subjects"]
    identifiers: set[str] = set()
    priorities = {key: 0 for key in ("essential", "major", "optional", "exclude_by_default")}
    evidence_count = 0
    owned_set = set(expected_owned)
    for index, subject in enumerate(subjects):
        identifier = subject["local_subject_id"]
        if identifier in identifiers:
            errors.append(f"Duplicate local_subject_id: {identifier}")
        else:
            identifiers.add(identifier)
        priority = subject.get("priority")
        priorities[priority] += 1
        evidence = subject["evidence"]
        for item in evidence:
            evidence_count += 1
            page = item.get("document_page")
            if page not in owned_set:
                errors.append(f"Evidence page must be owned by {chunk_id}: {page}")

    assessment = artifact.get("discovery_assessment")
    if assessment is not None:
        if assessment.get("subject_count") not in {None, len(subjects)}:
            errors.append("discovery_assessment.subject_count does not match subjects.")
        recorded_priorities = assessment.get("priority_counts")
        if recorded_priorities is not None:
            for key, value in priorities.items():
                if recorded_priorities.get(key, 0) != value:
                    errors.append(f"discovery_assessment.priority_counts.{key} does not match subjects.")
        if assessment.get("density_used_as_subject_quota") not in {None, False}:
            errors.append("Parallel discovery must not use density as a subject quota.")

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


def active_discovery_chunk_ids(state: dict[str, Any], root: Path) -> set[str]:
    active: set[str] = set()
    for item in state.get("artifacts", []):
        if not isinstance(item, dict) or item.get("artifact_type") != "source_subject_chunk":
            continue
        path = item.get("path")
        if not isinstance(path, str):
            continue
        local = root / safe_relative_path(path)
        if not local.is_file():
            continue
        artifact = load_json(local, "Registered source-subject artifact")
        chunk_id = artifact.get("chunk", {}).get("chunk_id")
        if isinstance(chunk_id, str):
            active.add(chunk_id)
    return active


def validated_inputs(args: argparse.Namespace) -> tuple[dict[str, Any], Path, dict[str, Any], list[tuple[Path, dict[str, Any], dict[str, Any]]]]:
    state_path = Path(args.state).resolve()
    state, root = load_run(state_path)
    state["_state_path"] = str(state_path)
    chunk_manifest = load_json(Path(args.chunk_manifest).resolve(), "Chunk manifest")
    structural = schema_errors(chunk_manifest, "chunk-manifest.schema.json")
    if structural:
        fail("invalid_chunk_manifest", "Chunk manifest is structurally invalid.", structural)
    chunk_records(chunk_manifest)
    supplied: list[tuple[Path, dict[str, Any], dict[str, Any]]] = []
    seen: set[str] = set()
    for value in args.artifact:
        source = Path(value).resolve()
        artifact = load_json(source, "Source-subject artifact")
        summary = validate_subject_artifact(
            artifact, source, state, chunk_manifest, require_blindness=not args.allow_compromised
        )
        chunk_id = summary["chunk_id"]
        if chunk_id in seen:
            fail("duplicate_integration_chunk", f"Chunk supplied more than once: {chunk_id}")
        seen.add(chunk_id)
        supplied.append((source, artifact, summary))
    return state, root, chunk_manifest, supplied


def command_validate_discoveries(args: argparse.Namespace) -> None:
    state, _, _, supplied = validated_inputs(args)
    emit({
        "command": "validate-discoveries",
        "ok": True,
        "evaluation_id": state["evaluation_id"],
        "validation": [summary for _, _, summary in supplied],
        "artifacts_written": [],
        "warnings": [],
    })


def command_register_discoveries(args: argparse.Namespace) -> None:
    state_path = Path(args.state).resolve()
    state, root, chunk_manifest, supplied = validated_inputs(args)
    expected_ids = set(chunk_records(chunk_manifest))

    new_state = deepcopy(state)
    new_state.pop("_state_path", None)
    stamp = now()
    planned_copies: list[tuple[Path, Path]] = []
    integrated: list[dict[str, Any]] = []
    for source, _, summary in supplied:
        chunk_id = summary["chunk_id"]
        relative = f"source/source-subject-chunk.{chunk_id}.json"
        destination = root / PurePosixPath(relative)
        digest = summary["artifact_sha256"]
        existing = next(
            (item for item in new_state.get("artifacts", []) if item.get("path") == relative),
            None,
        )
        if source != destination:
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
        new_state["artifacts"] = [item for item in new_state.get("artifacts", []) if item.get("path") != relative]
        new_state["artifacts"].append(record)
        integrated.append({"chunk_id": chunk_id, "path": relative, "sha256": digest})

    for source, destination in planned_copies:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    new_state["artifacts"].sort(key=lambda item: item.get("path", ""))
    active_ids = active_discovery_chunk_ids(new_state, root)
    missing = sorted(expected_ids - active_ids)
    stage = new_state["stages"]["source_subject_discovery"]
    stage["status"] = "completed" if not missing else "in_progress"
    stage["updated_at"] = stamp
    registered_ids = {summary["chunk_id"] for _, _, summary in supplied}
    note = f"Registered parallel source discoveries: {', '.join(sorted(registered_ids))}."
    if note not in stage.setdefault("notes", []):
        stage["notes"].append(note)
    new_state["updated_at"] = stamp
    save_state(state_path, new_state)

    emit({
        "command": "register-discoveries",
        "ok": True,
        "evaluation_id": new_state["evaluation_id"],
        "registered": sorted(integrated, key=lambda item: item["chunk_id"]),
        "source_subject_discovery_status": stage["status"],
        "active_chunk_count": len(active_ids),
        "expected_chunk_count": len(expected_ids),
        "missing_chunks": missing,
        "artifacts_written": [str(state_path)] + [item["path"] for item in integrated],
        "next_actions": ["continue_or_checkpoint"] if not missing else ["register_remaining_discoveries"],
        "warnings": [],
    })


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command, handler in (
        ("validate-discoveries", command_validate_discoveries),
        ("register-discoveries", command_register_discoveries),
    ):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--state", required=True)
        subparser.add_argument("--chunk-manifest", required=True)
        subparser.add_argument("--artifact", action="append", required=True)
        subparser.add_argument("--allow-compromised", action="store_true")
        subparser.set_defaults(func=handler)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "register-discoveries":
        with evaluation_mutation_lock(Path(args.state)):
            args.func(args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
