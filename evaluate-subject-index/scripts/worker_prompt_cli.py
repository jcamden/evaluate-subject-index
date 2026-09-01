#!/usr/bin/env python3
"""Render collision-safe worker launch prompts from validated evaluation facts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
CHUNK_ID = re.compile(r"^CHUNK-[0-9]{3,}$")
PUBLICATION_PROFILES = {"aggregate_only", "public_evaluation_artifacts"}


class PromptSpecError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PromptSpecError(message)


def text_field(value: dict[str, Any], name: str) -> str:
    result = value.get(name)
    require(isinstance(result, str) and result.strip() == result and bool(result), f"{name} must be a nonempty string")
    return result


def sha_field(value: dict[str, Any], name: str) -> str:
    result = text_field(value, name)
    require(bool(SHA256.fullmatch(result)), f"{name} must be a lowercase SHA-256")
    return result


def relative_path(value: str, name: str) -> str:
    path = PurePosixPath(value)
    require(not path.is_absolute() and ".." not in path.parts and value == path.as_posix(), f"{name} must be a safe relative POSIX path")
    return value


def library_path(value: str, name: str) -> str:
    path = PurePosixPath(value)
    require(path.is_absolute() and ".." not in path.parts and value == path.as_posix(), f"{name} must be an absolute Library path")
    return value.rstrip("/")


def validate_spec(spec: dict[str, Any]) -> None:
    require(spec.get("schema_version") in {"locator-worker-prompt-pack-v1", "locator-worker-prompt-pack-v2"}, "unsupported schema_version")
    for name in ("evaluation_id", "candidate_id", "project", "base_branch", "benchmark_project", "checkpoint_filename"):
        text_field(spec, name)
    require(bool(COMMIT.fullmatch(text_field(spec, "base_commit"))), "base_commit must be a 40-character lowercase commit")
    require(bool(COMMIT.fullmatch(text_field(spec, "benchmark_ref"))), "benchmark_ref must be a 40-character lowercase commit")
    for name in (
        "benchmark_canonical_sha256", "source_sha256", "candidate_identity_sha256",
        "normalized_candidate_sha256", "item_inventory_sha256", "policy_file_sha256",
        "page_map_canonical_sha256", "chunk_manifest_canonical_sha256",
        "benchmark_lock_file_sha256", "benchmark_lock_canonical_sha256", "checkpoint_sha256",
    ):
        sha_field(spec, name)
    library_path(text_field(spec, "checkpoint_library_root"), "checkpoint_library_root")
    library_path(text_field(spec, "worker_library_root"), "worker_library_root")
    require(spec.get("publication_profile", "aggregate_only") in PUBLICATION_PROFILES, "publication_profile is invalid")
    chunks = spec.get("chunks")
    require(isinstance(chunks, list) and bool(chunks), "chunks must be a nonempty array")
    seen: set[str] = set()
    for index, chunk in enumerate(chunks):
        require(isinstance(chunk, dict), f"chunks[{index}] must be an object")
        chunk_id = text_field(chunk, "chunk_id")
        require(bool(CHUNK_ID.fullmatch(chunk_id)), f"chunks[{index}].chunk_id is invalid")
        require(chunk_id not in seen, f"duplicate chunk_id: {chunk_id}")
        seen.add(chunk_id)
        for name in ("source_unit", "owned_document_pages"):
            text_field(chunk, name)
        require(isinstance(chunk.get("expected_locator_assignments"), int) and chunk["expected_locator_assignments"] >= 0,
                f"chunks[{index}].expected_locator_assignments must be a nonnegative integer")
        for name in ("locator_packet_path", "source_materialize_path", "sidecar_materialize_path"):
            relative_path(text_field(chunk, name), f"chunks[{index}].{name}")
        for name in ("source_library_path", "sidecar_library_path"):
            library_path(text_field(chunk, name), f"chunks[{index}].{name}")
        for name in ("locator_packet_sha256", "source_sha256", "sidecar_sha256"):
            sha_field(chunk, name)


def validate_checkpoint(spec: dict[str, Any], checkpoint: Path) -> None:
    require(checkpoint.is_file(), f"checkpoint does not exist: {checkpoint}")
    payload = checkpoint.read_bytes()
    require(
        hashlib.sha256(payload).hexdigest() == spec["checkpoint_sha256"],
        "checkpoint bytes do not match checkpoint_sha256",
    )
    require(checkpoint.name == spec["checkpoint_filename"], "checkpoint filename differs from checkpoint_filename")
    try:
        with zipfile.ZipFile(checkpoint, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            require(len(names) == len(set(names)), "checkpoint contains duplicate member paths")
            required = {"evaluation-state.json", "artifact-manifest.json", "bundle-metadata.json"}
            require(required.issubset(names), "checkpoint is missing required control files")
            for info in infos:
                path = PurePosixPath(info.filename)
                mode = info.external_attr >> 16
                require(
                    not path.is_absolute() and ".." not in path.parts and "\\" not in info.filename,
                    f"checkpoint contains an unsafe member path: {info.filename}",
                )
                require(
                    not info.is_dir() and not stat.S_ISLNK(mode),
                    f"checkpoint contains an unsupported member: {info.filename}",
                )
            state_payload = archive.read("evaluation-state.json")
            manifest_payload = archive.read("artifact-manifest.json")
            state = json.loads(state_payload.decode("utf-8"))
            manifest = json.loads(manifest_payload.decode("utf-8"))
            metadata = json.loads(archive.read("bundle-metadata.json").decode("utf-8"))
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromptSpecError(f"checkpoint is invalid: {exc}") from exc
    require(isinstance(state, dict), "checkpoint evaluation-state.json must be an object")
    require(isinstance(manifest, dict), "checkpoint artifact-manifest.json must be an object")
    require(isinstance(metadata, dict), "checkpoint bundle-metadata.json must be an object")
    require(
        state.get("schema_version") == "subject-index-evaluation-state-v4",
        "checkpoint evaluation state schema is unsupported",
    )
    require(
        manifest.get("schema_version") == "subject-index-artifact-manifest-v1",
        "checkpoint artifact manifest schema is unsupported",
    )
    require(metadata.get("schema_version") == "subject-index-bundle-v1", "checkpoint bundle schema is unsupported")
    expected_members = set(metadata.get("included_paths", [])) | {"bundle-metadata.json"}
    require(set(names) == expected_members, "checkpoint members differ from bundle metadata")
    require(
        hashlib.sha256(state_payload).hexdigest() == metadata.get("state_sha256"),
        "checkpoint evaluation state hash differs from bundle metadata",
    )
    require(
        hashlib.sha256(manifest_payload).hexdigest() == metadata.get("manifest_sha256"),
        "checkpoint artifact manifest hash differs from bundle metadata",
    )
    require(state.get("evaluation_id") == spec["evaluation_id"], "checkpoint evaluation_id differs from prompt pack")
    require(manifest.get("evaluation_id") == spec["evaluation_id"], "checkpoint manifest evaluation_id differs from prompt pack")
    require(metadata.get("evaluation_id") == spec["evaluation_id"], "checkpoint metadata evaluation_id differs from prompt pack")
    configuration = state.get("configuration")
    require(isinstance(configuration, dict), "checkpoint configuration must be an object")
    require(
        "publication_profile" in configuration,
        "checkpoint omits configuration.publication_profile; run bundle_cli.py migrate-publication-profile before rendering prompts",
    )
    checkpoint_profile = configuration.get("publication_profile")
    prompt_profile = spec.get("publication_profile", "aggregate_only")
    require(checkpoint_profile in PUBLICATION_PROFILES, "checkpoint publication_profile is invalid")
    require(
        checkpoint_profile == prompt_profile,
        "checkpoint publication_profile differs from prompt pack publication_profile",
    )


def render_chunk(spec: dict[str, Any], chunk: dict[str, Any]) -> str:
    chunk_id = chunk["chunk_id"]
    lower_chunk = chunk_id.lower()
    recovery_root = f"{spec['worker_library_root'].rstrip('/')}/locator-audit/{chunk_id}/"
    publication_profile = spec.get("publication_profile", "aggregate_only")
    if publication_profile == "public_evaluation_artifacts":
        publication_instruction = f"""Preserve the complete audit, receipt, worker state, worker manifest, and recovery ZIP under the recovery root before publication. Publish the exact validated canonical audit bytes under `locator-audit-v2` at `candidate/locator-audits/locator-audit.{chunk_id}.v2.json` in one commit and one open, unmerged pull request. The public artifact must pass the strict canonical-audit allowlist, bounded-text, path, and secret scan. Do not publish source PDFs, PDF chunks, raw source text, receipts, recovery data, or control files; do not update canonical state or manifests, modify the benchmark repository, or merge the pull request."""
        binding_nouns = "public canonical audit and its identical recovery copy"
    else:
        publication_instruction = f"""Preserve the complete private audit, receipt, worker state, worker manifest, and recovery ZIP under the recovery root before publication. Publish exactly `validation/locator-audit-worker.{chunk_id}.json` in one commit and one open, unmerged pull request. Do not publish the complete audit, update canonical state or manifests, modify the benchmark repository, or merge the pull request."""
        binding_nouns = "public aggregate report and private audit"
    return f"""## {chunk_id} — {chunk['source_unit']}

```text
@Evaluate Subject Index worker-locator-audit {chunk_id} --project {spec['project']}

Resume the canonical evaluation in an isolated worker:

- Evaluation ID: {spec['evaluation_id']}
- Candidate ID: {spec['candidate_id']}
- Expected base branch: {spec['base_branch']}
- Immutable base commit: {spec['base_commit']}
- Benchmark project/ref: {spec['benchmark_project']} @ {spec['benchmark_ref']}
- Frozen benchmark canonical SHA-256: {spec['benchmark_canonical_sha256']}
- Source document SHA-256: {spec['source_sha256']}
- Candidate identity SHA-256: {spec['candidate_identity_sha256']}
- Normalized candidate file SHA-256: {spec['normalized_candidate_sha256']}
- Item inventory file SHA-256: {spec['item_inventory_sha256']}
- Policy file SHA-256: {spec['policy_file_sha256']}
- Page-map canonical SHA-256: {spec['page_map_canonical_sha256']}
- Chunk-manifest canonical SHA-256: {spec['chunk_manifest_canonical_sha256']}
- Candidate-benchmark-lock file/canonical SHA-256: {spec['benchmark_lock_file_sha256']} / {spec['benchmark_lock_canonical_sha256']}
- Publication profile: {publication_profile}

Import and fully validate this cumulative portable checkpoint from `{spec['checkpoint_library_root']}`:

- {spec['checkpoint_filename']}
- SHA-256: {spec['checkpoint_sha256']}

Worker scope:

- Chunk: {chunk_id}
- Source unit: {chunk['source_unit']}
- Owned document pages: {chunk['owned_document_pages']}
- Locator packet: `{chunk['locator_packet_path']}`
- Packet SHA-256: {chunk['locator_packet_sha256']}
- Expected locator assignments: {chunk['expected_locator_assignments']}

Before substantive work, retrieve these exact restricted artifacts from ChatGPT Library, materialize them at the evaluation-relative destinations, and hash-verify them:

- Library source: `{chunk['source_library_path']}`
  - Materialize as: `{chunk['source_materialize_path']}`
  - Required SHA-256: `{chunk['source_sha256']}`
- Library source: `{chunk['sidecar_library_path']}`
  - Materialize as: `{chunk['sidecar_materialize_path']}`
  - Required SHA-256: `{chunk['sidecar_sha256']}`

If either restricted source artifact is unavailable or has a different hash, stop as blocked. Use the unique private recovery root `workers/locator-audit/{chunk_id}/`. Use branch `locator-audit/{lower_chunk}`; refuse it if it already exists.

Audit every one of the {chunk['expected_locator_assignments']} packet assignments exactly once. Preserve the complete heading path, judge only this chunk's owned assignments, and use only `supported`, `partially_supported`, `unsupported`, or `uninspectable`.

During the same source inspection, answer two independent questions:

1. How substantively does the cited page treat the indexed subject?
2. Does that treatment accurately fit the complete heading path?

For every measured locator, record one concise, locator-specific, public-safe `evidence_summary` describing what the cited page contains and why the treatment class was assigned. Record a separate concise public-safe `fit_rationale` when page treatment and complete-path fit differ, fit is less than 100, structured classifiers conflict, or a supplemental decision will supply fit. A routine supported, substantive, exact-fit case may omit authored fit prose because the projection can explain it mechanically from the structured category and rule. Never substitute provenance boilerplate for either explanation. Also record evidence IDs, error codes, severity, and confidence. Do not perform missing-access, global-structure, density, item-assessment, scoring, or reporting work.

Use `parallel_candidate_audit_cli.py build-locator-worker`, `bind-publication`, and `validate-worker`. {publication_instruction}

After the pull request has been created, obtain a direct GitHub observation of its exact URL, number, open state, head branch and commit, base branch and commit, one-commit history, changed-path allowlist, and public-artifact blob/file hash. Run `bind-publication` with that observation, then rerun `validate-worker`. Save the resulting final publication-bound `locator-audit-worker-receipt.json` and its receipt-bound `locator-audit-worker-recovery.zip` to the existing Library recovery root `{recovery_root}`, replacing the earlier pre-publication receipt while preserving the canonical filenames. Verify that the saved final receipt names the exact pull-request URL and head commit and binds the {binding_nouns} plus the recovery ZIP. Do not modify or merge the pull request afterward.
```
"""


def render(spec: dict[str, Any]) -> str:
    validate_spec(spec)
    header = """# Worker locator-audit launch prompts

Use one prompt in each isolated chunk-level chat. These prompts do not authorize a worker to proceed until that chunk's restricted PDF and page sidecar have both been reconnected and verified by SHA-256. The candidate repository base branch was verified at the immutable commit below, and no selected `locator-audit/*` branch existed when this launch pack was prepared; every worker must check again and refuse a collision. Every prompt also requires the worker to persist its final publication-bound receipt—not merely its earlier pre-publication receipt—to the chunk-specific Library recovery root after opening the pull request.

"""
    return header + "\n".join(render_chunk(spec, chunk) for chunk in spec["chunks"])


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="operation", required=True)
    renderer = subparsers.add_parser("render-locator-pack")
    renderer.add_argument("--input", required=True)
    renderer.add_argument("--checkpoint", required=True)
    renderer.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        spec = json.loads(Path(args.input).read_text(encoding="utf-8"))
        require(isinstance(spec, dict), "input must be a JSON object")
        validate_spec(spec)
        validate_checkpoint(spec, Path(args.checkpoint))
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render(spec), encoding="utf-8")
    except (OSError, json.JSONDecodeError, PromptSpecError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({"ok": True, "operation": "render-locator-pack", "output": str(output), "chunk_count": len(spec["chunks"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
