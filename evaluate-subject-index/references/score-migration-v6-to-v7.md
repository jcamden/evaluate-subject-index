# V6-to-V7 score-only migration

## Purpose

`subject-index-score-migration-v6-to-v7-v1` recalculates V7 from exact V6 frozen evidence. It never edits V6 artifacts and never reopens or reinterprets the evaluation.

## Required inputs

Use a `subject-index-v6-to-v7-migration-input-v1` manifest with SHA-256 references to:

- the V6 dimension-calculation input;
- exact normalized candidate and item inventory;
- V6 calculation, result, item assessments, web report, and projection metadata; and
- one complete input/config/candidate/inventory/V6-calculation set for every representation-adjusted counterfactual view.

When a prior run stops on newly exposed structure triggers, the canonical view
and every affected counterfactual may additionally reference one
`subject-index-v7-architecture-review-supplement-v1` artifact. The supplement
binds the exact V6 dimension-calculation input, candidate, inventory,
historical structure audit, evaluation, and audit mode. It is not part of V6
recalculation and cannot replace any V6
input.

The manifest records the methodology repository, exact V6 base commit, V7 implementation commit, evaluation repository/base commit, benchmark repository/current head, frozen benchmark commit, and frozen benchmark SHA-256. The migration verifies the old projection chain, recalculates V6 from its inputs, requires the candidate and inventory file hashes bound by the V6 evidence identity, and refuses a frozen benchmark SHA-256 that differs from the exact V6 calculation. A later benchmark head never silently rebinds the evaluation.

## Algorithm

1. Validate every input schema, file hash, self-hash, artifact reference, calculation projection, and V6 gate array.
2. Recalculate V6 from the canonical frozen ledgers and require dimension/value identity.
3. Derive displayed-locator grouping, range ownership/spans, and atomic assignments from the exact normalized candidate and inventory.
4. Reject missing grouping, prose-dependent mapping, incomplete locator utility, or unreviewed newly triggered architecture cases. If a supplemental review is supplied, first derive the unresolved trigger set without it and require the supplement to contain every and only those paths.
5. Build the active structure correction in memory. Never rewrite `structure-audit-v3`, V4, or any other historical file.
6. Recalculate V7 Page-reference Reliability. Recalculate Findability and Navigation only when a deterministic false-positive architecture correction changes its active node/defect projection. Require all other dimensions to remain value-identical.
7. Rebuild V7 item assessments, projection metadata, result, and web report.
8. Recalculate each counterfactual score view from that view’s own calculation input and structure review; carry its exact representation provenance artifacts forward.
9. Preserve the V6 gate array byte-for-value and hash-for-hash.
10. Emit a migration record and a validation receipt binding active and historical projections.

## False-positive removal

Removal is allowed only when all conditions hold:

- the historical structured root-cause family is exactly an approved `atomic_assignment_threshold_only` family;
- the mechanically derived atomic count exceeded six;
- corrected `displayed_locator_count > 6` is false;
- corrected `maximum_range_span > 10` is false;
- no independent structured architecture defect or explicit semantic decision remains; and
- the affected adverse node status can be deterministically restored after removing the sole defect.

The active V7 projection records every removed or retained historical architecture defect in `historical_defect_dispositions`. Each row includes the complete frozen structured defect object and its SHA-256 digest, its closed basis classification, all corrected displayed/range/atomic metrics, the deterministic mapping rule, the path disposition, and whether the defect was removed from or retained in the active V7 projection. Only `root_cause_family` is a classification input; rationale and other prose are retained as history but never interpreted. The V6 structure audit, item artifact, result, and report remain untouched.

## Newly exposed review cases

If corrected counting triggers a path that has no frozen structured determination about conceptual heterogeneity and access impairment, the disposition is `review_required`. A trigger alone cannot create a defect. Full migration stops with `supplemental_architecture_review_required`; pilot output may remain explicitly unscored/suppressed under the normal evidence-completeness rules.

A supplemental review is limited to architecture. It cannot revisit source pages, locator-support judgments, missing-access audits, or unrelated structure judgments.

Freeze the follow-up as
`subject-index-v7-architecture-review-supplement-v1`. Its decision rows use the
same four booleans and status contract as `structure-audit-v5`. Evidence IDs are
restricted to the affected frozen candidate path, record, inventory nodes,
display records, ranges, and atomic assignments. The migration validates its
self-hash, bindings, exact unresolved-trigger scope, unique review identities,
and non-overlap with decisions already present in the historical structure
audit. It then projects the decisions in memory for review derivation. The V6
configuration, V6 calculation, and historical structure bytes remain
unchanged.

The supplement is semantic input authorized after the fail-closed stop; the
migration still does not invent a decision. The migration record and receipt
state whether such judgments were added, identify their narrow scope, and bind
each canonical or counterfactual supplement separately.

## Counterfactual score views

Migration refuses to copy a representation-adjusted score. Every historical counterfactual view must have a matching manifest record. V7 recalculates it from its own frozen calculation input, normalized candidate, inventory, and structure review, then binds every historical representation-correction provenance artifact by hash. Missing or extra views fail validation.

The migration record preserves the complete historical V6 score-view object and records the regenerated V7 canonical and counterfactual score-view object. Each V7 counterfactual points to its own recalculated dimension artifact, structure review, and representation-provenance artifacts; no score is copied from the canonical view.

## Outputs

The command writes, without overwriting:

- `structure-locator-review.v7.json`;
- `dimension-calculations.v7.json`;
- `item-assessments.v7.json`;
- `projection-metadata.v7.json`;
- `score-migration.v6-to-v7.json`;
- `evaluation-result.v7.json` (schema V8);
- `web-report.v7.json` (schema V6);
- counterfactual calculations/reviews under `score-views/`; and
- `validation-receipt.v7.json`.

Run:

```bash
python evaluate-subject-index/scripts/dimension_score_v7_cli.py migrate-v6-to-v7 \
  --manifest path/to/v7-migration-input.json \
  --output-directory path/to/new-v7-projection
```

The command never migrates an Oxford evaluation repository implicitly. The Oxford-shaped locator example is a generic regression fixture only; it is not a target score and the locator utility values are not tuned to reproduce an Oxford outcome.
