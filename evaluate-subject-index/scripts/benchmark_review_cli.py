#!/usr/bin/env python3
"""Deterministic inventories and completion gates for source-benchmark review."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


INVENTORY_SCHEMA = "source-benchmark-review-inventory-v1"
REVIEW_SCHEMA = "source-benchmark-review-v1"


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail("file_not_found", f"File does not exist: {path}")
    except json.JSONDecodeError as exc:
        fail("invalid_json", f"Could not parse {path}: {exc}")
    if not isinstance(value, dict):
        fail("invalid_root", f"JSON root must be an object: {path}")
    return value


def save_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: dict[str, Any]) -> str:
    clone = dict(value)
    clone.pop("benchmark_sha256", None)
    encoded = json.dumps(clone, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def benchmark_content_hash(value: dict[str, Any]) -> str:
    """Hash editorial benchmark content while ignoring draft/freeze wrapper fields."""
    clone = dict(value)
    for field in ("schema_version", "benchmark_sha256", "synthesis", "freeze"):
        clone.pop(field, None)
    encoded = json.dumps(clone, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_label(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.findall(r"[a-z0-9]+", folded))


def emit(payload: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


def fail(code: str, message: str, details: Any = None) -> None:
    payload: dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    emit(payload, 1)


def require_list(value: dict[str, Any], key: str) -> list[Any]:
    result = value.get(key)
    if not isinstance(result, list):
        fail("invalid_benchmark", f"Benchmark field must be an array: {key}")
    return result


def subject_id(subject: dict[str, Any]) -> str:
    return str(subject.get("subject_id", ""))


def relationship_id(relationship: dict[str, Any]) -> str:
    return str(relationship.get("relationship_id", ""))


def task_id(task: dict[str, Any]) -> str:
    return str(task.get("task_id", ""))


def final_benchmark_structure_errors(benchmark: dict[str, Any]) -> list[str]:
    """Validate the shared current frozen-benchmark content contract."""
    errors: list[str] = []
    subjects = benchmark.get("subjects")
    relationships = benchmark.get("relationships")
    tasks = benchmark.get("reader_tasks")
    if not isinstance(subjects, list) or not isinstance(relationships, list) or not isinstance(tasks, list):
        return ["subjects, relationships, and reader_tasks must be arrays."]
    subject_ids: list[str] = []
    for subject in subjects:
        valid = (
            isinstance(subject, dict)
            and isinstance(subject.get("subject_id"), str) and subject["subject_id"].startswith("SUBJ-")
            and isinstance(subject.get("label"), str) and bool(subject["label"].strip())
            and subject.get("priority") in {"essential", "major", "optional", "exclude_by_default"}
            and isinstance(subject.get("meaning"), str) and bool(subject["meaning"].strip())
            and isinstance(subject.get("stance"), str) and bool(subject["stance"].strip())
            and isinstance(subject.get("acceptable_access"), list) and bool(subject["acceptable_access"])
            and all(isinstance(value, str) and bool(value.strip()) for value in subject["acceptable_access"])
            and isinstance(subject.get("evidence"), list) and bool(subject["evidence"])
            and all(isinstance(value, dict) and bool(value) for value in subject["evidence"])
        )
        if not valid:
            errors.append("Every subject must satisfy the nonempty frozen subject contract.")
        elif isinstance(subject, dict):
            subject_ids.append(subject["subject_id"])
    if len(subject_ids) != len(set(subject_ids)):
        errors.append("Subject identifiers must be unique.")
    known_subject_ids = set(subject_ids)
    relationship_ids: list[str] = []
    for relationship in relationships:
        has_target_id = isinstance(relationship, dict) and "target_subject_id" in relationship
        has_target_label = isinstance(relationship, dict) and "target_label" in relationship
        valid = (
            isinstance(relationship, dict)
            and isinstance(relationship.get("relationship_id"), str) and relationship["relationship_id"].startswith("REL-")
            and relationship.get("source_subject_id") in known_subject_ids
            and isinstance(relationship.get("relationship_type", relationship.get("type")), str)
            and bool(relationship.get("relationship_type", relationship.get("type")).strip())
            and isinstance(relationship.get("resolution_status"), str) and bool(relationship["resolution_status"].strip())
            and has_target_id != has_target_label
            and (not has_target_id or relationship.get("target_subject_id") in known_subject_ids)
            and (not has_target_label or (isinstance(relationship.get("target_label"), str) and bool(relationship["target_label"].strip())))
        )
        if not valid:
            errors.append("Every relationship must identify a known source, type, status, and known or labeled target.")
        elif isinstance(relationship, dict):
            relationship_ids.append(relationship["relationship_id"])
    if len(relationship_ids) != len(set(relationship_ids)):
        errors.append("Relationship identifiers must be unique.")
    task_ids: list[str] = []
    for task in tasks:
        valid = (
            isinstance(task, dict)
            and isinstance(task.get("task_id"), str) and task["task_id"].startswith("TASK-")
            and isinstance(task.get("question"), str) and bool(task["question"].strip())
            and isinstance(task.get("subject_ids"), list) and bool(task["subject_ids"])
            and all(isinstance(value, str) for value in task["subject_ids"])
            and len(task["subject_ids"]) == len(set(task["subject_ids"]))
            and set(task["subject_ids"]).issubset(known_subject_ids)
        )
        if not valid:
            errors.append("Every reader task must have a nonempty question and at least one known subject.")
        elif isinstance(task, dict):
            task_ids.append(task["task_id"])
    if len(task_ids) != len(set(task_ids)):
        errors.append("Reader-task identifiers must be unique.")
    return errors


def build_inventory(draft_path: Path, threshold: float) -> dict[str, Any]:
    draft = load_json(draft_path)
    subjects = require_list(draft, "subjects")
    relationships = require_list(draft, "relationships")
    tasks = require_list(draft, "reader_tasks")
    subject_ids = [subject_id(item) for item in subjects]
    relationship_ids = [relationship_id(item) for item in relationships]
    task_ids = [task_id(item) for item in tasks]
    if any(not item.startswith("SUBJ-") for item in subject_ids):
        fail("invalid_subject_id", "Every benchmark subject must have a SUBJ-* identifier.")
    if len(subject_ids) != len(set(subject_ids)):
        fail("duplicate_subject_id", "Benchmark subject identifiers must be unique.")
    if any(not item.startswith("REL-") for item in relationship_ids):
        fail("invalid_relationship_id", "Every benchmark relationship must have a REL-* identifier.")
    if len(relationship_ids) != len(set(relationship_ids)):
        fail("duplicate_relationship_id", "Benchmark relationship identifiers must be unique.")
    if any(not item.startswith("TASK-") for item in task_ids):
        fail("invalid_task_id", "Every reader task must have a TASK-* identifier.")
    if len(task_ids) != len(set(task_ids)):
        fail("duplicate_task_id", "Reader-task identifiers must be unique.")

    labels: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in subjects:
        labels[normalize_label(str(item.get("label", "")))].append(item)
    exact_groups = [
        {"normalized_label": label, "subject_ids": [subject_id(item) for item in group], "labels": [item.get("label") for item in group]}
        for label, group in sorted(labels.items())
        if label and len(group) > 1
    ]

    normalized = [(subject_id(item), str(item.get("label", "")), normalize_label(str(item.get("label", "")))) for item in subjects]
    near_pairs: list[dict[str, Any]] = []
    for index, (left_id, left_label, left_normalized) in enumerate(normalized):
        if not left_normalized:
            continue
        for right_id, right_label, right_normalized in normalized[index + 1:]:
            if not right_normalized or left_normalized == right_normalized:
                continue
            ratio = SequenceMatcher(None, left_normalized, right_normalized).ratio()
            if ratio >= threshold:
                near_pairs.append({
                    "left_subject_id": left_id,
                    "left_label": left_label,
                    "right_subject_id": right_id,
                    "right_label": right_label,
                    "similarity": round(ratio, 4),
                })

    cross_chapter = [
        subject_id(item)
        for item in subjects
        if isinstance(item.get("chapter_provenance"), list) and len(item["chapter_provenance"]) > 1
    ]
    unresolved = [
        relationship_id(item)
        for item in relationships
        if item.get("resolution_status", "resolved") != "resolved"
    ]
    fallback_tasks = [
        task_id(item)
        for item in tasks
        if item.get("fallback_generated") is True
        or ("source_task_ids" in item and isinstance(item.get("source_task_ids"), list) and not item["source_task_ids"])
    ]
    task_subject_ids = {
        str(item)
        for task in tasks
        for item in (task.get("subject_ids") if isinstance(task.get("subject_ids"), list) else [])
    }
    subject_id_set = set(subject_ids)
    invalid_relationship_targets = [
        relationship_id(item)
        for item in relationships
        if item.get("target_subject_id") and item.get("target_subject_id") not in subject_id_set
    ]
    invalid_task_subject_ids = sorted(task_subject_ids - subject_id_set)
    missing_tasks = sorted(subject_id_set - task_subject_ids)
    missing_fields: dict[str, list[str]] = {}
    for item in subjects:
        missing = []
        for field in ("label", "meaning", "stance"):
            if not str(item.get(field, "")).strip():
                missing.append(field)
        for field in ("acceptable_access", "evidence"):
            if not isinstance(item.get(field), list) or not item[field]:
                missing.append(field)
        if missing:
            missing_fields[subject_id(item)] = missing

    priority_counts = Counter(str(item.get("priority", "missing")) for item in subjects)
    scored_count = priority_counts.get("essential", 0) + priority_counts.get("major", 0)
    unresolved_share = len(unresolved) / len(relationships) if relationships else 0.0
    scored_share = scored_count / len(subjects) if subjects else 0.0
    warnings: list[str] = []
    if exact_groups:
        warnings.append("Exact duplicate normalized labels require semantic disposition.")
    if near_pairs:
        warnings.append("Near-duplicate labels are diagnostic candidates, not automatic merges.")
    if unresolved:
        warnings.append("Every non-resolved relationship requires an individual editorial disposition.")
    if fallback_tasks:
        warnings.append("Every fallback-generated reader task requires independent editorial review.")
    if scored_share >= 0.9:
        warnings.append("Essential-plus-major priority share is at least 90%; review significance without imposing a quota.")

    return {
        "schema_version": INVENTORY_SCHEMA,
        "evaluation_id": draft.get("evaluation_id"),
        "draft": {
            "path": draft_path.name,
            "version": draft.get("version"),
            "file_sha256": file_sha256(draft_path),
            "canonical_sha256": canonical_hash(draft),
            "candidate_blindness": draft.get("candidate_blindness"),
        },
        "review_requirements": {
            "independent_fresh_context_required_for_full_mode": True,
            "candidate_must_remain_unseen": True,
            "density_is_not_a_subject_or_priority_quota": True,
            "full_mode_requires_complete_id_coverage": True,
        },
        "denominators": {
            "subjects": len(subjects),
            "relationships": len(relationships),
            "reader_tasks": len(tasks),
            "cross_chapter_subjects": len(cross_chapter),
            "unresolved_relationships": len(unresolved),
            "fallback_reader_tasks": len(fallback_tasks),
            "exclusions": len(draft.get("exclusions", [])) if isinstance(draft.get("exclusions"), list) else 0,
            "uncertainties": len(draft.get("uncertainties", [])) if isinstance(draft.get("uncertainties"), list) else 0,
        },
        "queues": {
            "subject_ids": subject_ids,
            "relationship_ids": relationship_ids,
            "reader_task_ids": task_ids,
            "cross_chapter_subject_ids": cross_chapter,
            "unresolved_relationship_ids": unresolved,
            "fallback_reader_task_ids": fallback_tasks,
            "exact_duplicate_label_groups": exact_groups,
            "near_duplicate_label_pairs": sorted(near_pairs, key=lambda item: (-item["similarity"], item["left_subject_id"], item["right_subject_id"])),
            "subjects_missing_reader_tasks": missing_tasks,
            "subjects_missing_required_fields": missing_fields,
            "invalid_relationship_target_ids": invalid_relationship_targets,
            "invalid_task_subject_ids": invalid_task_subject_ids,
        },
        "diagnostics": {
            "priority_distribution": dict(sorted(priority_counts.items())),
            "essential_plus_major_share": round(scored_share, 6),
            "relationship_resolution_distribution": dict(sorted(Counter(str(item.get("resolution_status", "resolved")) for item in relationships).items())),
            "unresolved_relationship_share": round(unresolved_share, 6),
            "near_duplicate_threshold": threshold,
            "warnings": warnings,
        },
    }


def set_of_strings(value: Any, field: str, errors: list[str]) -> set[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        errors.append(f"{field} must be an array of strings.")
        return set()
    if len(value) != len(set(value)):
        errors.append(f"{field} contains duplicate identifiers.")
    return set(value)


def validate_review_data(draft_path: Path, inventory_path: Path, review_path: Path) -> tuple[list[str], dict[str, Any]]:
    draft = load_json(draft_path)
    inventory = load_json(inventory_path)
    review = load_json(review_path)
    errors: list[str] = []
    if inventory.get("schema_version") != INVENTORY_SCHEMA:
        errors.append("Unsupported review inventory schema.")
    if review.get("schema_version") != REVIEW_SCHEMA:
        errors.append("Unsupported benchmark review schema.")
    for value, label in ((inventory, "inventory"), (review, "review")):
        if value.get("evaluation_id") != draft.get("evaluation_id"):
            errors.append(f"{label} evaluation_id does not match the draft.")
    draft_ref = review.get("draft", {}) if isinstance(review.get("draft"), dict) else {}
    if draft_ref.get("file_sha256") != file_sha256(draft_path):
        errors.append("Review draft file_sha256 does not match the supplied draft.")
    if draft_ref.get("canonical_sha256") != canonical_hash(draft):
        errors.append("Review draft canonical_sha256 does not match the supplied draft.")
    if review.get("candidate_blindness") != "preserved":
        errors.append("Candidate blindness must be preserved for an approved benchmark review.")
    independence = review.get("reviewer_independence", {}) if isinstance(review.get("reviewer_independence"), dict) else {}
    if not independence.get("candidate_unseen"):
        errors.append("The benchmark reviewer must attest that the candidate remained unseen.")
    if independence.get("source_reconnected_sha256") != draft.get("source_sha256"):
        errors.append("The reviewer source hash does not match the benchmark source hash.")
    coverage = review.get("coverage", {}) if isinstance(review.get("coverage"), dict) else {}
    queue = inventory.get("queues", {}) if isinstance(inventory.get("queues"), dict) else {}
    comparisons = (
        ("subject_ids_reviewed", "subject_ids"),
        ("relationship_ids_reviewed", "relationship_ids"),
        ("reader_task_ids_reviewed", "reader_task_ids"),
        ("cross_chapter_subject_ids_reviewed", "cross_chapter_subject_ids"),
        ("unresolved_relationship_ids_dispositioned", "unresolved_relationship_ids"),
        ("fallback_reader_task_ids_reviewed", "fallback_reader_task_ids"),
    )
    review_mode = review.get("review_mode")
    if review_mode not in {"full", "pilot"}:
        errors.append("review_mode must be full or pilot.")
    if review_mode == "full" and not independence.get("fresh_context"):
        errors.append("Full benchmark review requires a fresh independent context.")
    for reviewed_field, expected_field in comparisons:
        reviewed_ids = set_of_strings(coverage.get(reviewed_field), f"coverage.{reviewed_field}", errors)
        expected_ids = set_of_strings(queue.get(expected_field), f"inventory.queues.{expected_field}", errors)
        if not reviewed_ids.issubset(expected_ids):
            errors.append(f"coverage.{reviewed_field} contains identifiers outside the inventory.")
        if review_mode == "full" and reviewed_ids != expected_ids:
            errors.append(f"Full review has incomplete coverage for {reviewed_field}: expected {len(expected_ids)}, reviewed {len(reviewed_ids)}.")
    completion = review.get("completion", {}) if isinstance(review.get("completion"), dict) else {}
    if review_mode == "full":
        for field in ("structural_validation_passed", "editorial_review_complete", "source_first_omission_review_complete", "candidate_blindness_preserved", "no_unreviewed_required_items", "public_claims_allowed"):
            if completion.get(field) is not True:
                errors.append(f"Full review completion.{field} must be true.")
    elif completion.get("public_claims_allowed") is not False:
        errors.append("Pilot benchmark review must set completion.public_claims_allowed to false.")
    changes = review.get("changes")
    required_change_fields = ("merges", "splits", "priority_changes", "relationship_changes", "reader_task_changes", "subjects_added", "subjects_removed", "terminology_changes")
    if not isinstance(changes, dict):
        errors.append("changes must be an object.")
    else:
        for field in required_change_fields:
            if not isinstance(changes.get(field), list):
                errors.append(f"changes.{field} must be an array.")
    recommendation = review.get("recommendation")
    if recommendation not in {"retain_draft", "approve_revised", "revise_before_freeze", "blocked"}:
        errors.append("Unsupported review recommendation.")
    if review_mode == "pilot" and recommendation in {"retain_draft", "approve_revised"}:
        errors.append("Pilot review cannot approve a benchmark for final freeze.")
    return errors, review


def command_screen(args: argparse.Namespace) -> None:
    if not 0.0 < args.near_duplicate_threshold <= 1.0:
        fail("invalid_threshold", "near-duplicate-threshold must be greater than 0 and no more than 1.")
    output = Path(args.output)
    result = build_inventory(Path(args.draft), args.near_duplicate_threshold)
    save_json(output, result)
    emit({
        "command": "screen",
        "ok": True,
        "evaluation_id": result.get("evaluation_id"),
        "inventory_path": str(output.resolve()),
        "denominators": result["denominators"],
        "diagnostics": result["diagnostics"],
    })


def command_validate_review(args: argparse.Namespace) -> None:
    errors, review = validate_review_data(Path(args.draft), Path(args.inventory), Path(args.review))
    emit({
        "command": "validate-review",
        "ok": not errors,
        "evaluation_id": review.get("evaluation_id"),
        "review_mode": review.get("review_mode"),
        "recommendation": review.get("recommendation"),
        "errors": errors,
        "warnings": [],
    }, 0 if not errors else 1)


def command_validate_final(args: argparse.Namespace) -> None:
    draft_path = Path(args.draft)
    final_path = Path(args.final)
    errors, review = validate_review_data(draft_path, Path(args.inventory), Path(args.review))
    draft = load_json(draft_path)
    final = load_json(final_path)
    errors.extend(final_benchmark_structure_errors(final))
    for field in ("evaluation_id", "source_sha256", "policy_sha256", "page_map_sha256", "chunk_manifest_sha256"):
        if final.get(field) != draft.get(field):
            errors.append(f"Final benchmark changed frozen identity field: {field}")
    if final.get("candidate_blindness") != "preserved":
        errors.append("Final benchmark candidate blindness must be preserved.")
    stored_hash = final.get("benchmark_sha256")
    actual_hash = canonical_hash(final)
    if stored_hash != actual_hash:
        errors.append("Final benchmark canonical hash does not recompute.")
    recommendation = review.get("recommendation")
    same_bytes = file_sha256(draft_path) == file_sha256(final_path)
    same_canonical_content = benchmark_content_hash(draft) == benchmark_content_hash(final)
    if recommendation == "retain_draft":
        if not same_canonical_content:
            errors.append("retain_draft review must preserve the draft's canonical benchmark content.")
        if final.get("version") != draft.get("version"):
            errors.append("retain_draft review must retain the draft version.")
    elif recommendation == "approve_revised":
        if same_bytes:
            errors.append("approve_revised review requires a substantively different final benchmark.")
        if not isinstance(final.get("version"), int) or final.get("version", 0) <= draft.get("version", 0):
            errors.append("A revised benchmark must increment the benchmark version.")
    else:
        errors.append("Review recommendation does not authorize final freeze.")
    emit({
        "command": "validate-final",
        "ok": not errors,
        "evaluation_id": final.get("evaluation_id"),
        "version": final.get("version"),
        "benchmark_sha256": actual_hash,
        "errors": errors,
        "warnings": [],
    }, 0 if not errors else 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    screen = subparsers.add_parser("screen")
    screen.add_argument("--draft", required=True)
    screen.add_argument("--output", required=True)
    screen.add_argument("--near-duplicate-threshold", type=float, default=0.93)
    screen.set_defaults(func=command_screen)
    review = subparsers.add_parser("validate-review")
    review.add_argument("--draft", required=True)
    review.add_argument("--inventory", required=True)
    review.add_argument("--review", required=True)
    review.set_defaults(func=command_validate_review)
    final = subparsers.add_parser("validate-final")
    final.add_argument("--draft", required=True)
    final.add_argument("--inventory", required=True)
    final.add_argument("--review", required=True)
    final.add_argument("--final", required=True)
    final.set_defaults(func=command_validate_final)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
