# V7 JSON artifact contracts

V7 adds new schema identities and leaves every V4, V5, and V6 schema and reader in place.

| V7 artifact | Schema identity | Contract |
| --- | --- | --- |
| Native structure audit | `structure-audit-v5` | Explicit structured architecture-review decisions |
| Locator evidence projection | `locator-evidence-state-v3.schema.json` | Valid two-axis combined locator state |
| Structure locator review | `subject-index-structure-locator-review-v1` | Display/range/atomic derivation, triggers, semantic evidence, and dispositions |
| Dimension calculation | `subject-index-dimension-calculations-v3` | V7 utility ledger, corrected active structure projection, and all calculation provenance |
| Item assessments | `subject-index-item-assessments-v4` | Grade equals 100 times locator utility; path structure fields remain non-scoring |
| Projection metadata | `subject-index-v7-projection-metadata-v1` | Canonical and counterfactual calculation/review/provenance bindings |
| Evaluation result | `subject-index-evaluation-result-v8` | V7 scorecard, diagnostics, gates, migration, and structure-review references |
| Web report | `subject-index-web-report-v6` | V7 method, score views, locator utility, structure counting, and migration comparison |
| Migration input | `subject-index-v6-to-v7-migration-input-v1` | Exact V6 history plus per-view frozen recalculation inputs |
| Migration record | `subject-index-score-migration-v6-to-v7-v1` | Old/new dimensions, totals, gates, score views, invariants, and path dispositions |
| Validation receipt | `subject-index-score-migration-v6-to-v7-validation-v1` | Hash-bound active, historical, and counterfactual projection receipt |

## Locator utility invariants

Every assessable row binds locator ID, frozen judgment/treatment/scope, inspectability, codes, structured defects, severity, treatment and fit categories/scores, rule IDs, `combined_credit`, and `diagnostic_grade`. Runtime validation rejects prose-dependent, contradictory, or incomplete mappings. The grade must equal `100 × combined_credit`; the dimension declares that grades are not arithmetic inputs.

## Structure-count invariants

The schema distinguishes `delivered_displayed_locator_ids`, `displayed_locator_count`, per-display atomic ownership, range endpoints/span, `maximum_range_span`, path atomic IDs, and `atomic_assignment_count`. Cross-field validation additionally requires:

- displayed count equals the number of ordered `DISPLAY-*` rows;
- one range row retains one range identity and every owned atomic assignment;
- per-display and path atomic counts equal their exact ID-list lengths;
- the path atomic list equals the ordered concatenation of display ownership lists;
- inclusive range span reconstructs from bound endpoint document pages;
- triggers reconstruct exactly from `> 6` and `> 10`;
- summary counts reconstruct from path rows; and
- migration readiness is false for any derivation failure or unreviewed trigger.

The `structured_defect_confirmed` schema branch requires a trigger, four true semantic criteria, a retained structured defect, and a bound defect ID. `reviewed_no_defect` requires no defect IDs and at least one false criterion. A recalculated self-hash cannot bypass these semantic checks.

Every applicable historical architecture defect also has one `historical_defect_dispositions` row. The row hash-binds the complete frozen structured basis to its corrected metrics, mapping rule, path disposition, and removed-or-retained active status. Semantic validation reconstructs the basis digest and requires the removed and retained sets to partition the applicable defect IDs exactly.

## History and projections

Historical artifact references retain their original schema identities and file hashes. Migration never rewrites them. The V7 receipt binds the migration, calculation, result, item assessments, web report, projection metadata, and structure review plus all historical counterparts. Each counterfactual view binds its own V6 input/config/candidate/inventory, recalculated V7 calculation and review, and original representation-provenance files.

JSON numbers are compared through canonical decimal-safe serialization, so parsing a stored decimal as `Decimal` and reconstructing it as a finite float does not create false drift, while a numeric-value change still fails validation.
