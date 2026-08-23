#!/usr/bin/env python3
"""Deterministic state manager for the evaluate-subject-index skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


LEGACY_STAGES_V3 = [
    "initialize",
    "page_mapping",
    "chunk_definition",
    "define_policy",
    "source_chunk_preparation",
    "source_subject_discovery",
    "benchmark_freeze",
    "candidate_normalization",
    "locator_chunk_preparation",
    "locator_audit",
    "missing_access_audit",
    "structure_audit",
    "scoring",
    "web_report",
]

STAGES = [
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

COMMANDS = {
    "initialize": "initialize",
    "page_mapping": "map-pages",
    "chunk_definition": "define-chunks",
    "define_policy": "define-policy",
    "source_chunk_preparation": "prepare-source-chunks",
    "source_subject_discovery": "discover-source-subjects",
    "benchmark_synthesis": "synthesize-source-benchmark",
    "benchmark_review": "review-source-benchmark",
    "benchmark_freeze": "freeze-source-benchmark",
    "candidate_normalization": "normalize-index",
    "locator_chunk_preparation": "prepare-locator-chunks",
    "locator_audit": "audit-locators",
    "missing_access_audit": "audit-missing-access",
    "structure_audit": "audit-index-structure",
    "scoring": "score-index",
    "web_report": "build-web-report",
}

REQUIRED_INPUTS = {
    "initialize": ["source file", "source title or inferable title", "document-page span"],
    "page_mapping": ["compact mapping from one-based document-page ranges to source page-label strings"],
    "chunk_definition": ["expanded page map", "user-approved owned and context document-page ranges"],
    "define_policy": ["initialized state", "source scope and availability facts", "page map", "chunk manifest", "built-in standard policy v1"],
    "source_chunk_preparation": ["source PDF", "expanded page map", "validated chunk manifest"],
    "source_subject_discovery": ["source chunk PDFs", "sidecar page maps", "frozen policy", "chunk manifest"],
    "benchmark_synthesis": ["all source-subject chunks", "whole-source synthesis pass", "provisional reader tasks"],
    "benchmark_review": ["candidate-blind benchmark draft", "independent review context", "benchmark review inventory", "exact source for contested judgments"],
    "benchmark_freeze": ["reviewed benchmark draft", "complete benchmark review ledger", "final canonical hash"],
    "candidate_normalization": ["original candidate index", "expanded page map", "deterministic item inventory"],
    "locator_chunk_preparation": ["normalized candidate", "expanded page map", "validated chunk manifest"],
    "locator_audit": ["source chunk PDF", "candidate locator chunk packet", "page sidecar"],
    "missing_access_audit": ["frozen benchmark", "normalized candidate", "locator judgments"],
    "structure_audit": ["complete locator and missing-access audits", "normalized whole index", "item inventory"],
    "scoring": ["all complete audit ledgers", "item inventory", "item grading v1", "rubric v4", "standard critical gates"],
    "web_report": ["validated evaluation result", "item assessments", "balanced representative examples"],
}

COMPLETION_TESTS = {
    "initialize": "State is valid; source identity, one-based document-page span, and inferred or supplied readership provenance are recorded.",
    "page_mapping": "Every document page has one mapping record and every indexable label resolves uniquely.",
    "chunk_definition": "The user approved the ranges, owned pages are unique, and every in-scope document page is owned.",
    "define_policy": "Standard policy v1 is source-bound, schema-valid, frozen, hashed, and any deviations are documented.",
    "source_chunk_preparation": "Every chunk PDF and sidecar map exists and preserves original document-page identity.",
    "source_subject_discovery": "Every owned source page was reviewed once and every chunk artifact is valid.",
    "benchmark_synthesis": "A candidate-blind whole-source draft consolidates all chunks, relationships, priorities, reader tasks, exclusions, uncertainties, and omission findings.",
    "benchmark_review": "An independent candidate-blind review covers every required subject, relationship, reader task, merge/split, priority, and omission check, with no undispositioned required item.",
    "benchmark_freeze": "The independently reviewed candidate-blind benchmark is versioned, schema-valid, canonically hashed, and frozen.",
    "candidate_normalization": "Every delivered record, complete path, expanded locator, heading node, and cross-reference has a stable ID in the candidate and item inventory.",
    "locator_chunk_preparation": "Every resolved locator is routed once and the routing exception ledger is empty.",
    "locator_audit": "Every expected expanded locator assignment has exactly one judgment.",
    "missing_access_audit": "Every scored benchmark subject and expected treatment has a coverage judgment.",
    "structure_audit": "The full hierarchy, every heading node and cross-reference, terminology, mechanics, density, and distribution are audited.",
    "scoring": "Diagnostic item grades, popover factors, overall score arithmetic, gates, denominators, hashes, and limitations validate.",
    "web_report": "The display payload validates and references frozen evidence IDs plus the exact item-assessment artifact and color/popover contract.",
}

VALID_STATUSES = {"not_started", "in_progress", "completed", "blocked"}
STATE_SCHEMA_VERSION = "subject-index-evaluation-state-v4"
LEGACY_STATE_SCHEMA_VERSION = "subject-index-evaluation-state-v3"
SUPPORTED_STATE_SCHEMA_VERSIONS = {LEGACY_STATE_SCHEMA_VERSION, STATE_SCHEMA_VERSION}
MANIFEST_SCHEMA_VERSION = "subject-index-artifact-manifest-v1"
MANIFEST_FILENAME = "artifact-manifest.json"
VALID_VISIBILITY = {"public", "private", "restricted"}
VALID_RETENTION = {"required", "cache"}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail("state_not_found", f"State file does not exist: {path}")
    except json.JSONDecodeError as exc:
        fail("invalid_json", f"Could not parse state JSON: {exc}")
    if not isinstance(data, dict):
        fail("invalid_state", "State root must be a JSON object.")
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def portable_relative_path(path: Path, root: Path) -> str:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    try:
        relative = resolved_path.relative_to(resolved_root)
    except ValueError:
        fail("artifact_outside_evaluation_directory", f"Artifact must be inside {resolved_root}: {resolved_path}")
    portable = PurePosixPath(relative.as_posix())
    if portable.is_absolute() or ".." in portable.parts or str(portable) in {"", "."}:
        fail("invalid_artifact_path", f"Artifact path is not portable: {relative}")
    return str(portable)


def resolve_artifact_path(state_path: Path, stored_path: str) -> Path:
    portable = PurePosixPath(stored_path)
    if portable.is_absolute() or ".." in portable.parts or stored_path in {"", "."}:
        raise ValueError(f"Artifact path is not portable: {stored_path}")
    return state_path.resolve().parent.joinpath(*portable.parts)


def manifest_path_for_state(state_path: Path, state: dict[str, Any]) -> Path:
    stored = str(state.get("artifact_manifest_path", MANIFEST_FILENAME))
    return resolve_artifact_path(state_path, stored)


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail("manifest_not_found", f"Artifact manifest does not exist: {path}")
    except json.JSONDecodeError as exc:
        fail("invalid_manifest_json", f"Could not parse artifact manifest JSON: {exc}")
    if not isinstance(manifest, dict):
        fail("invalid_manifest", "Artifact manifest root must be a JSON object.")
    return manifest


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def artifact_id(path: str, sha256: str) -> str:
    identity = hashlib.sha256(f"{path}\0{sha256}".encode("utf-8")).hexdigest()
    return f"ART-{identity[:12].upper()}"


def emit(payload: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(exit_code)


def fail(code: str, message: str, details: Any = None) -> None:
    payload = {"ok": False, "error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    emit(payload, 1)


def stages_for_state(state: dict[str, Any]) -> list[str]:
    if state.get("schema_version") == LEGACY_STATE_SCHEMA_VERSION:
        return LEGACY_STAGES_V3
    return STAGES


def stage_dependencies(stage: str, stage_order: list[str]) -> list[str]:
    index = stage_order.index(stage)
    return stage_order[:index]


def validate_state(state: dict[str, Any], state_path: Path | None = None, check_files: bool = True) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for key in ("schema_version", "evaluation_id", "artifact_manifest_path", "source", "configuration", "stages", "artifacts", "blockers"):
        if key not in state:
            errors.append(f"Missing required key: {key}")
    if state.get("schema_version") not in SUPPORTED_STATE_SCHEMA_VERSIONS:
        errors.append("Unsupported schema_version.")
    if state.get("configuration", {}).get("storage_mode") not in {"local", "library", "hybrid"}:
        errors.append("configuration.storage_mode must be local, library, or hybrid.")
    readership = state.get("configuration", {}).get("readership_provenance")
    if readership is None:
        warnings.append("Legacy state has no readership provenance; record it when defining policy.")
    elif readership.get("basis") not in {"inferred", "user_supplied"}:
        errors.append("configuration.readership_provenance.basis must be inferred or user_supplied.")
    elif readership.get("confidence") not in {"high", "medium", "low"}:
        errors.append("configuration.readership_provenance.confidence must be high, medium, or low.")

    stages = state.get("stages", {})
    if not isinstance(stages, dict):
        errors.append("stages must be an object.")
        stages = {}
    stage_order = stages_for_state(state)
    for name in stage_order:
        record = stages.get(name)
        if not isinstance(record, dict):
            errors.append(f"Missing stage record: {name}")
            continue
        if record.get("status") not in VALID_STATUSES:
            errors.append(f"Invalid status for {name}: {record.get('status')}")

    completed_prefix = True
    for name in stage_order:
        status = stages.get(name, {}).get("status")
        if status == "completed" and not completed_prefix:
            errors.append(f"Stage {name} is completed before all dependencies are complete.")
        if status != "completed":
            completed_prefix = False

    span = state.get("source", {}).get("document_page_span") if isinstance(state.get("source"), dict) else None
    if not (isinstance(span, list) and len(span) == 2 and all(isinstance(v, int) for v in span) and span[0] <= span[1]):
        errors.append("source.document_page_span must be an ascending pair of integers.")

    artifacts = state.get("artifacts", [])
    if not isinstance(artifacts, list):
        errors.append("artifacts must be an array.")
        artifacts = []
    seen_paths: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            errors.append("Each artifact must be an object.")
            continue
        stored_path = str(artifact.get("path", ""))
        if stored_path in seen_paths:
            errors.append(f"Duplicate artifact path: {stored_path}")
        seen_paths.add(stored_path)
        if artifact.get("visibility") not in VALID_VISIBILITY:
            errors.append(f"Invalid artifact visibility: {stored_path}")
        if artifact.get("retention") not in VALID_RETENTION:
            errors.append(f"Invalid artifact retention: {stored_path}")
        try:
            artifact_path = resolve_artifact_path(state_path, stored_path) if state_path else Path(stored_path)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if check_files and not artifact_path.is_file():
            warnings.append(f"Artifact is not currently accessible: {stored_path}")
        elif check_files:
            actual = sha256_file(artifact_path)
            recorded = artifact.get("sha256")
            if recorded and actual != recorded:
                errors.append(f"Artifact hash mismatch: {stored_path}")

    if state_path:
        try:
            manifest_path = manifest_path_for_state(state_path, state)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"Artifact manifest is unavailable or invalid: {exc}")
        else:
            if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
                errors.append("Unsupported artifact manifest schema_version.")
            if manifest.get("evaluation_id") != state.get("evaluation_id"):
                errors.append("Artifact manifest evaluation_id does not match state.")
            state_artifacts = {(item.get("path"), item.get("sha256")) for item in artifacts if isinstance(item, dict)}
            manifest_artifacts = {
                (item.get("path"), item.get("sha256"))
                for item in manifest.get("artifacts", [])
                if isinstance(item, dict)
            }
            if state_artifacts != manifest_artifacts:
                errors.append("State and artifact manifest inventories do not match.")

    artifact_stages = {item.get("stage") for item in artifacts if isinstance(item, dict)}
    for name in stage_order[1:]:
        artifact_present = name in artifact_stages
        if name == "benchmark_synthesis":
            artifact_present = artifact_present or "benchmark_freeze" in artifact_stages
        if stages.get(name, {}).get("status") == "completed" and not artifact_present:
            errors.append(f"Completed stage has no registered artifact: {name}")

    active = [name for name in stage_order if stages.get(name, {}).get("status") == "in_progress"]
    if len(active) > 1:
        errors.append(f"More than one stage is in progress: {active}")
    return errors, warnings


def next_stage(state: dict[str, Any]) -> dict[str, Any] | None:
    stages = state["stages"]
    stage_order = stages_for_state(state)
    for name in stage_order:
        status = stages[name]["status"]
        if status == "completed":
            continue
        deps = stage_dependencies(name, stage_order)
        unmet = [dep for dep in deps if stages[dep]["status"] != "completed"]
        return {
            "stage": name,
            "command": COMMANDS[name],
            "status": status,
            "available": not unmet and status != "blocked",
            "unmet_dependencies": unmet,
            "required_inputs": REQUIRED_INPUTS[name],
            "completion_test": COMPLETION_TESTS[name],
        }
    return None


def state_summary(state: dict[str, Any], state_path: Path | None = None) -> dict[str, Any]:
    errors, warnings = validate_state(state, state_path=state_path)
    stages = state.get("stages", {})
    stage_order = stages_for_state(state)
    current = next((name for name in stage_order if stages.get(name, {}).get("status") == "in_progress"), None)
    if current is None:
        current = next((name for name in stage_order if stages.get(name, {}).get("status") != "completed"), "complete")
    return {
        "ok": not errors,
        "evaluation_id": state.get("evaluation_id"),
        "storage_mode": state.get("configuration", {}).get("storage_mode"),
        "state": current,
        "completed_stages": [name for name in stage_order if stages.get(name, {}).get("status") == "completed"],
        "blocked_stages": [name for name in stage_order if stages.get(name, {}).get("status") == "blocked"],
        "artifacts": state.get("artifacts", []),
        "blockers": state.get("blockers", []),
        "next_actions": [] if next_stage(state) is None else [next_stage(state)],
        "errors": errors,
        "warnings": warnings,
    }


def command_init(args: argparse.Namespace) -> None:
    output = Path(args.output).resolve()
    if output.exists() and not args.force:
        fail("state_exists", f"Refusing to overwrite existing state: {output}")
    source_path = Path(args.source_file).resolve()
    source_hash = sha256_file(source_path)
    if source_hash is None:
        fail("source_not_found", f"Source file does not exist: {source_path}")
    stamp = now()
    stages = {
        name: {
            "status": "completed" if name == "initialize" else "not_started",
            "updated_at": stamp if name == "initialize" else None,
            "notes": [],
        }
        for name in STAGES
    }
    blockers = []
    state = {
        "schema_version": STATE_SCHEMA_VERSION,
        "evaluation_id": args.evaluation_id,
        "artifact_manifest_path": MANIFEST_FILENAME,
        "created_at": stamp,
        "updated_at": stamp,
        "source": {
            "title": args.source_title,
            "filename": source_path.name,
            "sha256": source_hash,
            "document_page_span": [args.document_page_start, args.document_page_end],
            "document_page_basis": "one_based_inclusive",
        },
        "candidate": None,
        "configuration": {
            "audit_mode": args.audit_mode,
            "index_type": "subject_index",
            "intended_readership": args.intended_readership,
            "readership_provenance": {
                "basis": args.readership_basis,
                "confidence": args.readership_confidence,
                "rationale": args.readership_rationale,
            },
            "output_format": "json",
            "storage_mode": args.storage_mode,
            "chunking": {"primary": "chapter", "maximum_pages": 60, "context_overlap_pages": 2},
            "policy_profile": "subject-index-standard-policy-v1",
            "rubric_version": "subject-index-rubric-v4",
        },
        "stages": stages,
        "artifacts": [],
        "blockers": blockers,
    }
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluation_id": args.evaluation_id,
        "created_at": stamp,
        "updated_at": stamp,
        "artifacts": [],
    }
    save_manifest(output.parent / MANIFEST_FILENAME, manifest)
    save_state(output, state)
    payload = state_summary(state, output)
    payload.update({
        "command": "initialize",
        "state_path": str(output),
        "artifacts_written": [str(output), str(output.parent / MANIFEST_FILENAME)],
    })
    emit(payload)


def command_status(args: argparse.Namespace) -> None:
    state_path = Path(args.state)
    state = load_state(state_path)
    payload = state_summary(state, state_path)
    payload["command"] = "status"
    emit(payload, 0 if payload["ok"] else 1)


def command_next(args: argparse.Namespace) -> None:
    state_path = Path(args.state)
    state = load_state(state_path)
    errors, warnings = validate_state(state, state_path=state_path)
    payload = {
        "command": "next",
        "ok": not errors,
        "evaluation_id": state.get("evaluation_id"),
        "next_actions": [] if next_stage(state) is None else [next_stage(state)],
        "errors": errors,
        "warnings": warnings,
    }
    emit(payload, 0 if payload["ok"] else 1)


def command_set_stage(args: argparse.Namespace) -> None:
    state_path = Path(args.state)
    state = load_state(state_path)
    stage_order = stages_for_state(state)
    if args.stage not in stage_order:
        fail("unknown_stage", f"Unknown stage: {args.stage}")
    unmet = [dep for dep in stage_dependencies(args.stage, stage_order) if state["stages"][dep]["status"] != "completed"]
    if args.status in {"in_progress", "completed"} and unmet:
        fail("unmet_dependencies", f"Cannot set {args.stage} to {args.status}.", unmet)
    if args.status == "in_progress":
        active = [name for name in stage_order if state["stages"][name]["status"] == "in_progress" and name != args.stage]
        if active:
            fail("another_stage_active", "Only one stage may be in progress.", active)
    if args.status == "completed" and not args.artifact_path:
        has_registered = any(item.get("stage") == args.stage for item in state.get("artifacts", []))
        if args.stage != "initialize" and not has_registered:
            fail("completion_artifact_required", f"Cannot complete {args.stage} without a registered artifact.")
    stamp = now()
    record = state["stages"][args.stage]
    record["status"] = args.status
    record["updated_at"] = stamp
    if args.note:
        record.setdefault("notes", []).append(args.note)
    artifacts_written: list[str] = []
    if args.artifact_path:
        artifact_path = Path(args.artifact_path).resolve()
        relative_path = portable_relative_path(artifact_path, state_path.resolve().parent)
        artifact_hash = sha256_file(artifact_path)
        if artifact_hash is None:
            fail("artifact_not_found", f"Artifact file does not exist: {artifact_path}")
        if artifact_path.suffix.lower() == ".json":
            try:
                json.loads(artifact_path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                fail("invalid_artifact_json", f"JSON artifact is invalid: {exc}")
        manifest_path = manifest_path_for_state(state_path, state)
        manifest = load_manifest(manifest_path)
        previous = next((item for item in manifest.get("artifacts", []) if item.get("path") == relative_path), None)
        if previous and previous.get("frozen") and previous.get("sha256") != artifact_hash:
            fail(
                "frozen_artifact_changed",
                "Refusing to overwrite a frozen artifact with different bytes; use a versioned path.",
                {"path": relative_path, "previous_sha256": previous.get("sha256"), "new_sha256": artifact_hash},
            )
        guessed_type = mimetypes.guess_type(artifact_path.name)[0] or "application/octet-stream"
        record = {
            "artifact_id": artifact_id(relative_path, artifact_hash),
            "stage": args.stage,
            "artifact_type": args.artifact_type or artifact_path.stem,
            "path": relative_path,
            "sha256": artifact_hash,
            "media_type": args.media_type or guessed_type,
            "visibility": args.visibility,
            "retention": args.retention,
            "frozen": args.frozen,
            "recorded_at": stamp,
        }
        if previous and previous.get("sha256") != artifact_hash:
            record["supersedes"] = previous.get("artifact_id")
        artifact = {
            key: record[key]
            for key in ("artifact_id", "stage", "artifact_type", "path", "sha256", "visibility", "retention", "frozen", "recorded_at")
        }
        state["artifacts"] = [
            item for item in state.get("artifacts", [])
            if item.get("path") != relative_path
        ]
        state["artifacts"].append(artifact)
        manifest["artifacts"] = [item for item in manifest.get("artifacts", []) if item.get("path") != relative_path]
        manifest["artifacts"].append(record)
        manifest["artifacts"].sort(key=lambda item: item["path"])
        manifest["updated_at"] = stamp
        save_manifest(manifest_path, manifest)
        artifacts_written.append(relative_path)
    state["updated_at"] = stamp
    save_state(state_path, state)
    payload = state_summary(state, state_path)
    payload.update({"command": "set-stage", "updated_stage": args.stage, "artifacts_written": artifacts_written})
    emit(payload, 0 if payload["ok"] else 1)


def command_validate(args: argparse.Namespace) -> None:
    state_path = Path(args.state)
    state = load_state(state_path)
    errors, warnings = validate_state(state, state_path=state_path, check_files=not args.skip_files)
    emit({
        "command": "validate",
        "ok": not errors,
        "evaluation_id": state.get("evaluation_id"),
        "errors": errors,
        "warnings": warnings,
    }, 0 if not errors else 1)


def command_adopt_standard_policy(args: argparse.Namespace) -> None:
    state_path = Path(args.state)
    state = load_state(state_path)
    policy_stage = state.get("stages", {}).get("define_policy", {}).get("status")
    stage_order = stages_for_state(state)
    later_started = [
        name for name in stage_order[stage_order.index("source_chunk_preparation"):]
        if state.get("stages", {}).get(name, {}).get("status") != "not_started"
    ]
    if policy_stage == "completed" or later_started:
        fail(
            "policy_already_frozen_or_used",
            "Adopt the standard policy only before policy freeze and candidate-independent downstream work.",
            {"policy_stage": policy_stage, "later_started": later_started},
        )
    configuration = state.setdefault("configuration", {})
    if args.intended_readership:
        configuration["intended_readership"] = args.intended_readership
    configuration["readership_provenance"] = {
        "basis": args.readership_basis,
        "confidence": args.readership_confidence,
        "rationale": args.readership_rationale,
    }
    configuration["policy_profile"] = "subject-index-standard-policy-v1"
    configuration["rubric_version"] = "subject-index-rubric-v4"
    state["updated_at"] = now()
    save_state(state_path, state)
    payload = state_summary(state, state_path)
    payload.update({
        "command": "adopt-standard-policy",
        "policy_profile": configuration["policy_profile"],
        "rubric_version": configuration["rubric_version"],
        "state_path": str(state_path.resolve()),
    })
    emit(payload, 0 if payload["ok"] else 1)


def command_upgrade_benchmark_workflow(args: argparse.Namespace) -> None:
    state_path = Path(args.state)
    state = load_state(state_path)
    if state.get("schema_version") == STATE_SCHEMA_VERSION:
        payload = state_summary(state, state_path)
        payload.update({"command": "upgrade-benchmark-workflow", "changed": False})
        emit(payload, 0 if payload["ok"] else 1)
    if state.get("schema_version") != LEGACY_STATE_SCHEMA_VERSION:
        fail("unsupported_upgrade_source", "Only v3 evaluation states can be upgraded to the reviewed-benchmark workflow.")
    later_started = [
        name for name in LEGACY_STAGES_V3[LEGACY_STAGES_V3.index("candidate_normalization"):]
        if state.get("stages", {}).get(name, {}).get("status") != "not_started"
    ]
    if later_started:
        fail(
            "candidate_work_already_started",
            "Upgrade the benchmark workflow before candidate normalization or later candidate work.",
            later_started,
        )
    stamp = now()
    old_stages = state["stages"]
    old_freeze = old_stages.get("benchmark_freeze", {"status": "not_started", "updated_at": None, "notes": []})
    if old_freeze.get("status") == "completed":
        synthesis_status = "completed"
        synthesis_notes = list(old_freeze.get("notes", [])) + [
            "Legacy frozen benchmark adopted as the candidate-blind synthesis baseline for independent post-freeze review."
        ]
    else:
        synthesis_status = old_freeze.get("status", "not_started")
        synthesis_notes = list(old_freeze.get("notes", []))
    new_stages: dict[str, Any] = {}
    for name in STAGES:
        if name == "benchmark_synthesis":
            new_stages[name] = {
                "status": synthesis_status,
                "updated_at": stamp if synthesis_status == "completed" else old_freeze.get("updated_at"),
                "notes": synthesis_notes,
            }
        elif name == "benchmark_review":
            new_stages[name] = {
                "status": "not_started",
                "updated_at": None,
                "notes": ["Independent candidate-blind benchmark review required before final freeze."],
            }
        elif name == "benchmark_freeze":
            new_stages[name] = {
                "status": "not_started",
                "updated_at": None,
                "notes": ["Final freeze must follow completed independent benchmark review."],
            }
        else:
            new_stages[name] = old_stages[name]
    state["schema_version"] = STATE_SCHEMA_VERSION
    state["stages"] = new_stages
    state["updated_at"] = stamp
    save_state(state_path, state)
    payload = state_summary(state, state_path)
    payload.update({"command": "upgrade-benchmark-workflow", "changed": True, "state_path": str(state_path.resolve())})
    emit(payload, 0 if payload["ok"] else 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create evaluation-state.json")
    init_parser.add_argument("--output", required=True)
    init_parser.add_argument("--evaluation-id", required=True)
    init_parser.add_argument("--source-title", required=True)
    init_parser.add_argument("--source-file", required=True)
    init_parser.add_argument("--document-page-start", "--page-start", dest="document_page_start", type=int, required=True)
    init_parser.add_argument("--document-page-end", "--page-end", dest="document_page_end", type=int, required=True)
    init_parser.add_argument("--intended-readership", required=True)
    init_parser.add_argument("--readership-basis", choices=["inferred", "user_supplied"], default="inferred")
    init_parser.add_argument("--readership-confidence", choices=["high", "medium", "low"], default="medium")
    init_parser.add_argument(
        "--readership-rationale",
        default="Inferred from the source's genre, publisher, terminology, and presentation.",
    )
    init_parser.add_argument("--audit-mode", choices=["full", "pilot"], default="full")
    init_parser.add_argument("--storage-mode", choices=["local", "library", "hybrid"], default="local")
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(func=command_init)

    for name, function in (("status", command_status), ("next", command_next)):
        sub = subparsers.add_parser(name)
        sub.add_argument("--state", required=True)
        sub.set_defaults(func=function)

    set_parser = subparsers.add_parser("set-stage", help="Update one stage after dependency checks")
    set_parser.add_argument("--state", required=True)
    set_parser.add_argument("--stage", required=True, choices=sorted(set(STAGES + LEGACY_STAGES_V3)))
    set_parser.add_argument("--status", required=True, choices=sorted(VALID_STATUSES))
    set_parser.add_argument("--artifact-type")
    set_parser.add_argument("--artifact-path")
    set_parser.add_argument("--media-type")
    set_parser.add_argument("--visibility", choices=sorted(VALID_VISIBILITY), default="private")
    set_parser.add_argument("--retention", choices=sorted(VALID_RETENTION), default="required")
    set_parser.add_argument("--frozen", action="store_true")
    set_parser.add_argument("--note")
    set_parser.set_defaults(func=command_set_stage)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--state", required=True)
    validate_parser.add_argument("--skip-files", action="store_true")
    validate_parser.set_defaults(func=command_validate)

    adopt_parser = subparsers.add_parser("adopt-standard-policy")
    adopt_parser.add_argument("--state", required=True)
    adopt_parser.add_argument("--intended-readership")
    adopt_parser.add_argument("--readership-basis", choices=["inferred", "user_supplied"], required=True)
    adopt_parser.add_argument("--readership-confidence", choices=["high", "medium", "low"], required=True)
    adopt_parser.add_argument("--readership-rationale", required=True)
    adopt_parser.set_defaults(func=command_adopt_standard_policy)

    upgrade_parser = subparsers.add_parser("upgrade-benchmark-workflow")
    upgrade_parser.add_argument("--state", required=True)
    upgrade_parser.set_defaults(func=command_upgrade_benchmark_workflow)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "document_page_start", 0) and args.document_page_end < args.document_page_start:
        fail("invalid_page_span", "document-page-end must be greater than or equal to document-page-start.")
    args.func(args)


if __name__ == "__main__":
    main()
