#!/usr/bin/env python3
"""Track one current V7 subject-index evaluation in one atomic state file."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import mimetypes
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from schema_validation import schema_errors


STAGES = [
    "initialize", "page_mapping", "chunk_definition", "define_policy",
    "source_chunk_preparation", "source_subject_discovery", "benchmark_synthesis",
    "benchmark_review", "benchmark_freeze", "candidate_normalization",
    "locator_chunk_preparation", "locator_audit", "missing_access_audit",
    "structure_audit", "scoring", "web_report",
]

COMMANDS = {
    "initialize": "initialize", "page_mapping": "map-pages",
    "chunk_definition": "define-chunks", "define_policy": "define-policy",
    "source_chunk_preparation": "prepare-source-chunks",
    "source_subject_discovery": "discover-source-subjects",
    "benchmark_synthesis": "synthesize-source-benchmark",
    "benchmark_review": "review-source-benchmark", "benchmark_freeze": "freeze-source-benchmark",
    "candidate_normalization": "normalize-index", "locator_chunk_preparation": "prepare-locator-chunks",
    "locator_audit": "audit-locators", "missing_access_audit": "audit-missing-access",
    "structure_audit": "audit-index-structure", "scoring": "score-index",
    "web_report": "build-web-report",
}

REQUIRED_INPUTS = {
    "initialize": ["source file", "source title", "document-page span"],
    "page_mapping": ["source page-label mapping"],
    "chunk_definition": ["expanded page map", "approved chunk ranges"],
    "define_policy": ["source facts", "page map", "chunk manifest", "standard V7 policy"],
    "source_chunk_preparation": ["source PDF", "page map", "chunk manifest"],
    "source_subject_discovery": ["source chunks", "sidecars", "policy"],
    "benchmark_synthesis": ["all source-subject chunks"],
    "benchmark_review": ["candidate-blind benchmark draft", "independent review"],
    "benchmark_freeze": ["approved benchmark"],
    "candidate_normalization": ["candidate index", "page map"],
    "locator_chunk_preparation": ["normalized candidate", "chunk manifest"],
    "locator_audit": ["locator packets", "source chunks"],
    "missing_access_audit": ["benchmark", "normalized candidate", "locator audits"],
    "structure_audit": ["complete candidate audits", "normalized index"],
    "scoring": ["complete V7 audit ledgers"],
    "web_report": ["validated V7 result", "V7 item assessments"],
}
COMPLETION_TESTS = {name: f"A current V7 {name.replace('_', ' ')} artifact is registered." for name in STAGES}
COMPLETION_TESTS["initialize"] = "The state file and source identity are recorded."

VALID_STATUSES = {"not_started", "in_progress", "completed", "blocked"}
VALID_VISIBILITY = {"public", "private", "restricted"}
VALID_RETENTION = {"required", "cache"}
STATE_SCHEMA_VERSION = "subject-index-evaluation-state-v5"
SCORE_RUBRIC_VERSION = "subject-index-rubric-v7"
DIMENSION_CALCULATION_PROFILE = "subject-index-dimension-calculation-v3"
SCORING_COMPLETION_SCHEMA = "subject-index-evaluation-result-v9"
WEB_REPORT_COMPLETION_SCHEMA = "subject-index-web-report-v7"


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def emit(payload: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(exit_code)


def fail(code: str, message: str, details: Any = None) -> None:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    emit({"ok": False, "error": error}, 1)


@contextmanager
def evaluation_mutation_lock(state_path: Path):
    """Serialize cooperative writers for one evaluation directory."""
    lock_path = state_path.resolve().parent / ".evaluation.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail("evaluation_lock_busy", "Another process is updating this evaluation.")
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail("state_not_found", f"State file does not exist: {path}")
    except json.JSONDecodeError as exc:
        fail("invalid_json", f"Could not parse state JSON: {exc}")
    if not isinstance(value, dict):
        fail("invalid_state", "State must be a JSON object.")
    return value


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Atomically replace the single canonical run file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def portable_relative_path(path: Path, root: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        fail("artifact_outside_evaluation_directory", f"Artifact must be inside {root.resolve()}: {path.resolve()}")
    portable = PurePosixPath(relative.as_posix())
    if portable.is_absolute() or ".." in portable.parts or str(portable) in {"", "."}:
        fail("invalid_artifact_path", f"Artifact path is not portable: {relative}")
    return str(portable)


def resolve_artifact_path(state_path: Path, stored_path: str) -> Path:
    portable = PurePosixPath(stored_path)
    if portable.is_absolute() or ".." in portable.parts or stored_path in {"", "."} or "\\" in stored_path:
        raise ValueError(f"Artifact path is not portable: {stored_path}")
    return state_path.resolve().parent.joinpath(*portable.parts)


def artifact_id(path: str, digest: str) -> str:
    value = hashlib.sha256(f"{path}\0{digest}".encode("utf-8")).hexdigest()
    return f"ART-{value[:12].upper()}"


def stages_for_state(state: dict[str, Any]) -> list[str]:
    return STAGES


def stage_dependencies(stage: str, stage_order: list[str]) -> list[str]:
    return stage_order[:stage_order.index(stage)]


def _completion_schema(stage: str) -> str | None:
    return {"scoring": SCORING_COMPLETION_SCHEMA, "web_report": WEB_REPORT_COMPLETION_SCHEMA}.get(stage)


def artifact_is_active_for_stage(state: dict[str, Any], artifact: dict[str, Any], stage: str) -> bool:
    if artifact.get("stage") != stage:
        return False
    required_schema = _completion_schema(stage)
    return required_schema is None or artifact.get("schema_version") == required_schema


def validate_state(
    state: dict[str, Any],
    state_path: Path | None = None,
    check_files: bool = True,
) -> tuple[list[str], list[str]]:
    """Validate the single current state document and its accessible artifacts."""
    errors: list[str] = []
    warnings: list[str] = []
    structural = schema_errors(state, "evaluation-state.schema.json")
    if structural:
        return [f"State schema: {error}" for error in structural], warnings

    configuration = state["configuration"]
    expected_identity = {"rubric_version": SCORE_RUBRIC_VERSION, "dimension_calculation_profile": DIMENSION_CALCULATION_PROFILE}
    if configuration.get("scoring_identity") != expected_identity:
        errors.append("configuration.scoring_identity must select the current V7 profile.")

    stages = state.get("stages") if isinstance(state.get("stages"), dict) else {}
    completed_prefix = True
    for name in STAGES:
        record = stages[name]
        status = record.get("status")
        if status == "completed" and not completed_prefix:
            errors.append(f"Stage {name} is completed before all dependencies are complete.")
        if status != "completed":
            completed_prefix = False
    active = [name for name in STAGES if stages.get(name, {}).get("status") == "in_progress"]
    if len(active) > 1:
        errors.append(f"More than one stage is in progress: {active}")

    span = state.get("source", {}).get("document_page_span") if isinstance(state.get("source"), dict) else None
    if not (isinstance(span, list) and len(span) == 2 and all(isinstance(item, int) for item in span) and span[0] <= span[1]):
        errors.append("source.document_page_span must be an ascending integer pair.")

    artifacts = state["artifacts"]
    seen: set[str] = set()
    for artifact in artifacts:
        stored = artifact["path"]
        if stored in seen:
            errors.append(f"Duplicate artifact path: {stored}")
        seen.add(stored)
        try:
            local = resolve_artifact_path(state_path, stored) if state_path else Path(stored)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if check_files and not local.is_file():
            warnings.append(f"Artifact is not currently accessible: {stored}")
        elif check_files and artifact.get("sha256") and sha256_file(local) != artifact.get("sha256"):
            warnings.append(f"Artifact bytes changed since registration: {stored}")

    for name in STAGES[1:]:
        if stages.get(name, {}).get("status") == "completed" and not any(
            artifact_is_active_for_stage(state, item, name) for item in artifacts if isinstance(item, dict)
        ):
            errors.append(f"Completed stage has no current artifact: {name}")
    return errors, warnings


def next_stage(state: dict[str, Any]) -> dict[str, Any] | None:
    stages = state.get("stages", {})
    for name in STAGES:
        status = stages.get(name, {}).get("status")
        if status == "completed":
            continue
        unmet = [dependency for dependency in stage_dependencies(name, STAGES) if stages.get(dependency, {}).get("status") != "completed"]
        return {
            "stage": name, "command": COMMANDS[name], "status": status,
            "available": not unmet and status != "blocked", "unmet_dependencies": unmet,
            "required_inputs": REQUIRED_INPUTS[name], "completion_test": COMPLETION_TESTS[name],
        }
    return None


def candidate_preparation_action(state: dict[str, Any]) -> dict[str, Any]:
    stages = state.get("stages", {})
    dependencies = ("page_mapping", "chunk_definition", "define_policy")
    missing = [name for name in dependencies if stages.get(name, {}).get("status") != "completed"]
    integrated = stages.get("candidate_normalization", {}).get("status") == "completed"
    return {
        "command": "candidate_preparation_cli.py register",
        "status": "completed" if integrated else "available" if not missing else "blocked",
        "available": not missing and not integrated,
        "unmet_dependencies": missing,
    }


def candidate_audit_parallel_actions(state: dict[str, Any]) -> list[dict[str, Any]]:
    stages = state.get("stages", {})
    locator_ready = stages.get("locator_chunk_preparation", {}).get("status") == "completed"
    locator_done = stages.get("locator_audit", {}).get("status") == "completed"
    missing_done = stages.get("missing_access_audit", {}).get("status") == "completed"
    return [
        {"command": "parallel_candidate_audit_cli.py register-audits --audit-kind locator", "status": "completed" if locator_done else "available" if locator_ready else "blocked", "available": locator_ready and not locator_done},
        {"command": "parallel_candidate_audit_cli.py register-audits --audit-kind missing_access", "status": "completed" if missing_done else "available" if locator_done else "blocked", "available": locator_done and not missing_done},
    ]


def state_summary(state: dict[str, Any], state_path: Path | None = None) -> dict[str, Any]:
    errors, warnings = validate_state(state, state_path=state_path)
    stages = state.get("stages", {})
    current = next((name for name in STAGES if stages.get(name, {}).get("status") == "in_progress"), None)
    if current is None:
        current = next((name for name in STAGES if stages.get(name, {}).get("status") != "completed"), "complete")
    action = next_stage(state)
    return {
        "ok": not errors, "evaluation_id": state.get("evaluation_id"),
        "storage_mode": state.get("configuration", {}).get("storage_mode"),
        "scoring_identity": state.get("configuration", {}).get("scoring_identity"), "state": current,
        "completed_stages": [name for name in STAGES if stages.get(name, {}).get("status") == "completed"],
        "blocked_stages": [name for name in STAGES if stages.get(name, {}).get("status") == "blocked"],
        "artifacts": state.get("artifacts", []), "blockers": state.get("blockers", []),
        "next_actions": [] if action is None else [action],
        "parallel_actions": [candidate_preparation_action(state), *candidate_audit_parallel_actions(state)],
        "errors": errors, "warnings": warnings,
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
    stages = {name: {"status": "completed" if name == "initialize" else "not_started", "updated_at": stamp if name == "initialize" else None, "notes": []} for name in STAGES}
    state = {
        "schema_version": STATE_SCHEMA_VERSION, "evaluation_id": args.evaluation_id,
        "created_at": stamp, "updated_at": stamp,
        "source": {
            "title": args.source_title, **({"edition": args.source_edition} if args.source_edition else {}),
            "filename": source_path.name, "sha256": source_hash,
            "document_page_span": [args.document_page_start, args.document_page_end],
            "document_page_basis": "one_based_inclusive",
        },
        "candidate": None,
        "configuration": {
            "audit_mode": args.audit_mode, "index_type": "subject_index",
            "intended_readership": args.intended_readership,
            "readership_provenance": {"basis": args.readership_basis, "confidence": args.readership_confidence, "rationale": args.readership_rationale},
            "output_format": "json", "storage_mode": args.storage_mode,
            "policy_profile": "subject-index-standard-policy-v7", "rubric_version": SCORE_RUBRIC_VERSION,
            "scoring_identity": {"rubric_version": SCORE_RUBRIC_VERSION, "dimension_calculation_profile": DIMENSION_CALCULATION_PROFILE},
        },
        "stages": stages, "artifacts": [], "blockers": [],
    }
    save_state(output, state)
    payload = state_summary(state, output)
    payload.update({"command": "initialize", "state_path": str(output), "artifacts_written": [str(output)]})
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
    action = next_stage(state)
    emit({"command": "next", "ok": not errors, "evaluation_id": state.get("evaluation_id"), "next_actions": [] if action is None else [action], "parallel_actions": [candidate_preparation_action(state), *candidate_audit_parallel_actions(state)], "errors": errors, "warnings": warnings}, 0 if not errors else 1)


def command_set_stage(args: argparse.Namespace) -> None:
    state_path = Path(args.state)
    state = load_state(state_path)
    unmet = [name for name in stage_dependencies(args.stage, STAGES) if state["stages"][name]["status"] != "completed"]
    if args.status in {"in_progress", "completed"} and unmet:
        fail("unmet_dependencies", f"Cannot set {args.stage} to {args.status}.", unmet)
    if args.status == "in_progress":
        active = [name for name in STAGES if state["stages"][name]["status"] == "in_progress" and name != args.stage]
        if active:
            fail("another_stage_active", "Only one stage may be in progress.", active)

    stamp = now()
    written: list[str] = []
    if args.artifact_path:
        local = Path(args.artifact_path).resolve()
        digest = sha256_file(local)
        if digest is None:
            fail("artifact_not_found", f"Artifact file does not exist: {local}")
        relative = portable_relative_path(local, state_path.resolve().parent)
        schema_version = None
        if local.suffix.lower() == ".json":
            try:
                document = json.loads(local.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                fail("invalid_artifact_json", f"JSON artifact is invalid: {exc}")
            if isinstance(document, dict):
                schema_version = document.get("schema_version")
        required_schema = _completion_schema(args.stage) if args.status == "completed" else None
        if required_schema and schema_version != required_schema:
            fail("current_v7_artifact_required", f"Completing {args.stage} requires {required_schema}.", {"actual": schema_version})
        record = {
            "artifact_id": artifact_id(relative, digest), "stage": args.stage,
            "artifact_type": args.artifact_type or local.stem, "path": relative, "sha256": digest,
            "media_type": args.media_type or mimetypes.guess_type(local.name)[0] or "application/octet-stream",
            "visibility": args.visibility, "retention": args.retention, "frozen": args.frozen,
            "recorded_at": stamp, **({"schema_version": schema_version} if isinstance(schema_version, str) else {}),
        }
        state["artifacts"] = [item for item in state.get("artifacts", []) if item.get("path") != relative]
        state["artifacts"].append(record)
        state["artifacts"].sort(key=lambda item: item["path"])
        written.append(relative)
    elif args.status == "completed" and args.stage != "initialize" and not any(
        artifact_is_active_for_stage(state, item, args.stage) for item in state.get("artifacts", []) if isinstance(item, dict)
    ):
        fail("completion_artifact_required", f"Cannot complete {args.stage} without a current registered artifact.")

    stage = state["stages"][args.stage]
    stage["status"] = args.status
    stage["updated_at"] = stamp
    if args.note:
        stage.setdefault("notes", []).append(args.note)
    state["updated_at"] = stamp
    save_state(state_path, state)
    payload = state_summary(state, state_path)
    payload.update({"command": "set-stage", "updated_stage": args.stage, "artifacts_written": written})
    emit(payload, 0 if payload["ok"] else 1)


def command_validate(args: argparse.Namespace) -> None:
    state_path = Path(args.state)
    state = load_state(state_path)
    errors, warnings = validate_state(state, state_path=state_path, check_files=not args.skip_files)
    emit({"command": "validate", "ok": not errors, "evaluation_id": state.get("evaluation_id"), "errors": errors, "warnings": warnings}, 0 if not errors else 1)


def command_adopt_standard_policy(args: argparse.Namespace) -> None:
    state_path = Path(args.state)
    state = load_state(state_path)
    if state.get("stages", {}).get("define_policy", {}).get("status") == "completed":
        fail("policy_already_frozen", "The policy stage is already complete.")
    configuration = state["configuration"]
    if args.intended_readership:
        configuration["intended_readership"] = args.intended_readership
    configuration["readership_provenance"] = {"basis": args.readership_basis, "confidence": args.readership_confidence, "rationale": args.readership_rationale}
    configuration["policy_profile"] = "subject-index-standard-policy-v7"
    configuration["rubric_version"] = SCORE_RUBRIC_VERSION
    configuration["scoring_identity"] = {"rubric_version": SCORE_RUBRIC_VERSION, "dimension_calculation_profile": DIMENSION_CALCULATION_PROFILE}
    state["updated_at"] = now()
    save_state(state_path, state)
    emit({"command": "adopt-standard-policy", "ok": True, "evaluation_id": state["evaluation_id"], "policy_profile": configuration["policy_profile"], "scoring_identity": configuration["scoring_identity"], "state_path": str(state_path.resolve())})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init")
    init.add_argument("--output", required=True)
    init.add_argument("--evaluation-id", required=True)
    init.add_argument("--source-title", required=True)
    init.add_argument("--source-edition")
    init.add_argument("--source-file", required=True)
    init.add_argument("--document-page-start", "--page-start", dest="document_page_start", type=int, required=True)
    init.add_argument("--document-page-end", "--page-end", dest="document_page_end", type=int, required=True)
    init.add_argument("--intended-readership", required=True)
    init.add_argument("--readership-basis", choices=["inferred", "user_supplied"], default="inferred")
    init.add_argument("--readership-confidence", choices=["high", "medium", "low"], default="medium")
    init.add_argument("--readership-rationale", default="Inferred from the source.")
    init.add_argument("--audit-mode", choices=["full", "pilot"], default="full")
    init.add_argument("--storage-mode", choices=["local", "library", "hybrid"], default="local")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=command_init)

    for name, function in (("status", command_status), ("next", command_next), ("validate", command_validate)):
        command = subparsers.add_parser(name)
        command.add_argument("--state", required=True)
        if name == "validate":
            command.add_argument("--skip-files", action="store_true")
        command.set_defaults(func=function)

    stage = subparsers.add_parser("set-stage")
    stage.add_argument("--state", required=True)
    stage.add_argument("--stage", required=True, choices=STAGES)
    stage.add_argument("--status", required=True, choices=sorted(VALID_STATUSES))
    stage.add_argument("--artifact-type")
    stage.add_argument("--artifact-path")
    stage.add_argument("--media-type")
    stage.add_argument("--visibility", choices=sorted(VALID_VISIBILITY), default="private")
    stage.add_argument("--retention", choices=sorted(VALID_RETENTION), default="required")
    stage.add_argument("--frozen", action="store_true")
    stage.add_argument("--note")
    stage.set_defaults(func=command_set_stage)

    policy = subparsers.add_parser("adopt-standard-policy")
    policy.add_argument("--state", required=True)
    policy.add_argument("--intended-readership")
    policy.add_argument("--readership-basis", choices=["inferred", "user_supplied"], required=True)
    policy.add_argument("--readership-confidence", choices=["high", "medium", "low"], required=True)
    policy.add_argument("--readership-rationale", required=True)
    policy.set_defaults(func=command_adopt_standard_policy)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if getattr(args, "document_page_start", 0) and args.document_page_end < args.document_page_start:
        fail("invalid_page_span", "document-page-end must be greater than or equal to document-page-start.")
    if args.command in {"init", "set-stage", "adopt-standard-policy"}:
        state_path = Path(args.output if args.command == "init" else args.state)
        with evaluation_mutation_lock(state_path):
            args.func(args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
