#!/usr/bin/env python3
"""Create, inspect, and safely import subject-index evaluation bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


STATE_SCHEMA_VERSION = "subject-index-evaluation-state-v4"
MANIFEST_SCHEMA_VERSION = "subject-index-artifact-manifest-v1"
BUNDLE_SCHEMA_VERSION = "subject-index-bundle-v1"
PUBLICATION_PROFILES = {"aggregate_only", "public_evaluation_artifacts"}


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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail("file_not_found", f"{label} does not exist: {path}")
    except json.JSONDecodeError as exc:
        fail("invalid_json", f"{label} is invalid JSON: {exc}")
    if not isinstance(data, dict):
        fail("invalid_document", f"{label} must be a JSON object.")
    return data


def safe_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value in {"", "."} or "\\" in value:
        fail("unsafe_path", f"Path is not a safe relative POSIX path: {value}")
    return str(path)


def load_run(state_path: Path) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    state_path = state_path.resolve()
    root = state_path.parent
    state = load_json(state_path, "Evaluation state")
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        fail("unsupported_state", f"Expected {STATE_SCHEMA_VERSION}.")
    manifest_rel = safe_relative_path(str(state.get("artifact_manifest_path", "artifact-manifest.json")))
    manifest_path = root / manifest_rel
    manifest = load_json(manifest_path, "Artifact manifest")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        fail("unsupported_manifest", f"Expected {MANIFEST_SCHEMA_VERSION}.")
    if manifest.get("evaluation_id") != state.get("evaluation_id"):
        fail("identity_mismatch", "State and artifact manifest evaluation IDs differ.")
    return state, manifest, root, manifest_path


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


def command_package(args: argparse.Namespace) -> None:
    state_path = Path(args.state)
    state, manifest, root, manifest_path = load_run(state_path)
    profile = args.profile
    included: dict[str, Path] = {
        "evaluation-state.json": state_path.resolve(),
        safe_relative_path(str(state["artifact_manifest_path"])): manifest_path,
    }
    excluded: list[dict[str, str]] = []

    for record in manifest.get("artifacts", []):
        if not isinstance(record, dict):
            fail("invalid_manifest_record", "Every manifest artifact must be an object.")
        relative = safe_relative_path(str(record.get("path", "")))
        visibility = record.get("visibility")
        if profile == "portable" and visibility == "restricted":
            excluded.append({"path": relative, "reason": "restricted_by_portable_profile"})
            continue
        if relative == "bundle-metadata.json" or relative.startswith("exports/"):
            excluded.append({"path": relative, "reason": "export_artifact_not_nested"})
            continue
        local = root.joinpath(*PurePosixPath(relative).parts)
        if not local.is_file():
            if record.get("retention") == "required":
                fail("required_artifact_missing", f"Required artifact is missing: {relative}")
            excluded.append({"path": relative, "reason": "missing_cache"})
            continue
        actual = sha256_file(local)
        if actual != record.get("sha256"):
            fail(
                "artifact_hash_mismatch",
                f"Artifact hash does not match the manifest: {relative}",
                {"recorded": record.get("sha256"), "actual": actual},
            )
        included[relative] = local

    included_paths = sorted(included)
    metadata = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "evaluation_id": state["evaluation_id"],
        "profile": profile,
        "created_at": now(),
        "state_sha256": sha256_file(state_path.resolve()),
        "manifest_sha256": sha256_file(manifest_path),
        "included_paths": included_paths,
        "excluded": sorted(excluded, key=lambda item: item["path"]),
    }
    output = Path(args.output).resolve() if args.output else default_output(
        root, state["evaluation_id"], args.command, profile
    )
    if output.exists() and not args.force:
        fail("output_exists", f"Refusing to overwrite existing bundle: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relative in included_paths:
                add_bytes(archive, relative, included[relative].read_bytes())
            add_bytes(
                archive,
                "bundle-metadata.json",
                (json.dumps(metadata, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
            )
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()

    emit({
        "command": args.command,
        "ok": True,
        "evaluation_id": state["evaluation_id"],
        "storage_mode": state.get("configuration", {}).get("storage_mode"),
        "profile": profile,
        "artifacts_written": [{"path": str(output), "sha256": sha256_file(output)}],
        "included_count": len(included_paths),
        "excluded_count": len(excluded),
        "next_actions": [],
        "warnings": [],
    })


def command_list(args: argparse.Namespace) -> None:
    state, manifest, _, _ = load_run(Path(args.state))
    artifacts = sorted(manifest.get("artifacts", []), key=lambda item: item.get("path", ""))
    emit({
        "command": "list-artifacts",
        "ok": True,
        "evaluation_id": state["evaluation_id"],
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "next_actions": [],
        "warnings": [],
    })


def is_symlink_member(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def command_import(args: argparse.Namespace) -> None:
    bundle = Path(args.input).resolve()
    if not bundle.is_file():
        fail("bundle_not_found", f"Bundle does not exist: {bundle}")
    output = Path(args.output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        fail("output_not_empty", f"Import directory must be new or empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(bundle, "r") as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            fail("duplicate_members", "Bundle contains duplicate member paths.")
        for info in infos:
            safe_relative_path(info.filename)
            if info.is_dir() or is_symlink_member(info):
                fail("unsupported_member", f"Bundle contains an unsupported member: {info.filename}")
        required = {"evaluation-state.json", "artifact-manifest.json", "bundle-metadata.json"}
        missing = sorted(required - set(names))
        if missing:
            fail("missing_control_files", "Bundle is missing required control files.", missing)
        try:
            metadata = json.loads(archive.read("bundle-metadata.json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            fail("invalid_bundle_metadata", f"Bundle metadata is invalid: {exc}")
        if metadata.get("schema_version") != BUNDLE_SCHEMA_VERSION:
            fail("unsupported_bundle", f"Expected {BUNDLE_SCHEMA_VERSION}.")
        expected_members = set(metadata.get("included_paths", [])) | {"bundle-metadata.json"}
        if set(names) != expected_members:
            fail(
                "bundle_inventory_mismatch",
                "ZIP members do not match bundle metadata.",
                {"expected": sorted(expected_members), "actual": sorted(names)},
            )

        for info in infos:
            relative = PurePosixPath(info.filename)
            target = output.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info.filename))

    state_path = output / "evaluation-state.json"
    manifest_path = output / "artifact-manifest.json"
    if sha256_file(state_path) != metadata.get("state_sha256"):
        fail("state_hash_mismatch", "Imported evaluation-state.json does not match bundle metadata.")
    if sha256_file(manifest_path) != metadata.get("manifest_sha256"):
        fail("manifest_hash_mismatch", "Imported artifact-manifest.json does not match bundle metadata.")
    state, manifest, _, _ = load_run(state_path)

    included = set(metadata.get("included_paths", []))
    errors: list[str] = []
    for record in manifest.get("artifacts", []):
        relative = safe_relative_path(str(record.get("path", "")))
        if relative not in included:
            continue
        local = output.joinpath(*PurePosixPath(relative).parts)
        if not local.is_file() or sha256_file(local) != record.get("sha256"):
            errors.append(relative)
    if errors:
        fail("imported_artifact_mismatch", "Imported artifacts failed hash validation.", errors)

    reconnect = [
        item["path"]
        for item in metadata.get("excluded", [])
        if item.get("reason") == "restricted_by_portable_profile"
    ]
    emit({
        "command": "import-bundle",
        "ok": True,
        "evaluation_id": state["evaluation_id"],
        "profile": metadata.get("profile"),
        "artifacts_written": [{"path": str(output), "type": "evaluation_directory"}],
        "reconnect_required": reconnect,
        "next_actions": ["validate", "status", "next"],
        "warnings": [] if not reconnect else ["Reconnect excluded restricted inputs by SHA-256 before dependent work."],
    })


def command_migrate_publication_profile(args: argparse.Namespace) -> None:
    bundle = Path(args.input).resolve()
    if not bundle.is_file():
        fail("bundle_not_found", f"Bundle does not exist: {bundle}")
    output = Path(args.output).resolve()
    if output.exists() and not args.force:
        fail("output_exists", f"Refusing to overwrite existing bundle: {output}")

    with zipfile.ZipFile(bundle, "r") as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            fail("duplicate_members", "Bundle contains duplicate member paths.")
        for info in infos:
            safe_relative_path(info.filename)
            if info.is_dir() or is_symlink_member(info):
                fail("unsupported_member", f"Bundle contains an unsupported member: {info.filename}")
        required = {"evaluation-state.json", "artifact-manifest.json", "bundle-metadata.json"}
        missing = sorted(required - set(names))
        if missing:
            fail("missing_control_files", "Bundle is missing required control files.", missing)
        members = {info.filename: archive.read(info.filename) for info in infos}

    try:
        metadata = json.loads(members["bundle-metadata.json"].decode("utf-8"))
        state = json.loads(members["evaluation-state.json"].decode("utf-8"))
        manifest = json.loads(members["artifact-manifest.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail("invalid_bundle_json", f"Bundle control JSON is invalid: {exc}")
    if not all(isinstance(item, dict) for item in (metadata, state, manifest)):
        fail("invalid_bundle_controls", "Bundle control files must be JSON objects.")
    if metadata.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        fail("unsupported_bundle", f"Expected {BUNDLE_SCHEMA_VERSION}.")
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        fail("unsupported_state", f"Expected {STATE_SCHEMA_VERSION}.")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        fail("unsupported_manifest", f"Expected {MANIFEST_SCHEMA_VERSION}.")
    if state.get("evaluation_id") != manifest.get("evaluation_id") or state.get("evaluation_id") != metadata.get("evaluation_id"):
        fail("identity_mismatch", "Bundle state, manifest, and metadata evaluation IDs differ.")
    expected_members = set(metadata.get("included_paths", [])) | {"bundle-metadata.json"}
    if set(names) != expected_members:
        fail(
            "bundle_inventory_mismatch",
            "ZIP members do not match bundle metadata.",
            {"expected": sorted(expected_members), "actual": sorted(names)},
        )
    if sha256_bytes(members["evaluation-state.json"]) != metadata.get("state_sha256"):
        fail("state_hash_mismatch", "Bundled evaluation-state.json does not match bundle metadata.")
    if sha256_bytes(members["artifact-manifest.json"]) != metadata.get("manifest_sha256"):
        fail("manifest_hash_mismatch", "Bundled artifact-manifest.json does not match bundle metadata.")

    included = set(metadata.get("included_paths", []))
    artifact_errors: list[str] = []
    for record in manifest.get("artifacts", []):
        if not isinstance(record, dict):
            fail("invalid_manifest_record", "Every manifest artifact must be an object.")
        relative = safe_relative_path(str(record.get("path", "")))
        if relative in included and sha256_bytes(members.get(relative, b"")) != record.get("sha256"):
            artifact_errors.append(relative)
    if artifact_errors:
        fail("artifact_hash_mismatch", "Bundled artifacts failed manifest hash validation.", artifact_errors)

    configuration = state.get("configuration")
    if not isinstance(configuration, dict):
        fail("invalid_configuration", "Evaluation state configuration must be an object.")
    explicit_profile = configuration.get("publication_profile")
    current_profile = explicit_profile if explicit_profile is not None else "aggregate_only"
    if current_profile not in PUBLICATION_PROFILES:
        fail("invalid_publication_profile", "The checkpoint publication profile is invalid.")
    if current_profile != args.from_profile:
        fail(
            "publication_profile_source_mismatch",
            "The checkpoint's effective publication profile differs from --from-profile.",
            {"expected": args.from_profile, "actual": current_profile, "explicit": explicit_profile is not None},
        )
    if explicit_profile == args.publication_profile:
        fail("migration_not_needed", "The checkpoint already explicitly selects the requested publication profile.")

    judgment_stages = ("locator_audit", "missing_access_audit", "structure_audit", "scoring")
    started = {
        name: state.get("stages", {}).get(name, {}).get("status")
        for name in judgment_stages
        if state.get("stages", {}).get(name, {}).get("status") not in {None, "not_started"}
    }
    audit_paths = sorted(
        name for name in names
        if "/locator-audits/" in name
        or "/missing-access-audits/" in name
        or name.startswith("validation/locator-audit-worker.")
        or name.startswith("validation/missing-access-audit-worker.")
    )
    if started or audit_paths:
        fail(
            "candidate_audit_migration_requires_revalidation",
            "Refusing an in-place checkpoint profile migration after candidate-audit work has started.",
            {"started_stages": started, "audit_paths": audit_paths},
        )

    source_bundle_sha256 = sha256_file(bundle)
    configuration["publication_profile"] = args.publication_profile
    state["updated_at"] = now()
    state_bytes = (json.dumps(state, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    members["evaluation-state.json"] = state_bytes
    metadata["created_at"] = now()
    metadata["state_sha256"] = sha256_bytes(state_bytes)
    metadata["publication_profile_migration"] = {
        "from": current_profile,
        "to": args.publication_profile,
        "source_bundle_sha256": source_bundle_sha256,
        "source_profile_was_explicit": explicit_profile is not None,
    }
    members["bundle-metadata.json"] = (json.dumps(metadata, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(members):
                add_bytes(archive, name, members[name])
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()

    emit({
        "command": "migrate-publication-profile",
        "ok": True,
        "evaluation_id": state["evaluation_id"],
        "from_profile": current_profile,
        "publication_profile": args.publication_profile,
        "source_profile_was_explicit": explicit_profile is not None,
        "source_bundle_sha256": source_bundle_sha256,
        "artifacts_written": [{"path": str(output), "sha256": sha256_file(output)}],
        "warnings": [],
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

    migration = subparsers.add_parser("migrate-publication-profile")
    migration.add_argument("--input", required=True)
    migration.add_argument("--output", required=True)
    migration.add_argument("--from-profile", choices=sorted(PUBLICATION_PROFILES), required=True)
    migration.add_argument("--publication-profile", choices=sorted(PUBLICATION_PROFILES), required=True)
    migration.add_argument("--force", action="store_true")
    migration.set_defaults(func=command_migrate_publication_profile)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
