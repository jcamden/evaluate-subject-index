#!/usr/bin/env python3
"""Deterministic state manager for the evaluate-subject-index skill."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STAGES = [
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

COMMANDS = {
    "initialize": "initialize",
    "page_mapping": "map-pages",
    "chunk_definition": "define-chunks",
    "define_policy": "define-policy",
    "source_chunk_preparation": "prepare-source-chunks",
    "source_subject_discovery": "discover-source-subjects",
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
    "initialize": ["source file", "source title", "document-page span", "audience", "audit mode"],
    "page_mapping": ["compact mapping from one-based document-page ranges to source page-label strings"],
    "chunk_definition": ["expanded page map", "user-approved owned and context document-page ranges"],
    "define_policy": ["initialized state", "source scope", "page map", "chunk manifest", "indexing policies", "density-band rationale"],
    "source_chunk_preparation": ["source PDF", "expanded page map", "validated chunk manifest"],
    "source_subject_discovery": ["source chunk PDFs", "sidecar page maps", "frozen policy", "chunk manifest"],
    "benchmark_freeze": ["all source-subject chunks", "whole-source synthesis pass", "reader tasks"],
    "candidate_normalization": ["original candidate index", "expanded page map"],
    "locator_chunk_preparation": ["normalized candidate", "expanded page map", "validated chunk manifest"],
    "locator_audit": ["source chunk PDF", "candidate locator chunk packet", "page sidecar"],
    "missing_access_audit": ["frozen benchmark", "normalized candidate", "locator judgments"],
    "structure_audit": ["complete locator and missing-access audits", "normalized whole index"],
    "scoring": ["all complete audit ledgers", "rubric v3", "critical gates"],
    "web_report": ["validated evaluation result", "balanced representative examples"],
}

COMPLETION_TESTS = {
    "initialize": "State is valid and the source identity and one-based document-page span are recorded.",
    "page_mapping": "Every document page has one mapping record and every indexable label resolves uniquely.",
    "chunk_definition": "The user approved the ranges, owned pages are unique, and every in-scope document page is owned.",
    "define_policy": "Policy is schema-valid, frozen, hashed, and density is scored or explicitly descriptive-only.",
    "source_chunk_preparation": "Every chunk PDF and sidecar map exists and preserves original document-page identity.",
    "source_subject_discovery": "Every owned source page was reviewed once and every chunk artifact is valid.",
    "benchmark_freeze": "Whole-source synthesis is complete and the candidate-blind benchmark is frozen and hashed.",
    "candidate_normalization": "Every delivered record, cross-reference, and expanded locator has a stable ID.",
    "locator_chunk_preparation": "Every resolved locator is routed once and the routing exception ledger is empty.",
    "locator_audit": "Every expected expanded locator assignment has exactly one judgment.",
    "missing_access_audit": "Every scored benchmark subject and expected treatment has a coverage judgment.",
    "structure_audit": "The full hierarchy, terminology, references, mechanics, density, and distribution are audited.",
    "scoring": "Score arithmetic, gates, denominators, hashes, and limitations validate.",
    "web_report": "The display payload validates and references frozen evidence IDs.",
}

VALID_STATUSES = {"not_started", "in_progress", "completed", "blocked"}


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


def emit(payload: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(exit_code)


def fail(code: str, message: str, details: Any = None) -> None:
    payload = {"ok": False, "error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    emit(payload, 1)


def stage_dependencies(stage: str) -> list[str]:
    index = STAGES.index(stage)
    return STAGES[:index]


def validate_state(state: dict[str, Any], check_files: bool = True) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for key in ("schema_version", "evaluation_id", "source", "configuration", "stages", "artifacts", "blockers"):
        if key not in state:
            errors.append(f"Missing required key: {key}")
    if state.get("schema_version") != "subject-index-evaluation-state-v2":
        errors.append("Unsupported schema_version.")

    stages = state.get("stages", {})
    if not isinstance(stages, dict):
        errors.append("stages must be an object.")
        stages = {}
    for name in STAGES:
        record = stages.get(name)
        if not isinstance(record, dict):
            errors.append(f"Missing stage record: {name}")
            continue
        if record.get("status") not in VALID_STATUSES:
            errors.append(f"Invalid status for {name}: {record.get('status')}")

    completed_prefix = True
    for name in STAGES:
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
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            errors.append("Each artifact must be an object.")
            continue
        artifact_path = Path(str(artifact.get("path", "")))
        if check_files and not artifact_path.is_file():
            warnings.append(f"Artifact is not currently accessible: {artifact_path}")
        elif check_files:
            actual = sha256_file(artifact_path)
            recorded = artifact.get("sha256")
            if recorded and actual != recorded:
                errors.append(f"Artifact hash mismatch: {artifact_path}")

    active = [name for name in STAGES if stages.get(name, {}).get("status") == "in_progress"]
    if len(active) > 1:
        errors.append(f"More than one stage is in progress: {active}")
    return errors, warnings


def next_stage(state: dict[str, Any]) -> dict[str, Any] | None:
    stages = state["stages"]
    for name in STAGES:
        status = stages[name]["status"]
        if status == "completed":
            continue
        deps = stage_dependencies(name)
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


def state_summary(state: dict[str, Any]) -> dict[str, Any]:
    errors, warnings = validate_state(state)
    stages = state.get("stages", {})
    current = next((name for name in STAGES if stages.get(name, {}).get("status") == "in_progress"), None)
    if current is None:
        current = next((name for name in STAGES if stages.get(name, {}).get("status") != "completed"), "complete")
    return {
        "ok": not errors,
        "evaluation_id": state.get("evaluation_id"),
        "state": current,
        "completed_stages": [name for name in STAGES if stages.get(name, {}).get("status") == "completed"],
        "blocked_stages": [name for name in STAGES if stages.get(name, {}).get("status") == "blocked"],
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
        "schema_version": "subject-index-evaluation-state-v2",
        "evaluation_id": args.evaluation_id,
        "created_at": stamp,
        "updated_at": stamp,
        "source": {
            "title": args.source_title,
            "filename": source_path.name,
            "path": str(source_path),
            "sha256": source_hash,
            "document_page_span": [args.document_page_start, args.document_page_end],
            "document_page_basis": "one_based_inclusive",
        },
        "candidate": None,
        "configuration": {
            "audit_mode": args.audit_mode,
            "index_type": "subject_index",
            "intended_readership": args.intended_readership,
            "output_format": "json",
            "chunking": {"primary": "chapter", "maximum_pages": 60, "context_overlap_pages": 2},
            "rubric_version": "subject-index-rubric-v3",
        },
        "stages": stages,
        "artifacts": [],
        "blockers": blockers,
    }
    save_state(output, state)
    payload = state_summary(state)
    payload.update({"command": "initialize", "state_path": str(output), "artifacts_written": [str(output)]})
    emit(payload)


def command_status(args: argparse.Namespace) -> None:
    state = load_state(Path(args.state))
    payload = state_summary(state)
    payload["command"] = "status"
    emit(payload, 0 if payload["ok"] else 1)


def command_next(args: argparse.Namespace) -> None:
    state = load_state(Path(args.state))
    errors, warnings = validate_state(state)
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
    if args.stage not in STAGES:
        fail("unknown_stage", f"Unknown stage: {args.stage}")
    unmet = [dep for dep in stage_dependencies(args.stage) if state["stages"][dep]["status"] != "completed"]
    if args.status in {"in_progress", "completed"} and unmet:
        fail("unmet_dependencies", f"Cannot set {args.stage} to {args.status}.", unmet)
    if args.status == "in_progress":
        active = [name for name in STAGES if state["stages"][name]["status"] == "in_progress" and name != args.stage]
        if active:
            fail("another_stage_active", "Only one stage may be in progress.", active)
    stamp = now()
    record = state["stages"][args.stage]
    record["status"] = args.status
    record["updated_at"] = stamp
    if args.note:
        record.setdefault("notes", []).append(args.note)
    artifacts_written: list[str] = []
    if args.artifact_path:
        artifact_path = Path(args.artifact_path).resolve()
        artifact_hash = sha256_file(artifact_path)
        if artifact_hash is None:
            fail("artifact_not_found", f"Artifact file does not exist: {artifact_path}")
        artifact = {
            "stage": args.stage,
            "artifact_type": args.artifact_type or artifact_path.stem,
            "path": str(artifact_path),
            "sha256": artifact_hash,
            "recorded_at": stamp,
        }
        state["artifacts"] = [
            item for item in state.get("artifacts", [])
            if not (item.get("stage") == args.stage and item.get("path") == str(artifact_path))
        ]
        state["artifacts"].append(artifact)
        artifacts_written.append(str(artifact_path))
    state["updated_at"] = stamp
    save_state(state_path, state)
    payload = state_summary(state)
    payload.update({"command": "set-stage", "updated_stage": args.stage, "artifacts_written": artifacts_written})
    emit(payload, 0 if payload["ok"] else 1)


def command_validate(args: argparse.Namespace) -> None:
    state = load_state(Path(args.state))
    errors, warnings = validate_state(state, check_files=not args.skip_files)
    emit({
        "command": "validate",
        "ok": not errors,
        "evaluation_id": state.get("evaluation_id"),
        "errors": errors,
        "warnings": warnings,
    }, 0 if not errors else 1)


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
    init_parser.add_argument("--audit-mode", choices=["full", "pilot"], default="full")
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(func=command_init)

    for name, function in (("status", command_status), ("next", command_next)):
        sub = subparsers.add_parser(name)
        sub.add_argument("--state", required=True)
        sub.set_defaults(func=function)

    set_parser = subparsers.add_parser("set-stage", help="Update one stage after dependency checks")
    set_parser.add_argument("--state", required=True)
    set_parser.add_argument("--stage", required=True, choices=STAGES)
    set_parser.add_argument("--status", required=True, choices=sorted(VALID_STATUSES))
    set_parser.add_argument("--artifact-type")
    set_parser.add_argument("--artifact-path")
    set_parser.add_argument("--note")
    set_parser.set_defaults(func=command_set_stage)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--state", required=True)
    validate_parser.add_argument("--skip-files", action="store_true")
    validate_parser.set_defaults(func=command_validate)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "document_page_start", 0) and args.document_page_end < args.document_page_start:
        fail("invalid_page_span", "document-page-end must be greater than or equal to document-page-start.")
    args.func(args)


if __name__ == "__main__":
    main()
