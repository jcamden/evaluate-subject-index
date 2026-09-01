#!/usr/bin/env python3
"""Deterministic state manager for the evaluate-subject-index skill."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import mimetypes
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


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
    "scoring": ["all complete audit ledgers", "strict V5 scoring context or migration supplement", "dimension calculation profile v1", "item grading v1 kept non-additive", "standard critical gates kept outside arithmetic"],
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
    "scoring": "V5 dimension calculations derive from validated ledgers, expose complete formula provenance and stable uncertainty bounds, and keep item grades and gates outside arithmetic.",
    "web_report": "The display payload validates and references frozen evidence IDs plus the exact item-assessment artifact and color/popover contract.",
}

VALID_STATUSES = {"not_started", "in_progress", "completed", "blocked"}
STATE_SCHEMA_VERSION = "subject-index-evaluation-state-v4"
SUPPORTED_STATE_SCHEMA_VERSIONS = {STATE_SCHEMA_VERSION}
MANIFEST_SCHEMA_VERSION = "subject-index-artifact-manifest-v1"
MANIFEST_FILENAME = "artifact-manifest.json"
VALID_VISIBILITY = {"public", "private", "restricted"}
VALID_RETENTION = {"required", "cache"}
PUBLICATION_PROFILES = {"aggregate_only", "public_evaluation_artifacts"}
SCORE_RUBRIC_VERSION = "subject-index-rubric-v5"
DIMENSION_CALCULATION_PROFILE = "subject-index-dimension-calculation-v1"


def artifact_matches_active_scoring_identity(state: dict[str, Any], artifact: dict[str, Any], stage: str) -> bool:
    if artifact.get("stage") != stage:
        return False
    if stage not in {"scoring", "web_report"}:
        return True
    # Pre-Phase-2 states have no activation marker. They remain readable as
    # history, but the first explicit profile change records an epoch and
    # deactivates them before either stage can be completed again.
    if state.get("configuration", {}).get("scoring_identity") is None:
        return artifact.get("active_for_scoring_identity") is not False
    return (
        artifact.get("active_for_scoring_identity") is True
        and artifact.get("scoring_identity") == state.get("configuration", {}).get("scoring_identity")
    )


def artifact_is_active_for_stage(state: dict[str, Any], artifact: dict[str, Any], stage: str) -> bool:
    return artifact_matches_active_scoring_identity(state, artifact, stage) and (
        stage not in {"scoring", "web_report"}
        or state.get("configuration", {}).get("scoring_identity") is None
        or artifact.get("stage_completion_eligible") is True
    )


def require_calculation_matches_state(calculation: dict[str, Any], calculation_path: Path, state: dict[str, Any], state_path: Path) -> None:
    from dimension_score_cli import calculate_loaded, load_inputs, validate_migration_record_for_calculation

    identity = calculation.get("evidence_identity") if isinstance(calculation.get("evidence_identity"), dict) else {}
    candidate = state.get("candidate") if isinstance(state.get("candidate"), dict) else {}
    checks = (
        ("evaluation_id", calculation.get("evaluation_id"), state.get("evaluation_id")),
        ("audit_mode", calculation.get("audit_mode"), state.get("configuration", {}).get("audit_mode")),
        ("source_sha256", identity.get("source_sha256"), state.get("source", {}).get("sha256")),
        ("candidate_sha256", identity.get("candidate_sha256"), candidate.get("sha256")),
    )
    mismatches = [
        {"field": field, "calculation": actual, "state": expected}
        for field, actual, expected in checks
        if not isinstance(expected, str) or not expected or actual != expected
    ]
    if mismatches:
        fail("scoring_artifact_state_identity_mismatch", "The V5 calculation does not belong to canonical state.", mismatches)
    history = state.get("configuration", {}).get("score_profile_history")
    if not isinstance(history, list) or not history:
        fail("score_profile_history_required", "Active V5 scoring requires the authoritative profile-adoption preflight history.")
    adoption = history[-1]
    preflight_path = resolve_artifact_path(state_path, adoption["preflight_path"])
    if sha256_file(preflight_path) != adoption.get("preflight_sha256"):
        fail("score_profile_preflight_changed", "The adopted V5 preflight bytes no longer match state history.")
    try:
        preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail("score_profile_preflight_invalid", "The adopted V5 preflight is unavailable or invalid.", str(exc))
    if preflight.get("sufficient") is not True or calculation.get("input_artifacts") != preflight.get("input_artifacts"):
        fail("scoring_artifact_preflight_mismatch", "The V5 calculation inputs do not exactly match the authoritative adopted preflight.")
    calculation_input_path = resolve_artifact_path(state_path, adoption["calculation_input_path"])
    if sha256_file(calculation_input_path) != adoption.get("calculation_input_sha256"):
        fail("score_profile_calculation_input_changed", "The adopted V5 calculation-input bytes no longer match state history.")
    loaded = load_inputs(calculation_input_path)
    historical_structure = loaded.get("structure", {}).get("schema_version") == "structure-audit-v3"
    authoritative = calculate_loaded(loaded, allow_historical_migration=historical_structure)
    migration_context = calculation.get("migration_context")
    if historical_structure and not isinstance(migration_context, dict):
        fail("score_only_migration_required", "Historical structure-audit-v3 inputs require an exact V4 score-only migration and preserved gate outcomes.")
    if migration_context is not None:
        validate_migration_record_for_calculation(calculation, calculation_path, loaded=loaded)
    submitted_comparable = deepcopy(calculation)
    authoritative_comparable = deepcopy(authoritative)
    submitted_comparable.pop("calculation_sha256", None)
    submitted_comparable.pop("migration_context", None)
    authoritative_comparable.pop("calculation_sha256", None)
    if submitted_comparable != authoritative_comparable:
        fail("scoring_artifact_reconstruction_mismatch", "The submitted V5 calculation does not exactly reconstruct from the adopted frozen inputs.")


def require_profile_bound_stage_artifact(
    document: dict[str, Any],
    artifact_path: Path,
    stage: str,
    scoring_identity: dict[str, Any],
    state: dict[str, Any],
    state_path: Path,
) -> bool:
    """Authoritatively validate a V5 output and return completion eligibility."""
    from dimension_score_cli import (  # Imported lazily to keep basic state commands lightweight.
        CalculationError,
        canonical_hash,
        validate_projection_artifacts,
        validate_schema_document,
    )

    schema_version = document.get("schema_version")
    try:
        if stage == "scoring" and schema_version == "subject-index-dimension-calculations-v1":
            validate_schema_document(document, "dimension-calculations.schema.json", "Active V5 dimension calculation")
            if document.get("calculation_sha256") != canonical_hash(document, "calculation_sha256"):
                raise CalculationError("calculation_self_hash_mismatch", "The active V5 calculation self-hash does not reconstruct.")
            require_calculation_matches_state(document, artifact_path, state, state_path)
            rubric_version = document.get("rubric_version")
            profile = document.get("calculation_profile")
            completion_eligible = False
        elif stage == "scoring" and schema_version == "subject-index-evaluation-result-v6":
            validate_schema_document(document, "evaluation-result-v6.schema.json", "Active V5 evaluation result")
            provenance = document.get("provenance") if isinstance(document.get("provenance"), dict) else {}
            rubric_version = provenance.get("rubric_version")
            profile = provenance.get("dimension_calculation_profile")
            calculation_reference = document["dimension_calculations"]["artifact_path"]
            calculation_path = (Path(calculation_reference) if Path(calculation_reference).is_absolute() else artifact_path.parent / calculation_reference).resolve()
            calculation_hash = sha256_file(calculation_path)
            registered_calculations = [
                record
                for record in state.get("artifacts", [])
                if isinstance(record, dict)
                and artifact_matches_active_scoring_identity(state, record, "scoring")
                and resolve_artifact_path(state_path, record["path"]) == calculation_path
                and record.get("sha256") == calculation_hash
            ]
            if len(registered_calculations) != 1:
                raise CalculationError("active_v5_calculation_required", "The result's exact calculation path and hash must already be registered for the active score identity.", registered_calculations)
            validate_projection_artifacts(calculation_path, artifact_path)
            calculation_document = json.loads(calculation_path.read_text(encoding="utf-8"))
            require_calculation_matches_state(calculation_document, calculation_path, state, state_path)
            completion_eligible = True
        elif stage == "scoring":
            fail("active_v5_scoring_artifact_required", "Scoring requires a schema-valid V5 dimension calculation or V5 evaluation result; only a validated result can complete the stage.", {"schema_version": schema_version})
        elif stage == "web_report" and schema_version == "subject-index-web-report-v4":
            validate_schema_document(document, "web-report-v4.schema.json", "Active V5 web report")
            explainer = document.get("calculation_explainer") if isinstance(document.get("calculation_explainer"), dict) else {}
            rubric_version = explainer.get("rubric_version")
            profile = explainer.get("calculation_profile")
            calculation_reference = explainer["artifact_path"]
            calculation_path = (Path(calculation_reference) if Path(calculation_reference).is_absolute() else artifact_path.parent / calculation_reference).resolve()
            calculation_document = json.loads(calculation_path.read_text(encoding="utf-8"))
            require_calculation_matches_state(calculation_document, calculation_path, state, state_path)
            result_candidates: list[Path] = []
            for record in state.get("artifacts", []):
                if not isinstance(record, dict) or not artifact_is_active_for_stage(state, record, "scoring"):
                    continue
                candidate_path = resolve_artifact_path(state_path, record["path"])
                try:
                    candidate_document = json.loads(candidate_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if candidate_document.get("schema_version") != "subject-index-evaluation-result-v6":
                    continue
                bound = candidate_document.get("dimension_calculations", {}).get("artifact_path")
                if not isinstance(bound, str):
                    continue
                bound_path = (Path(bound) if Path(bound).is_absolute() else candidate_path.parent / bound).resolve()
                if bound_path == calculation_path:
                    result_candidates.append(candidate_path)
            if len(result_candidates) != 1:
                raise CalculationError("active_v5_evaluation_result_required", "Web-report validation requires exactly one active V5 evaluation result bound to the same calculation.", [str(item) for item in result_candidates])
            validate_projection_artifacts(calculation_path, result_candidates[0], artifact_path)
            completion_eligible = True
        elif stage == "web_report":
            fail("active_v5_web_report_required", "Web-report completion requires a schema-valid V5 web report whose projections validate against the active result.", {"schema_version": schema_version})
        else:
            return True
    except (CalculationError, OSError, KeyError) as exc:
        if isinstance(exc, CalculationError):
            details = {"code": exc.code, "message": exc.message, "details": exc.details}
        else:
            details = {"message": str(exc)}
        fail("invalid_profile_bound_artifact", f"The {stage} artifact failed authoritative V5 validation.", details)

    expected_rubric = scoring_identity.get("rubric_version")
    expected_profile = scoring_identity.get("dimension_calculation_profile")
    if rubric_version != expected_rubric or profile != expected_profile:
        fail(
            "scoring_artifact_identity_mismatch",
            f"The {stage} artifact does not bind the active score identity.",
            {
                "expected": scoring_identity,
                "actual": {"rubric_version": rubric_version, "dimension_calculation_profile": profile},
            },
        )
    return completion_eligible


@contextmanager
def evaluation_mutation_lock(state_path: Path):
    """Share the canonical evaluation lock with every state/manifest writer."""
    lock_path = state_path.resolve().parent / ".candidate-preparation-integration.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail("evaluation_lock_busy", "Another process owns the canonical evaluation lock.")
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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
    return STAGES


def stage_dependencies(stage: str, stage_order: list[str]) -> list[str]:
    index = stage_order.index(stage)
    return stage_order[:index]


def validate_state(
    state: dict[str, Any],
    state_path: Path | None = None,
    check_files: bool = True,
    manifest_document: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for key in ("schema_version", "evaluation_id", "artifact_manifest_path", "source", "configuration", "stages", "artifacts", "blockers"):
        if key not in state:
            errors.append(f"Missing required key: {key}")
    if state.get("schema_version") not in SUPPORTED_STATE_SCHEMA_VERSIONS:
        errors.append("Unsupported schema_version.")
    if state.get("configuration", {}).get("storage_mode") not in {"local", "library", "hybrid"}:
        errors.append("configuration.storage_mode must be local, library, or hybrid.")
    publication_profile = state.get("configuration", {}).get("publication_profile", "aggregate_only")
    if publication_profile not in PUBLICATION_PROFILES:
        errors.append(
            "configuration.publication_profile must be aggregate_only or public_evaluation_artifacts."
        )
    readership = state.get("configuration", {}).get("readership_provenance")
    if readership is None:
        warnings.append("Legacy state has no readership provenance; record it when defining policy.")
    elif readership.get("basis") not in {"inferred", "user_supplied"}:
        errors.append("configuration.readership_provenance.basis must be inferred or user_supplied.")
    elif readership.get("confidence") not in {"high", "medium", "low"}:
        errors.append("configuration.readership_provenance.confidence must be high, medium, or low.")
    scoring_identity = state.get("configuration", {}).get("scoring_identity")
    if scoring_identity is None:
        warnings.append("Legacy state has no decoupled scoring identity; run the V5 sufficiency preflight before score-only migration.")
    elif not isinstance(scoring_identity, dict):
        errors.append("configuration.scoring_identity must be an object.")
    else:
        if scoring_identity.get("rubric_version") != SCORE_RUBRIC_VERSION:
            errors.append(f"configuration.scoring_identity.rubric_version must be {SCORE_RUBRIC_VERSION}.")
        if scoring_identity.get("dimension_calculation_profile") != DIMENSION_CALCULATION_PROFILE:
            errors.append(f"configuration.scoring_identity.dimension_calculation_profile must be {DIMENSION_CALCULATION_PROFILE}.")

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
        if artifact.get("active_for_scoring_identity") is True:
            if artifact.get("stage") not in {"scoring", "web_report"}:
                errors.append(f"Only scoring/web-report artifacts may be active for score identity: {stored_path}")
            elif artifact.get("scoring_identity") != scoring_identity:
                errors.append(f"Active artifact score identity mismatch: {stored_path}")
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
            manifest = manifest_document if manifest_document is not None else json.loads(manifest_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"Artifact manifest is unavailable or invalid: {exc}")
        else:
            if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
                errors.append("Unsupported artifact manifest schema_version.")
            if manifest.get("evaluation_id") != state.get("evaluation_id"):
                errors.append("Artifact manifest evaluation_id does not match state.")
            binding_keys = (
                "path", "sha256", "stage", "artifact_type", "frozen", "retention",
                "active_for_scoring_identity", "scoring_identity", "stage_completion_eligible",
            )
            state_artifacts = {
                tuple(json.dumps(item.get(key), sort_keys=True) for key in binding_keys)
                for item in artifacts
                if isinstance(item, dict)
            }
            manifest_artifacts = {
                tuple(json.dumps(item.get(key), sort_keys=True) for key in binding_keys)
                for item in manifest.get("artifacts", [])
                if isinstance(item, dict)
            }
            if state_artifacts != manifest_artifacts:
                errors.append("State and artifact manifest inventories do not match.")

    for name in stage_order[1:]:
        artifact_present = any(
            artifact_is_active_for_stage(state, item, name)
            for item in artifacts
            if isinstance(item, dict)
        )
        if name == "benchmark_synthesis":
            artifact_present = artifact_present or any(
                artifact_is_active_for_stage(state, item, "benchmark_freeze")
                for item in artifacts
                if isinstance(item, dict)
            )
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


def candidate_preparation_action(state: dict[str, Any]) -> dict[str, Any]:
    """Describe the auxiliary preparation lane without changing canonical stage order."""
    missing: list[str] = []
    source = state.get("source", {}) if isinstance(state.get("source"), dict) else {}
    configuration = state.get("configuration", {}) if isinstance(state.get("configuration"), dict) else {}
    if not source.get("sha256"):
        missing.append("source_sha256")
    if not source.get("edition"):
        missing.append("edition_identity")
    if not configuration.get("policy_profile"):
        missing.append("policy_identity")
    if not configuration.get("rubric_version"):
        missing.append("rubric_identity")
    if configuration.get("audit_mode") not in {"full", "pilot"}:
        missing.append("audit_mode")
    artifact_types = {
        str(item.get("artifact_type", "")).replace("-", "_")
        for item in state.get("artifacts", [])
        if isinstance(item, dict)
    }
    for dependency, accepted in (
        ("expanded_page_map", {"page_map"}),
        ("chunk_manifest", {"chunk_manifest"}),
        ("frozen_evaluation_policy", {"evaluation_policy"}),
    ):
        if not artifact_types.intersection(accepted):
            missing.append(dependency)
    candidate = state.get("candidate")
    integrated = isinstance(candidate, dict) and bool(candidate.get("preparation_receipt_sha256"))
    return {
        "command": "worker-candidate-preparation",
        "lane": "auxiliary_isolated_worker",
        "status": "completed" if integrated else ("available" if not missing else "blocked"),
        "available": not missing and not integrated,
        "unmet_dependencies": missing,
        "canonical_next_unchanged": True,
        "benchmark_lock_status": "locked" if integrated else "pending_final_benchmark",
    }


def candidate_audit_parallel_actions(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Describe additive worker lanes without changing the canonical v4 next stage."""
    stages = state.get("stages", {}) if isinstance(state.get("stages"), dict) else {}
    locator_ready = stages.get("locator_chunk_preparation", {}).get("status") == "completed"
    locator_complete = stages.get("locator_audit", {}).get("status") == "completed"
    missing_complete = stages.get("missing_access_audit", {}).get("status") == "completed"

    locator_status = "completed" if locator_complete else ("available" if locator_ready else "blocked")
    missing_ready = locator_complete
    missing_status = "completed" if missing_complete else ("available" if missing_ready else "blocked")
    publication_profile = state.get("configuration", {}).get("publication_profile", "aggregate_only")
    return [
        {
            "command": "worker-locator-audit",
            "coordinator_command": "integrate-locator-audits",
            "lane": "auxiliary_isolated_chunk_workers",
            "fulfills_stage": "locator_audit",
            "status": locator_status,
            "available": locator_status == "available",
            "unmet_dependencies": [] if locator_ready else ["locator_chunk_preparation"],
            "canonical_next_unchanged": True,
            "publication_profile": publication_profile,
            "selection_rule": "Coordinator integration requires explicit pull requests and exact receipt/recovery bindings for the selected wave, plus the complete frozen locator-packet set for both preflight and integration.",
        },
        {
            "command": "worker-missing-access-audit",
            "coordinator_command": "integrate-missing-access-audits",
            "lane": "auxiliary_isolated_chunk_workers",
            "fulfills_stage": "missing_access_audit",
            "status": missing_status,
            "available": missing_status == "available",
            "unmet_dependencies": [] if missing_ready else ["locator_audit"],
            "canonical_next_unchanged": True,
            "publication_profile": publication_profile,
            "selection_rule": "Coordinator integration requires explicit pull requests and exact receipt/recovery bindings.",
        },
    ]


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
        "publication_profile": state.get("configuration", {}).get("publication_profile", "aggregate_only"),
        "scoring_identity": state.get("configuration", {}).get("scoring_identity"),
        "state": current,
        "completed_stages": [name for name in stage_order if stages.get(name, {}).get("status") == "completed"],
        "blocked_stages": [name for name in stage_order if stages.get(name, {}).get("status") == "blocked"],
        "artifacts": state.get("artifacts", []),
        "blockers": state.get("blockers", []),
        "next_actions": [] if next_stage(state) is None else [next_stage(state)],
        "parallel_actions": [candidate_preparation_action(state), *candidate_audit_parallel_actions(state)],
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
            **({"edition": args.source_edition} if args.source_edition else {}),
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
            "publication_profile": args.publication_profile,
            "chunking": {"primary": "chapter", "maximum_pages": 60, "context_overlap_pages": 2},
            "policy_profile": "subject-index-standard-policy-v1",
            # Kept only as the legacy judgment-policy/preparation identity.  V5
            # score identity is deliberately separate below.
            "rubric_version": "subject-index-rubric-v4",
            "scoring_identity": {
                "rubric_version": SCORE_RUBRIC_VERSION,
                "dimension_calculation_profile": DIMENSION_CALCULATION_PROFILE,
            },
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
        "parallel_actions": [candidate_preparation_action(state), *candidate_audit_parallel_actions(state)],
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
        has_registered = any(
            artifact_is_active_for_stage(state, item, args.stage)
            for item in state.get("artifacts", [])
            if isinstance(item, dict)
        )
        if args.stage != "initialize" and not has_registered:
            code = "active_profile_artifact_required" if args.stage in {"scoring", "web_report"} else "completion_artifact_required"
            fail(code, f"Cannot complete {args.stage} without a registered artifact active for the current score identity.")
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
        artifact_document: dict[str, Any] | None = None
        if artifact_path.suffix.lower() == ".json":
            try:
                artifact_document = json.loads(artifact_path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                fail("invalid_artifact_json", f"JSON artifact is invalid: {exc}")
        stage_completion_eligible: bool | None = None
        if args.stage in {"scoring", "web_report"}:
            if not isinstance(artifact_document, dict):
                fail("active_v5_json_artifact_required", f"{args.stage} requires a JSON artifact bound to the active score identity.")
            stage_completion_eligible = require_profile_bound_stage_artifact(
                artifact_document,
                artifact_path,
                args.stage,
                state.get("configuration", {}).get("scoring_identity", {}),
                state,
                state_path,
            )
            if args.status == "completed" and stage_completion_eligible is not True:
                fail("active_v5_evaluation_result_required", "Only an authoritatively validated V5 evaluation result can complete scoring.")
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
        if args.stage in {"scoring", "web_report"}:
            record["active_for_scoring_identity"] = True
            record["scoring_identity"] = deepcopy(state.get("configuration", {}).get("scoring_identity"))
            record["stage_completion_eligible"] = stage_completion_eligible
        if previous and previous.get("sha256") != artifact_hash:
            record["supersedes"] = previous.get("artifact_id")
        state_record_keys = ["artifact_id", "stage", "artifact_type", "path", "sha256", "visibility", "retention", "frozen", "recorded_at"]
        if args.stage in {"scoring", "web_report"}:
            state_record_keys.extend(["active_for_scoring_identity", "scoring_identity", "stage_completion_eligible"])
        artifact = {key: record[key] for key in state_record_keys}
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
    configuration.setdefault("scoring_identity", {
        "rubric_version": SCORE_RUBRIC_VERSION,
        "dimension_calculation_profile": DIMENSION_CALCULATION_PROFILE,
    })
    state["updated_at"] = now()
    save_state(state_path, state)
    payload = state_summary(state, state_path)
    payload.update({
        "command": "adopt-standard-policy",
        "policy_profile": configuration["policy_profile"],
        "rubric_version": configuration["rubric_version"],
        "scoring_identity": configuration["scoring_identity"],
        "state_path": str(state_path.resolve()),
    })
    emit(payload, 0 if payload["ok"] else 1)


def normalized_artifact_type(value: Any) -> str:
    return str(value or "").replace("-", "_")


def verify_v5_inputs_registered(
    state: dict[str, Any],
    state_path: Path,
    manifest: dict[str, Any],
    loaded: dict[str, Any],
) -> None:
    """Require score-profile evidence to be the state's exact frozen audit inventory."""
    role_contracts = {
        "chunk_manifest": ("chunk_definition", {"chunk_manifest"}),
        "locator_audit": ("locator_audit", {"locator_audit", "locator_audit_v1", "locator_audit_v2"}),
        "missing_access_audit": ("missing_access_audit", {"missing_access_audit", "missing_access_audit_v1"}),
        "structure_audit": ("structure_audit", {"structure_audit", "structure_audit_v3", "structure_audit_v4"}),
        "migration_supplement": ("structure_audit", {"migration_supplement", "v5_migration_supplement", "subject_index_v5_migration_supplement_v1"}),
    }
    state_records = [item for item in state.get("artifacts", []) if isinstance(item, dict)]
    manifest_by_path = {item.get("path"): item for item in manifest.get("artifacts", []) if isinstance(item, dict)}
    for artifact, resolved_input_path in zip(loaded["input_artifacts"], loaded["input_paths"], strict=True):
        role = artifact["role"].split("[", 1)[0]
        expected_stage, accepted_types = role_contracts[role]
        same_path: list[dict[str, Any]] = []
        for record in state_records:
            try:
                registered_path = resolve_artifact_path(state_path, str(record.get("path", ""))).resolve()
            except ValueError:
                continue
            if registered_path == resolved_input_path.resolve():
                same_path.append(record)
        if not same_path:
            fail(
                "v5_input_artifact_not_registered",
                f"V5 input {artifact['role']} is not registered in the canonical evaluation state.",
                {"role": artifact["role"], "path": str(resolved_input_path)},
            )
        matching = [item for item in same_path if item.get("sha256") == artifact["sha256"]]
        if not matching:
            fail(
                "v5_input_artifact_hash_mismatch",
                f"V5 input {artifact['role']} does not match the hash registered in canonical state.",
                {"role": artifact["role"], "path": str(resolved_input_path), "input_sha256": artifact["sha256"], "registered_sha256": [item.get("sha256") for item in same_path]},
            )
        record = matching[0]
        if record.get("frozen") is not True or record.get("retention") != "required":
            fail(
                "v5_input_artifact_not_frozen",
                f"V5 input {artifact['role']} must be a frozen, required canonical artifact.",
                {"role": artifact["role"], "path": record.get("path"), "frozen": record.get("frozen"), "retention": record.get("retention")},
            )
        if record.get("stage") != expected_stage or normalized_artifact_type(record.get("artifact_type")) not in accepted_types:
            fail(
                "v5_input_artifact_role_mismatch",
                f"V5 input {artifact['role']} is not registered under its required canonical stage and artifact type.",
                {
                    "role": artifact["role"],
                    "path": record.get("path"),
                    "expected_stage": expected_stage,
                    "actual_stage": record.get("stage"),
                    "accepted_artifact_types": sorted(accepted_types),
                    "actual_artifact_type": record.get("artifact_type"),
                },
            )
        if state.get("stages", {}).get(expected_stage, {}).get("status") != "completed":
            fail(
                "v5_input_artifact_stage_incomplete",
                f"V5 input {artifact['role']} belongs to a canonical stage that is not completed.",
                {"role": artifact["role"], "stage": expected_stage, "status": state.get("stages", {}).get(expected_stage, {}).get("status")},
            )
        manifest_record = manifest_by_path.get(record["path"])
        binding_keys = ("path", "sha256", "stage", "artifact_type", "frozen", "retention")
        if manifest_record is None or any(manifest_record.get(key) != record.get(key) for key in binding_keys):
            fail(
                "v5_input_manifest_binding_mismatch",
                f"V5 input {artifact['role']} is not identically bound in state and artifact manifest.",
                {"role": artifact["role"], "state_record": {key: record.get(key) for key in binding_keys}, "manifest_record": None if manifest_record is None else {key: manifest_record.get(key) for key in binding_keys}},
            )


def command_set_score_calculation_profile(args: argparse.Namespace) -> None:
    """Adopt V5 score identity while invalidating scoring outputs only."""
    state_path = Path(args.state)
    state = load_state(state_path)
    preflight_path = Path(args.preflight).resolve()
    calculation_input_path = Path(args.calculation_input).resolve()
    try:
        preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        fail("invalid_preflight", f"Could not read the deterministic V5 preflight: {exc}")
    try:
        import dimension_score_cli as v5_score
    except ImportError as exc:
        fail("v5_preflight_unavailable", f"Could not load the authoritative V5 scorer: {exc}")
    try:
        loaded = v5_score.load_inputs(calculation_input_path)
        ledgers, missing_requirements = v5_score.preflight_loaded(loaded)
    except (OSError, v5_score.CalculationError) as exc:
        details = exc.details if isinstance(exc, v5_score.CalculationError) else None
        fail("v5_inputs_insufficient", f"The authoritative V5 preflight could not be reproduced: {exc}", details)
    expected_preflight = {
        "command": "migration-sufficiency-preflight",
        "ok": True,
        "evaluation_id": loaded["config"]["evaluation_id"],
        "target_rubric_version": SCORE_RUBRIC_VERSION,
        "target_calculation_profile": DIMENSION_CALCULATION_PROFILE,
        "sufficient": not missing_requirements,
        "input_artifacts": loaded["input_artifacts"],
        "missing_requirements": missing_requirements,
        "mutated_inputs": False,
    }
    if missing_requirements:
        fail("v5_inputs_insufficient", "The authoritative V5 preflight is not sufficient to change score identity.", missing_requirements)
    if preflight != expected_preflight:
        fail("preflight_verification_mismatch", "The supplied preflight is not the exact result reproduced from the supplied frozen calculation input.", {"expected": expected_preflight, "actual": preflight})
    if loaded["config"]["evaluation_id"] != state.get("evaluation_id"):
        fail("preflight_identity_mismatch", "The calculation input and preflight belong to a different evaluation.")
    if loaded["config"]["audit_mode"] != state.get("configuration", {}).get("audit_mode"):
        fail("preflight_identity_mismatch", "The calculation input audit mode differs from canonical state.")
    if ledgers is None:
        fail("v5_inputs_insufficient", "The authoritative V5 preflight did not return validated ledgers.")
    if state.get("source", {}).get("sha256") != ledgers["identity"]["source_sha256"]:
        fail("preflight_identity_mismatch", "The calculation inputs bind a different source than canonical state.")
    state_candidate = state.get("candidate")
    if isinstance(state_candidate, dict) and state_candidate.get("sha256") != ledgers["identity"]["candidate_sha256"]:
        fail("preflight_identity_mismatch", "The calculation inputs bind a different candidate than canonical state.")
    manifest_path = manifest_path_for_state(state_path, state)
    manifest = load_manifest(manifest_path)
    state_errors, _ = validate_state(state, state_path=state_path, check_files=True, manifest_document=manifest)
    if state_errors:
        fail("invalid_state_for_score_profile_change", "Canonical state must validate before score identity can change.", state_errors)
    verify_v5_inputs_registered(state, state_path, manifest, loaded)
    before_stages = deepcopy(state.get("stages", {}))
    configuration = state.setdefault("configuration", {})
    previous = deepcopy(configuration.get("scoring_identity"))
    target = {
        "rubric_version": SCORE_RUBRIC_VERSION,
        "dimension_calculation_profile": DIMENSION_CALCULATION_PROFILE,
    }
    configuration["scoring_identity"] = target
    stamp = now()
    deactivated_artifacts: list[str] = []
    manifest_by_path = {
        item.get("path"): item
        for item in manifest.get("artifacts", [])
        if isinstance(item, dict)
    }
    for artifact in state.get("artifacts", []):
        if not isinstance(artifact, dict) or artifact.get("stage") not in {"scoring", "web_report"}:
            continue
        artifact["active_for_scoring_identity"] = False
        artifact["scoring_identity"] = previous
        artifact["invalidated_at"] = stamp
        artifact["invalidation_reason"] = "score_calculation_profile_changed"
        manifest_record = manifest_by_path.get(artifact.get("path"))
        if not isinstance(manifest_record, dict) or manifest_record.get("sha256") != artifact.get("sha256"):
            fail("artifact_manifest_binding_mismatch", "A scoring output cannot be deactivated because its manifest binding differs from state.", {"path": artifact.get("path")})
        manifest_record["active_for_scoring_identity"] = False
        manifest_record["scoring_identity"] = previous
        manifest_record["invalidated_at"] = stamp
        manifest_record["invalidation_reason"] = "score_calculation_profile_changed"
        deactivated_artifacts.append(str(artifact.get("path")))
    for stage in ("scoring", "web_report"):
        record = state["stages"][stage]
        record["status"] = "not_started"
        record["updated_at"] = stamp
        record.setdefault("notes", []).append("Invalidated by an explicit score-calculation-profile change; benchmark and audit stages remain frozen.")
    configuration.setdefault("score_profile_history", []).append({
        "changed_at": stamp,
        "previous": previous,
        "current": target,
        "preflight_path": portable_relative_path(preflight_path, state_path.resolve().parent),
        "preflight_sha256": sha256_file(preflight_path),
        "calculation_input_path": portable_relative_path(calculation_input_path, state_path.resolve().parent),
        "calculation_input_sha256": sha256_file(calculation_input_path),
        "invalidated_stages": ["scoring", "web_report"],
    })
    for stage in STAGES[:STAGES.index("scoring")]:
        if state["stages"][stage] != before_stages[stage]:
            fail("upstream_stage_changed", f"Score-profile migration attempted to change protected stage {stage}.")
    state["updated_at"] = stamp
    manifest["updated_at"] = stamp
    save_manifest(manifest_path, manifest)
    save_state(state_path, state)
    payload = state_summary(state, state_path)
    payload.update({
        "command": "set-score-calculation-profile",
        "score_identity": target,
        "invalidated_stages": ["scoring", "web_report"],
        "preserved_stages": STAGES[:STAGES.index("scoring")],
        "artifacts_deleted": [],
        "artifacts_deactivated": sorted(deactivated_artifacts),
    })
    emit(payload, 0 if payload["ok"] else 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create evaluation-state.json")
    init_parser.add_argument("--output", required=True)
    init_parser.add_argument("--evaluation-id", required=True)
    init_parser.add_argument("--source-title", required=True)
    init_parser.add_argument("--source-edition")
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
    init_parser.add_argument(
        "--publication-profile",
        choices=sorted(PUBLICATION_PROFILES),
        default="aggregate_only",
        help="Public artifact policy; omitted legacy states are treated as aggregate_only.",
    )
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(func=command_init)

    for name, function in (("status", command_status), ("next", command_next)):
        sub = subparsers.add_parser(name)
        sub.add_argument("--state", required=True)
        sub.set_defaults(func=function)

    set_parser = subparsers.add_parser("set-stage", help="Update one stage after dependency checks")
    set_parser.add_argument("--state", required=True)
    set_parser.add_argument("--stage", required=True, choices=sorted(STAGES))
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

    score_profile_parser = subparsers.add_parser(
        "set-score-calculation-profile",
        help="Adopt the approved V5 score profile after a sufficient deterministic preflight.",
    )
    score_profile_parser.add_argument("--state", required=True)
    score_profile_parser.add_argument("--preflight", required=True)
    score_profile_parser.add_argument("--calculation-input", required=True)
    score_profile_parser.set_defaults(func=command_set_score_calculation_profile)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "document_page_start", 0) and args.document_page_end < args.document_page_start:
        fail("invalid_page_span", "document-page-end must be greater than or equal to document-page-start.")
    if args.command in {"init", "set-stage", "adopt-standard-policy", "set-score-calculation-profile"}:
        state_path = Path(args.output if args.command == "init" else args.state)
        with evaluation_mutation_lock(state_path):
            args.func(args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
