# V6-to-V7 score-only migration

## Purpose

New V7.1 projections use `subject-index-score-migration-v6-to-v7-v2` to recalculate V7 from exact V6 frozen evidence. The V1 reader remains available for existing immutable migrations. Migration never edits V6 artifacts and never reopens or reinterprets the evaluation.

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

When unsupplemented locator-fit preflight reports unresolved complete-path-fit states, an affected view may additionally reference one `subject-index-v7-locator-fit-supplement-v2`. This semantic input is created only after the stop. It binds the exact V6 calculation-input file, normalized candidate, inventory, historical V6 calculation file and self-hash, complete locator and missing-access artifact sets, historical structure audit, chunk manifest, any historical migration supplement, evaluation/candidate/audit identity, and counterfactual representation provenance. Every binding uses the exact file SHA-256; the supplement also has a stable identity and self-hash. Each new decision includes either `public_safe_rationale` or a record reference into a separately validated, hash-bound public-safe rationale ledger. V1 supplements remain valid historical inputs through the compatibility reader.

The manifest records the methodology repository, exact V6 base commit, V7 implementation commit, evaluation repository/base commit, benchmark repository/current head, frozen benchmark commit, and frozen benchmark SHA-256. The migration verifies the old projection chain, recalculates V6 from its inputs, requires the candidate and inventory file hashes bound by the V6 evidence identity, and refuses a frozen benchmark SHA-256 that differs from the exact V6 calculation. A later benchmark head never silently rebinds the evaluation.

## Algorithm

1. Validate every input schema, file hash, self-hash, artifact reference, calculation projection, and V6 gate array.
2. Recalculate V6 from the canonical frozen ledgers and require dimension/value identity.
3. Run unsupplemented V7 locator compatibility on the complete validated ledgers. Place every locator exactly once in `deterministically_compatible`, `unresolved_complete_path_fit`, or `invalid_or_contradictory_state`; record per-reason counts and structured classifier provenance; derive the sorted unresolved set and hash; expose no aggregate V7 score; and stop on any invalid state.
4. Only after steps 1–3, read an optional locator-fit supplement. Require its declared scope and decisions to contain every and only the independently derived unresolved locator set, and validate all hashes, identities, ordering, path/locator bindings, evidence scope, and non-fit invariants. Without a complete supplement, no score is produced.
5. Derive displayed-locator grouping, range ownership/spans, and atomic assignments from the exact normalized candidate and inventory.
6. Reject missing grouping, prose-dependent mapping, or unreviewed newly triggered architecture cases. If a supplemental architecture review is supplied, first derive the unresolved trigger set without it and require the supplement to contain every and only those paths.
7. Build all supplemental decisions and active structure corrections in memory. Never rewrite `structure-audit-v3`, V4, a locator audit, calculation input, or any other historical file.
8. Map any supplemental fit category through the frozen V7 category values, derive `L=min(T,F)`, and recalculate V7 Page-reference Reliability. Recalculate Findability and Navigation only when a deterministic false-positive architecture correction changes its active node/defect projection. Require all other dimensions to remain value-identical.
9. Rebuild V7 item assessments, projection metadata, result, and web report.
10. Recalculate each counterfactual score view from that view’s own calculation input, structure evidence, locator-fit supplement, and representation provenance.
11. Preserve the V6 gate array byte-for-value and hash-for-hash.
12. Emit a migration record and a validation receipt binding active and historical projections.

## Deterministic item projection

Tool patch `dimension-score-cli-v7.0.6` applies `ITEM-PROJECTION-DEFECT-ID-ASC-V1` when a complete path, heading node, or cross-reference discovers more than one applicable structured defect. The projector preserves the existing path, node, locator, reference, display, and source-evidence order used for semantic navigation; it uses those identities only for membership lookup, deduplicates defects by stable `defect_id`, and emits defect-derived cap and evidence arrays in ascending `defect_id` order. Equivalent clean migrations must therefore produce byte-identical item, result, report, migration, and receipt artifacts across Python hash seeds.

This rule changes serialization only. It changes no schema identity or artifact shape, locator judgment, treatment or fit category, credit, minimum rule, grade, dimension formula, cap value, threshold, gate, architecture disposition, or historical byte. Historical artifacts remain immutable.

## Historical locator-fit compatibility

Historical top-level `structure-audit-v3` defects may predate `defect_kind`. Rule `F-COMPAT-LEGACY-CODE-SEVERITY-ONLY-V1` tolerates that omission only when every other required structured field is valid and the approved V7 code/severity table lets each record select one category without prose. Locator-bound `SCP`, `CON`, `STA`, `CMP`, `HED`, or `SUB` evidence maps minor to material mismatch, major to severe mismatch, and critical to no fit. Convergent records produce the same deterministic category as before; eligible inter-record disagreement follows the separate fit-only conflict rule. The historical defect is neither rewritten nor assigned an invented kind.

Cosmetic evidence cannot support an adverse semantic classification. `MEC` and `SEL` remain fit-neutral; `LOC_POS` is a consequence, not a fit cause. Unknown codes, missing severity, ambiguous scope, and every state outside the narrow conflict rule below remain invalid or ordinarily unresolved under the existing rules. Current-contract defects do not become legacy-compatible by deleting `defect_kind`.

### Fit-only conflict routing

Rule `F-COMPAT-LEGACY-FIT-CONFLICT-TO-SUPPLEMENT-V1` converts no historical record and weakens no validator. It applies only when:

1. every participating record is individually schema-valid;
2. all records share the exact evaluation, candidate, audit mode, locator ID, and uniquely bound normalized complete-path ID;
3. every participating code and severity is recognized by the existing V7 mappings;
4. at least two otherwise valid classifiers, including a legacy compatibility classifier, independently imply different existing fit categories;
5. the disagreement concerns only the derived complete-path-fit category;
6. no prose inference is required or permitted; and
7. exposing the disagreement requires no change to judgment, treatment, source scope, code, severity, defect, evidence, or any historical artifact.

The result is `unresolved_complete_path_fit`, reason `legacy_structured_fit_classification_conflict_requires_adjudication`. The public unresolved record includes locator/path identity; each classifier's source-artifact role, stable record identity, structured basis, code/severity, and independently implied category/rule; the conflict rule; and explicit no-precedence, no-prose, supplement-eligible, and history-unchanged declarations. The classifier list and implied-category list are stably sorted. No favorable, adverse, newest, highest-severity, or lowest-severity precedence is used; classifications are not averaged; and no category is selected automatically.

Tool patch `dimension-score-cli-v7.0.5` aligns that public record with the implementation when the exact frozen state is `unsupported` + `absent` + `indexable`: `absent` is preserved verbatim, the record stays in the unresolved group, and the semantic supplement must still provide an independent existing fit category. After supplementation, the unchanged treatment score of zero and separately mapped fit score are combined mechanically with `L=min(T,F)`. By contrast, valid `unavailable` treatment requires `uninspectable` judgment under both the evidence schema and runtime state contract, so it is classified deterministically as bounded and cannot enter the unresolved set. The patch changes no mapping or arithmetic.

This is not a general contradiction waiver. Mismatched evaluation/candidate/audit/locator/path identities, one locator assigned to incompatible normalized paths, missing structured identities, malformed records, unknown codes or severities, impossible treatment or scope state, contradictory hashes or self-hashes, artifact alias/containment/link failures, non-fit override attempts, prose-only classification, and conflicts extending beyond fit remain invalid. They stop preflight and migration with structured errors and are excluded from the unresolved set and its hash.

## Supplemental locator fit

The V2 supplement declares sorted unresolved `LOC-*` IDs and exactly one sorted decision per locator, including the matching `PATH-*`, one existing fit category, scoped evidence IDs, authorization provenance, a public-safe rationale or validated rationale-ledger reference, and confirmations that history and non-fit judgments are unchanged. It cannot contain `T`, `F`, `L`, a grade, a dimension score, a total, or fields that modify judgment, treatment, scope, codes, severity, evidence, defects, or gates. Its job is transport of a separately authorized semantic decision and its explanatory metadata, not methodology inference. Scoring reads the structured category only.

## Explanation projection

New migrations emit calculation V4, item V5, result V9, web-report V7, projection-metadata V2, migration V2, and receipt V2 artifacts. Item and web projections preserve the exact locator-audit evidence summary, expose both axis category/score/rule triples, carry required authored or ledger-backed fit rationale, retain evidence IDs and applicable structured defects, and show `min(T,F)`. Projection code must never substitute generic provenance text for the locator-specific evidence. Historical V7 artifact versions continue to validate without migration or rewriting.

For a conflict-routed locator, the authorized decision comes from direct semantic adjudication of the complete path at the cited destination. The decision resolves only the prospective V7 fit axis. It neither states nor implies that one historical classifier was correct, and every historical record remains byte-identical. Ordinary bare-`LOC_POS` unresolved states retain their separate reason and remain unmapped without the same exact-scope authorization process.

Evidence IDs are restricted to the affected locator and path, their bound candidate/inventory records and nodes, applicable structured defects, owned displays/ranges, and source-evidence identifiers already present in bound ledgers. Missing, extra, duplicate, unsorted, deterministic-locator, out-of-scope-evidence, hash-drift, identity-drift, prose-dependent, and cross-view-reuse attempts fail closed. Decisions are applied only in memory.

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

Migration refuses to copy a representation-adjusted score or canonical fit decision. Every historical counterfactual view must have a matching manifest record. V7 recalculates it from its own frozen calculation input, normalized candidate, inventory, historical calculation, structure review, separately bound locator-fit supplement when needed, and every historical representation-correction provenance artifact. Missing or extra views fail validation. Reuse is permitted only through separately validated bindings proving every relevant artifact identity is identical.

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

All compatibility and supplement tests use synthetic, candidate-independent fixtures. No evaluation repository, candidate data, locator distribution, score, or expected result was used to select a mapping, threshold, or validation behavior; evaluation results remain regression observations rather than targets.
