#!/usr/bin/env python3
"""Render lightweight locator-audit prompts for isolated chats."""

from __future__ import annotations

import argparse
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from schema_validation import schema_errors


class PromptSpecError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PromptSpecError(message)


def relative_path(value: str, name: str) -> str:
    path = PurePosixPath(value)
    require(not path.is_absolute() and ".." not in path.parts and value == path.as_posix(), f"{name} must be a safe relative POSIX path")
    return value


def library_path(value: str, name: str) -> str:
    path = PurePosixPath(value)
    require(path.is_absolute() and ".." not in path.parts and value == path.as_posix(), f"{name} must be an absolute Library path")
    return value.rstrip("/")


def validate_spec(spec: dict[str, Any]) -> None:
    errors = schema_errors(spec, "locator-worker-prompt-pack.schema.json")
    require(not errors, "prompt pack is structurally invalid: " + "; ".join(errors))
    library_path(spec["checkpoint_library_root"], "checkpoint_library_root")
    library_path(spec["worker_library_root"], "worker_library_root")
    seen: set[str] = set()
    for index, chunk in enumerate(spec["chunks"]):
        require(chunk["chunk_id"] not in seen, f"duplicate chunk_id: {chunk['chunk_id']}")
        seen.add(chunk["chunk_id"])
        for name in ("locator_packet_path", "source_materialize_path", "sidecar_materialize_path"):
            relative_path(chunk[name], f"chunks[{index}].{name}")
        for name in ("source_library_path", "sidecar_library_path"):
            library_path(chunk[name], f"chunks[{index}].{name}")


def validate_checkpoint(spec: dict[str, Any], checkpoint: Path) -> None:
    require(checkpoint.is_file(), f"checkpoint does not exist: {checkpoint}")
    try:
        with zipfile.ZipFile(checkpoint, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            require(len(names) == len(set(names)), "checkpoint contains duplicate member paths")
            require({"evaluation-state.json", "bundle-metadata.json"}.issubset(names), "checkpoint is missing required control files")
            for info in infos:
                path = PurePosixPath(info.filename)
                require(not path.is_absolute() and ".." not in path.parts and "\\" not in info.filename, f"checkpoint contains an unsafe member path: {info.filename}")
                require(not info.is_dir() and not stat.S_ISLNK(info.external_attr >> 16), f"checkpoint contains an unsupported member: {info.filename}")
            state = json.loads(archive.read("evaluation-state.json").decode("utf-8"))
            metadata = json.loads(archive.read("bundle-metadata.json").decode("utf-8"))
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromptSpecError(f"checkpoint is invalid: {exc}") from exc
    state_errors = schema_errors(state, "evaluation-state.schema.json")
    metadata_errors = schema_errors(metadata, "bundle-metadata.schema.json")
    require(not state_errors, "checkpoint evaluation state is structurally invalid: " + "; ".join(state_errors))
    require(not metadata_errors, "checkpoint bundle metadata is structurally invalid: " + "; ".join(metadata_errors))
    require(set(names) == set(metadata.get("included_paths", [])) | {"bundle-metadata.json"}, "checkpoint members differ from bundle metadata")
    require(state.get("evaluation_id") == spec["evaluation_id"], "checkpoint evaluation_id differs from prompt pack")


def render_chunk(spec: dict[str, Any], chunk: dict[str, Any]) -> str:
    chunk_id = chunk["chunk_id"]
    recovery_root = f"{spec['worker_library_root'].rstrip('/')}/locator-audit/{chunk_id}/"
    return f"""## {chunk_id} — {chunk['source_unit']}

```text
@Evaluate Subject Index audit-locators {chunk_id}

Resume evaluation `{spec['evaluation_id']}` for candidate `{spec['candidate_id']}` in an isolated chat. Import `{spec['checkpoint_filename']}` from `{spec['checkpoint_library_root']}` as a recovery copy. Validate its structure; no previous archive hash is required.

Scope:

- Owned document pages: {chunk['owned_document_pages']}
- Locator packet: `{chunk['locator_packet_path']}`
- Expected locator assignments: {chunk['expected_locator_assignments']}

Retrieve the restricted source chunk from `{chunk['source_library_path']}` and materialize it as `{chunk['source_materialize_path']}`. Retrieve its page sidecar from `{chunk['sidecar_library_path']}` and materialize it as `{chunk['sidecar_materialize_path']}`. If either is unavailable, stop as blocked.

Audit every packet assignment exactly once. Preserve the complete heading path and use only `supported`, `partially_supported`, `unsupported`, or `uninspectable`. Record page treatment and complete-path fit independently, plus a concise evidence summary, any required fit rationale, evidence IDs, error codes, severity, and confidence. Do not perform missing-access, global-structure, density, scoring, or reporting work.

Validate the completed `locator-audit-v2`, save it under `{recovery_root}`, and return its path. A branch or pull request may be used for review, but neither is required.
```
"""


def render(spec: dict[str, Any]) -> str:
    validate_spec(spec)
    header = """# Worker locator-audit launch prompts

Use one prompt per isolated chunk chat. Checkpoints and branches are recovery or review conveniences, not integrity authorities.

"""
    return header + "\n".join(render_chunk(spec, chunk) for chunk in spec["chunks"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    renderer = subparsers.add_parser("render-locator-pack")
    renderer.add_argument("--input", required=True)
    renderer.add_argument("--checkpoint", required=True)
    renderer.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        spec = json.loads(Path(args.input).read_text(encoding="utf-8"))
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
