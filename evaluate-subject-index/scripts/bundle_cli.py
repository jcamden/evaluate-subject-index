#!/usr/bin/env python3
"""Create and resume lightweight checkpoints for a V7 evaluation."""

from __future__ import annotations

import argparse
import json
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from state_cli import load_state, resolve_artifact_path, validate_state
from schema_validation import schema_errors


BUNDLE_SCHEMA_VERSION = "subject-index-bundle-v2"


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


def safe_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value in {"", "."} or "\\" in value:
        fail("unsafe_path", f"Path is not a safe relative POSIX path: {value}")
    return str(path)


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def add_bytes(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    archive.writestr(zip_info(name), data)


def default_output(root: Path, evaluation_id: str, command: str, profile: str) -> Path:
    label = "checkpoint" if command == "checkpoint" else "bundle"
    return root / "exports" / f"{evaluation_id}-{label}-{profile}.zip"


def load_run(state_path: Path) -> tuple[dict[str, Any], Path]:
    state_path = state_path.resolve()
    state = load_state(state_path)
    errors, _ = validate_state(state, state_path=state_path)
    if errors:
        fail("invalid_state", "The evaluation state is not checkpointable.", errors)
    return state, state_path.parent


def command_package(args: argparse.Namespace) -> None:
    state_path = Path(args.state).resolve()
    state, root = load_run(state_path)
    included: dict[str, Path] = {"evaluation-state.json": state_path}
    excluded: list[dict[str, str]] = []
    for record in state.get("artifacts", []):
        relative = safe_relative_path(str(record.get("path", "")))
        if args.profile == "portable" and record.get("visibility") == "restricted":
            excluded.append({"path": relative, "reason": "restricted_by_portable_profile"})
            continue
        if relative.startswith("exports/"):
            excluded.append({"path": relative, "reason": "export_artifact_not_nested"})
            continue
        local = resolve_artifact_path(state_path, relative)
        if not local.is_file():
            excluded.append({"path": relative, "reason": "not_currently_accessible"})
            continue
        included[relative] = local

    metadata = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "evaluation_id": state["evaluation_id"],
        "profile": args.profile,
        "created_at": now(),
        "included_paths": sorted(included),
        "excluded": sorted(excluded, key=lambda item: item["path"]),
    }
    metadata_errors = schema_errors(metadata, "bundle-metadata.schema.json")
    if metadata_errors:
        fail("invalid_bundle_metadata", "Generated bundle metadata is invalid.", metadata_errors)
    output = Path(args.output).resolve() if args.output else default_output(root, state["evaluation_id"], args.command, args.profile)
    if output.exists() and not args.force:
        fail("output_exists", f"Refusing to overwrite existing bundle: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relative in sorted(included):
                add_bytes(archive, relative, included[relative].read_bytes())
            add_bytes(archive, "bundle-metadata.json", (json.dumps(metadata, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()
    emit({
        "command": args.command, "ok": True, "evaluation_id": state["evaluation_id"],
        "storage_mode": state.get("configuration", {}).get("storage_mode"), "profile": args.profile,
        "artifacts_written": [{"path": str(output)}], "included_count": len(included),
        "excluded_count": len(excluded), "next_actions": [], "warnings": [],
    })


def command_list(args: argparse.Namespace) -> None:
    state, _ = load_run(Path(args.state))
    artifacts = sorted(state.get("artifacts", []), key=lambda item: item.get("path", ""))
    emit({"command": "list-artifacts", "ok": True, "evaluation_id": state["evaluation_id"], "artifact_count": len(artifacts), "artifacts": artifacts})


def is_symlink_member(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def command_import(args: argparse.Namespace) -> None:
    bundle = Path(args.input).resolve()
    if not bundle.is_file():
        fail("bundle_not_found", f"Bundle does not exist: {bundle}")
    output = Path(args.output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        fail("output_not_empty", f"Import directory must be new or empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(bundle, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                fail("duplicate_members", "Bundle contains duplicate member paths.")
            required = {"evaluation-state.json", "bundle-metadata.json"}
            missing = sorted(required - set(names))
            if missing:
                fail("missing_control_files", "Bundle is missing required control files.", missing)
            for info in infos:
                safe_relative_path(info.filename)
                if info.is_dir() or is_symlink_member(info):
                    fail("unsupported_member", f"Bundle contains an unsupported member: {info.filename}")
            metadata = json.loads(archive.read("bundle-metadata.json").decode("utf-8"))
            metadata_errors = schema_errors(metadata, "bundle-metadata.schema.json")
            if metadata_errors:
                fail("invalid_bundle_metadata", "Bundle metadata is invalid.", metadata_errors)
            declared = set(metadata.get("included_paths", [])) | {"bundle-metadata.json"}
            if set(names) != declared:
                fail("bundle_inventory_mismatch", "Bundle members differ from its inventory.")
            for info in infos:
                target = output.joinpath(*PurePosixPath(info.filename).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info.filename))
    except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail("invalid_bundle", f"Checkpoint cannot be read: {exc}")

    state_path = output / "evaluation-state.json"
    state = load_state(state_path)
    errors, warnings = validate_state(state, state_path=state_path)
    if errors:
        fail("invalid_imported_state", "The checkpoint state is not resumable.", errors)
    reconnect = [item["path"] for item in metadata.get("excluded", []) if item.get("reason") == "restricted_by_portable_profile"]
    emit({
        "command": "import-bundle", "ok": True, "evaluation_id": state["evaluation_id"],
        "profile": metadata.get("profile"), "artifacts_written": [{"path": str(output), "type": "evaluation_directory"}],
        "reconnect_required": reconnect, "next_actions": ["status", "next"], "warnings": warnings,
    })


def add_package_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state", required=True)
    parser.add_argument("--output")
    parser.add_argument("--profile", choices=["portable", "private-complete"], default="portable")
    parser.add_argument("--force", action="store_true")
    parser.set_defaults(func=command_package)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_package_arguments(subparsers.add_parser("checkpoint"))
    add_package_arguments(subparsers.add_parser("export-bundle"))
    listing = subparsers.add_parser("list-artifacts")
    listing.add_argument("--state", required=True)
    listing.set_defaults(func=command_list)
    importing = subparsers.add_parser("import-bundle")
    importing.add_argument("--input", required=True)
    importing.add_argument("--output-dir", required=True)
    importing.set_defaults(func=command_import)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
