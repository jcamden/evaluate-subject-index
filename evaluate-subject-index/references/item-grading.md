# Diagnostic item grading and interactive display

## Contents

- [Purpose](#purpose)
- [Artifacts and identities](#artifacts-and-identities)
- [What each grade means](#what-each-grade-means)
- [Color bands](#color-bands)
- [Locator grades](#locator-grades)
- [Complete-path grades](#complete-path-grades)
- [Heading-node grades](#heading-node-grades)
- [Cross-reference grades](#cross-reference-grades)
- [Source-subject access grades](#source-subject-access-grades)
- [Popover contract](#popover-contract)
- [Full and pilot audits](#full-and-pilot-audits)
- [Validation](#validation)

## Purpose

Create a display-ready diagnostic grade for every assessable element without changing the six-dimension 100-point rubric. Use item grades for colored index displays, filtering, sorting, and evidence popovers. Never add or average item grades to recreate the overall score.

Use grading policy `subject-index-item-grading-v1`. Treat it as a presentation and diagnosis layer over frozen evidence. A locator grade answers whether one path/page assignment is supported. A complete-path grade summarizes the measured quality of one full entry. A heading-node grade evaluates the wording and structural role of one displayed main heading or subheading. These are deliberately different questions.

## Artifacts and identities

At `normalize-index`, create both:

- `candidate-index.json`, preserving every normalized record, `PATH-*`, and `LOC-*`; and
- `item-inventory.json`, deterministically adding `NODE-*` and `XREF-*` identities.

Generate a node from each unique heading-path prefix. All records beginning with the same main heading share one level-one node. A subheading node represents its exact two-level prefix. Generate identities from the candidate hash plus canonical identity data so repeated runs over identical normalized input produce the same IDs.

Resolve a cross-reference target to `target_path_id` when its normalized display text uniquely matches an inventory path. Leave it null when no unique match exists; the global reference audit must then record whether the target is unresolved, ambiguous, or otherwise defective.

At `score-index`, create `item-assessments.json` before `evaluation-result.json`. The item artifact contains locator, path, node, cross-reference, and source-subject assessments, plus a color legend and summary counts.

## What each grade means

| Item | Grade scope | Does not mean |
| --- | --- | --- |
| Locator | Whether one complete heading path is substantively supported on one cited page | Whether the subject is completely covered elsewhere |
| Complete path | The entry as delivered, using all measured path-specific evidence | A stand-alone contribution to the overall 100-point score |
| Heading node | The wording and structural role of one displayed main heading or subheading | An average of every descendant locator |
| Cross-reference | Whether one `see` or `see also` reference is valid and useful | Whether the entire referenced subject is well indexed |
| Source subject | Whether a candidate gives useful access to one independently discovered source subject | A candidate entry when no such entry exists |

Keep source-subject assessments available for a separate “missing important access” display. Do not invent a candidate heading to color when the candidate omitted it.

## Color bands

| Score | Band | Token |
| ---: | --- | --- |
| 90–100 | Excellent | `grade_excellent` |
| 80–89.99 | Strong | `grade_strong` |
| 70–79.99 | Mixed | `grade_mixed` |
| 60–69.99 | Weak | `grade_weak` |
| Below 60 | Poor | `grade_poor` |
| Not measured | Not measured | `grade_neutral` |

The JSON supplies semantic tokens, not fixed CSS colors. A website chooses accessible colors and must pair color with a label or icon. Never rely on color alone. Display `uninspectable` and `not_measured` neutrally; they are not failures.

## Locator grades

Map frozen locator judgments deterministically:

| Judgment | Score |
| --- | ---: |
| `supported` | 100 |
| `partially_supported` | 70 |
| `unsupported` | 0 |
| `uninspectable` | null |

Show mapping status, treatment class, confidence, severity, evidence summary, and evidence IDs in the popover. Confidence describes confidence in the judgment and does not alter the grade. A locator conclusively marked `unresolved` receives 0 because it does not identify a source page. An `ambiguous` locator remains neutral and uninspectable because the available mapping does not establish whether the candidate or source representation is at fault. Both remain subject to mapping, mechanics, and shipping-gate rules.

## Complete-path grades

Use the following rubric-aligned component weights:

| Component | Weight |
| --- | ---: |
| Meaningful coverage | 20 |
| Editorial selectivity, excluding chapter density | 10 |
| Conceptual and stance fidelity | 15 |
| Page-reference reliability | 25 |
| Findability and navigation | 20 |
| Mechanics and consistency | 5 |

The weights total 95 because the five chapter-density points are global and must never be assigned to an individual path.

Derive components as follows:

- Calculate page-reference reliability from the mean of measured locator grades attached to the path.
- Calculate editorial selectivity from the locator treatment classes: substantive 100, mixed 70, passing/citation/attribution/incidental/absent 0, and unavailable null.
- Calculate meaningful coverage from source-subject judgments that explicitly name the path in `matched_path_ids`, weighted essential 3, major 2, optional 1.
- Calculate conceptual fidelity, findability, and mechanics from the audited heading nodes in the path plus path-specific defects.
- Apply defect severity caps only to the component owned by the defect code: cosmetic 95, minor 85, major 55, critical 0.
- Store every applied cap with defect ID, severity, and maximum permitted component score so the interface can explain its effect.
- Exclude not-applicable or unmeasured components from the denominator rather than converting them to zero.

Normalize the weighted mean of measured components to 100. Retain every component score, weight, measurement state, and evidence ID. The deterministic tool performs this arithmetic; do not calculate it conversationally.

## Heading-node grades

Audit every `NODE-*` during the global structure pass. Record three component judgments:

- conceptual and stance fidelity;
- heading/access architecture; and
- mechanics and consistency.

Use statuses `passes`, `minor_issues`, `major_issues`, `fails`, `uninspectable`, and `not_applicable`. Map them to 100, 85, 55, 0, null, and null respectively. Apply path-specific defect caps. Normalize the measured components using their rubric weights of 15, 20, and 5.

A level-one main-heading grade evaluates that heading’s wording and organizational role. It does not conceal a weak child by averaging all descendants. Each child subheading and each complete path retains its own grade.

## Cross-reference grades

Audit every `XREF-*` separately. Map `supported`, `partially_supported`, `unsupported`, and `uninspectable` to 100, 70, 0, and null. Include reference type, source path, target display, target path when resolved, confidence, defects, and evidence IDs.

## Source-subject access grades

Map benchmark coverage `complete`, `partial`, `missing`, and `uninspectable` to 100, 70, 0, and null. Keep priority, matched paths, missed pages, severity, and confidence. Use these assessments both as complete-path coverage inputs when a path is explicitly matched and as a separate omissions panel.

## Popover contract

Every assessed item must include:

```json
{
  "popover": {
    "title": "Revolution — economic causes",
    "summary": "Short public-safe explanation.",
    "grade": {
      "score": 85,
      "rating": 4.25,
      "band": "strong",
      "color_token": "grade_strong",
      "status": "passes_with_issues"
    },
    "grade_scope": "complete_heading_path_as_delivered",
    "confidence": "high",
    "factors": [
      {
        "factor_id": "page_reference_reliability",
        "label": "Page Reference Reliability",
        "status": "measured",
        "score": 85,
        "weight": 25,
        "applied_cap": 85,
        "severity_caps": [
          {"defect_id": "DEFECT-0002", "severity": "minor", "maximum_score": 85, "summary": "One child is filed beneath an unintuitive umbrella."}
        ],
        "explanation": "Why this factor received its value.",
        "evidence_ids": ["LOC-0001", "DEFECT-0002"]
      }
    ],
    "navigation": {
      "path_id": "PATH-0042",
      "node_ids": ["NODE-0010", "NODE-0011"],
      "locator_ids": ["LOC-0001"]
    },
    "evidence_ids": ["LOC-0001", "DEFECT-0002"]
  }
}
```

Keep the popover concise and public-safe. Make it self-contained for the displayed grade, grade scope, confidence, factor scores, weights, caps, cap explanations, and navigation IDs. Use paraphrases and evidence IDs rather than source quotations. Store any necessary exact quotation or extended explanation in a restricted evidence ledger, not in `item-assessments.json`. A permitted authenticated interface may resolve evidence IDs to that deeper ledger. Show the grade scope so customers know whether they are viewing a locator, path, node, reference, or source-subject grade.

## Full and pilot audits

In full mode, require one locator judgment for every resolved locator, one node judgment for every inventory node, and one cross-reference judgment for every inventory reference. Fail item-assessment generation when those completion conditions are not met.

In pilot mode, emit all inventory items but grade only measured items. Use neutral `not_measured` output for unsampled items. Never use a colored pilot display to imply that the entire index was audited.

## Validation

Validate that:

- candidate, inventory, audits, and structure audit use the same candidate hash;
- IDs are unique and every full-audit expected ID is judged once;
- no null grade uses a failure color;
- every assessment contains a popover and evidence index;
- path components disclose weights and measurement states;
- chapter density is absent from path and node grades;
- summary band counts equal collection counts; and
- the web report references the exact item-assessment artifact hash.
