"""Live item-inventory and V7 projection helpers."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def fail(code: str, message: str, details: Iterable[str] | None = None) -> None:
    payload: dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = list(details)
    emit(payload)
    raise SystemExit(1)


def stable_id(prefix: str, candidate_sha256: str, identity: Any) -> str:
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{candidate_sha256}\n{canonical}".encode("utf-8")).hexdigest()[:12].upper()
    return f"{prefix}-{digest}"

def grade(score: float | None, measured: bool = True) -> dict[str, Any]:
    if score is None or not measured:
        return {
            "score": None,
            "rating": None,
            "band": "not_measured",
            "color_token": "grade_neutral",
            "status": "not_measured",
        }
    bounded = round(max(0.0, min(100.0, score)), 2)
    if bounded >= 90:
        band, token, status = "excellent", "grade_excellent", "passes"
    elif bounded >= 80:
        band, token, status = "strong", "grade_strong", "passes_with_issues"
    elif bounded >= 70:
        band, token, status = "mixed", "grade_mixed", "needs_review"
    elif bounded >= 60:
        band, token, status = "weak", "grade_weak", "needs_revision"
    else:
        band, token, status = "poor", "grade_poor", "fails"
    return {
        "score": bounded,
        "rating": round(bounded / 20.0, 3),
        "band": band,
        "color_token": token,
        "status": status,
    }
def canonical_target(value: str) -> str:
    normalized = value.casefold().replace("–", "—")
    normalized = re.sub(r"\s*(?:—|--)\s*", "—", normalized)
    return re.sub(r"\s+", " ", normalized).strip()

def weighted_mean(values: Iterable[tuple[float | None, float]]) -> float | None:
    measured = [(value, weight) for value, weight in values if value is not None and weight > 0]
    if not measured:
        return None
    denominator = sum(weight for _, weight in measured)
    return sum(float(value) * weight for value, weight in measured) / denominator

def build_inventory(candidate: dict[str, Any]) -> dict[str, Any]:
    candidate_schema = candidate.get("schema_version")
    if candidate_schema != "candidate-index-v2":
        fail("candidate_schema", "Candidate schema must be candidate-index-v2.")
    candidate_sha = candidate.get("candidate_sha256")
    if not isinstance(candidate_sha, str) or not candidate_sha:
        fail("candidate_identity", "Candidate requires candidate_sha256.")
    records = candidate.get("records")
    if not isinstance(records, list):
        fail("candidate_shape", "Candidate requires a records array.")

    paths: list[dict[str, Any]] = []
    nodes_by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    locators: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    seen_path_ids: set[str] = set()
    seen_locator_ids: set[str] = set()
    seen_reference_ids: set[str] = set()

    for record in records:
        if not isinstance(record, dict):
            fail("candidate_shape", "Every candidate record must be an object.")
        path_id = record.get("path_id")
        record_id = record.get("record_id")
        heading_path = record.get("heading_path")
        if not isinstance(path_id, str) or path_id in seen_path_ids:
            fail("path_identity", f"Duplicate or missing path_id: {path_id}")
        if not isinstance(record_id, str) or not record_id:
            fail("record_identity", f"{path_id} requires a non-empty record_id.")
        valid_depth = isinstance(heading_path, list) and len(heading_path) >= 1
        if not valid_depth or not all(isinstance(item, str) and item for item in heading_path):
            fail("heading_path", f"{path_id} requires one or more non-empty string heading levels.")
        seen_path_ids.add(path_id)

        node_ids: list[str] = []
        for level in range(1, len(heading_path) + 1):
            key = tuple(heading_path[:level])
            node = nodes_by_key.get(key)
            if node is None:
                node_id = stable_id("NODE", candidate_sha, {"heading_path": list(key)})
                parent_key = key[:-1]
                node = {
                    "node_id": node_id,
                    "level": level,
                    "role": "main_heading" if level == 1 else "subheading",
                    "label": key[-1],
                    "heading_path": list(key),
                    "parent_node_id": nodes_by_key[parent_key]["node_id"] if parent_key else None,
                    "path_ids": [],
                    "record_ids": [],
                    "direct_path_ids": [],
                }
                nodes_by_key[key] = node
            node_ids.append(node["node_id"])
            if path_id not in node["path_ids"]:
                node["path_ids"].append(path_id)
            if isinstance(record_id, str) and record_id not in node["record_ids"]:
                node["record_ids"].append(record_id)
        nodes_by_key[tuple(heading_path)]["direct_path_ids"].append(path_id)

        locator_ids: list[str] = []
        for assignment in record.get("locator_assignments", []):
            locator_id = assignment.get("locator_id")
            if not isinstance(locator_id, str) or locator_id in seen_locator_ids:
                fail("locator_identity", f"Duplicate or missing locator_id: {locator_id}")
            seen_locator_ids.add(locator_id)
            locator_ids.append(locator_id)
            locators.append({
                "locator_id": locator_id,
                "path_id": path_id,
                "node_ids": node_ids,
                "source_page_label": assignment.get("source_page_label"),
                "document_page": assignment.get("document_page"),
                "mapping_status": assignment.get("mapping_status"),
            })

        reference_ids: list[str] = []
        cross_references = record.get("cross_references")
        if not isinstance(cross_references, list):
            fail("cross_reference_shape", f"{path_id}.cross_references must be an array.")
        if record.get("record_type") == "cross_reference" and not cross_references:
            fail("cross_reference_shape", f"{path_id} is a cross-reference without a reference object.")
        for reference_index, reference in enumerate(cross_references):
            if not isinstance(reference, dict):
                fail("cross_reference_shape", f"{path_id} has a non-object cross-reference.")
            if reference.get("type") not in {"see", "see also"} or not isinstance(reference.get("target"), str) or not reference.get("target"):
                fail("cross_reference_shape", f"{path_id} requires valid see/see also references with non-empty targets.")
            identity = {"record_id": record_id, "path_id": path_id, "reference_index": reference_index}
            reference_id = reference.get("reference_id") or stable_id("XREF", candidate_sha, identity)
            if not isinstance(reference_id, str) or reference_id in seen_reference_ids:
                fail("cross_reference_identity", f"Duplicate or invalid cross-reference identity: {reference_id}")
            seen_reference_ids.add(reference_id)
            reference_ids.append(reference_id)
            references.append({
                "reference_id": reference_id,
                "record_id": record_id,
                "source_path_id": path_id,
                "source_node_id": node_ids[-1],
                "reference_type": reference.get("type"),
                "target_display": reference.get("target"),
                "target_path_id": reference.get("target_path_id"),
            })

        path_record = {
            "path_id": path_id,
            "record_id": record_id,
            "record_type": record.get("record_type"),
            "heading_path": heading_path,
            "node_ids": node_ids,
            "locator_ids": locator_ids,
            "reference_ids": reference_ids,
        }
        paths.append(path_record)

    nodes = sorted(nodes_by_key.values(), key=lambda item: (item["heading_path"], item["node_id"]))
    for node in nodes:
        node["path_ids"].sort()
        node["record_ids"].sort()
        node["direct_path_ids"].sort()
    target_index: dict[str, list[str]] = {}
    for path in paths:
        display = "—".join(path["heading_path"])
        target_index.setdefault(canonical_target(display), []).append(path["path_id"])
    for reference in references:
        if reference.get("target_path_id") is None and isinstance(reference.get("target_display"), str):
            matches = target_index.get(canonical_target(reference["target_display"]), [])
            if len(matches) == 1:
                reference["target_path_id"] = matches[0]
    return {
        "schema_version": "subject-index-item-inventory-v2",
        "candidate_id": candidate.get("candidate_id"),
        "candidate_sha256": candidate_sha,
        "paths": sorted(paths, key=lambda item: item["path_id"]),
        "heading_nodes": nodes,
        "locators": sorted(locators, key=lambda item: item["locator_id"]),
        "cross_references": sorted(references, key=lambda item: item["reference_id"]),
        "counts": {
            "paths": len(paths),
            "heading_nodes": len(nodes),
            "locators": len(locators),
            "cross_references": len(references),
        },
    }


def rebuild_summary(result: dict[str, Any]) -> None:
    collections = {
        "locators": result["locator_assessments"],
        "paths": result["path_assessments"],
        "heading_nodes": result["heading_node_assessments"],
        "cross_references": result["cross_reference_assessments"],
        "source_subjects": result["source_subject_assessments"],
    }
    result["summary"] = {
        name: {
            "total": len(items),
            "graded": sum(item["grade"]["score"] is not None for item in items),
            "not_measured": sum(item["grade"]["score"] is None for item in items),
            "bands": {
                band: sum(item["grade"]["band"] == band for item in items)
                for band in ("excellent", "strong", "mixed", "weak", "poor", "not_measured")
            },
        }
        for name, items in collections.items()
    }
