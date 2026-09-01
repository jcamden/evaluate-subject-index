# Web-report fields — V7.1 explanation projection

New V7 projections use `subject-index-web-report-v7`. Historical `subject-index-web-report-v6` files remain immutable and validate through the compatibility reader.

## Locator explanations

`locator_explanations` contains one entry for every measured locator and preserves the corresponding V5 item `locator_explanation` without paraphrase. Each entry exposes:

- the original locator-specific, public-safe `evidence_summary`;
- page-treatment category, score, rule ID, and the evidence summary as its primary rationale;
- complete-path-fit category, score, rule ID, and any required authored, supplemental, or ledger-backed rationale;
- evidence IDs and relevant structured defects; and
- `combined_locator_utility`, including the explicit `min(T,F)` expression and result.

The web builder may generate a concise fit explanation from the structured category and rule only for routine supported, substantive, indexable, defect-free 100/100 cases. It must preserve authored wording for divergent, nonperfect, conflicting, or supplemental cases. Generic statements about deriving a result from frozen provenance are methodology metadata, not locator explanations, and must never replace the evidence summary or required fit rationale.

## Calculation boundary

Explanation fields are projection-only. Page treatment, complete-path fit, combined credit, locator grade, dimension values, caps, gates, and total are copied from validated structured calculation and item artifacts. Neither the item builder nor the web builder interprets explanation prose to choose or modify a structured value.

## Compatibility

The artifact compatibility reader dispatches by `schema_version` and validates both V6 and V7 web reports against their original schemas. No historical report is rewritten or upgraded in place.
