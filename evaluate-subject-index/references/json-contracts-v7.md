# V7 JSON artifact contracts

V7 adds new schema identities and leaves every V4, V5, and V6 schema and reader in place.

| V7 artifact | Schema identity | Contract |
| --- | --- | --- |
| Native structure audit | `structure-audit-v5` | Explicit structured architecture-review decisions |
| Supplemental migration architecture review | `subject-index-v7-architecture-review-supplement-v1` | Exact unresolved-trigger decisions bound to frozen V6 candidate, inventory, and structure bytes |
| Native locator audit | `locator-audit-v2` | Locator-specific public-safe evidence plus conditionally required complete-path-fit rationale; V1 remains readable |
| Supplemental migration locator fit | `subject-index-v7-locator-fit-supplement-v2` | Every-and-only unresolved fit decisions, each with a public-safe rationale or hash-bound validated rationale-ledger reference; V1 remains readable |
| Locator-fit preflight | `subject-index-v7-locator-fit-preflight-v1` | Score-free, mutually exclusive deterministic/unresolved/invalid groups, unresolved reasons and exact-set hash, with structured conflict provenance when eligible |
| Locator evidence projection | `locator-evidence-state-v3.schema.json` | Valid two-axis combined locator state |
| Structure locator review | `subject-index-structure-locator-review-v1` | Display/range/atomic derivation, triggers, semantic evidence, and dispositions |
| Dimension calculation | `subject-index-dimension-calculations-v4` | V3 calculation profile and unchanged arithmetic, with V5 explanation-projection binding |
| Item assessments | `subject-index-item-assessments-v5` | Preserved locator evidence, independent axis explanations, and grade equal to 100 times locator utility |
| Projection metadata | `subject-index-v7-projection-metadata-v2` | Canonical and counterfactual V4/V5/V7 projection bindings |
| Evaluation result | `subject-index-evaluation-result-v9` | V7 scorecard with V4 calculation and V5 item bindings |
| Web report | `subject-index-web-report-v7` | Locator-specific two-axis explanations plus unchanged score views and structure reporting |
| Migration input | `subject-index-v6-to-v7-migration-input-v1` | Exact V6 history plus per-view frozen recalculation inputs |
| Migration record | `subject-index-score-migration-v6-to-v7-v2` | Old/new dimensions, totals, gates, score views, invariants, and V4/V5/V7 projection bindings |
| Validation receipt | `subject-index-score-migration-v6-to-v7-validation-v2` | Hash-bound active, historical, and counterfactual projection receipt |

## Locator utility invariants

Every assessable row binds locator ID, frozen judgment/treatment/scope, inspectability, codes, structured defects, severity, treatment and fit categories/scores, rule IDs, classification source, any legacy compatibility/conflict rule or supplemental decision/evidence IDs, `combined_credit`, and `diagnostic_grade`. Runtime validation rejects prose-dependent, contradictory, or incomplete mappings outside the narrow conflict route. The grade must equal `100 × combined_credit`; the dimension declares that grades are not arithmetic inputs.

`v7-locator-fit-preflight.schema.json` validates the public preflight artifact. The three arrays are disjoint, group counts are explicit, reason counts are keyed by stable reason codes, `aggregate_v7_score_available` is always false, and the unresolved-set hash preserves the established canonical seed. The conflict branch requires `F-COMPAT-LEGACY-FIT-CONFLICT-TO-SUPPLEMENT-V1`, reason `legacy_structured_fit_classification_conflict_requires_adjudication`, at least two structured classifiers and implied categories, stable locator/path/provenance identities, and false declarations for precedence, prose use, and historical modification. Its treatment enum includes `absent` because an otherwise valid unsupported/indexable conflict can legally retain that frozen class; the schema restricts that `absent` unresolved form to the conflict reason. It excludes `unavailable` because valid unavailable treatment requires an uninspectable judgment and is deterministically bounded before unresolved routing. Ordinary bare-`LOC_POS` records cannot carry conflict provenance. Invalid states are never supplement-eligible or hashed into the unresolved set.

The immutable V2 locator-fit supplement schema permits only the five frozen category names as scoring inputs. Each decision additionally carries either a concise `public_safe_rationale` or a `rationale_reference` bound to a separately validated, self-hashed rationale ledger and record. Rationale bytes are explanatory metadata: they cannot supply numerical fit/treatment/combined credit, grade, dimension score, total, or declare a historical classifier correct. Runtime validation reconstructs decision IDs, hashes, ordering, exact unresolved scope, path identity, evidence scope, and any rationale-ledger bindings before in-memory application. The V1 compatibility reader remains available for historical supplements and never rewrites them.

`locator-audit-v2.schema.json` requires a nonempty public-safe `evidence_summary` for every measured locator and conditionally requires `fit_rationale` when axes diverge, fit is nonperfect, classifiers conflict, or supplementation supplies fit. `item-assessments-v5.schema.json` and `web-report-v7.schema.json` preserve that exact evidence and expose both structured axes, any applicable fit rationale, relevant evidence/defects, and `min(T,F)`. These explanation fields are outside every calculation schema and calculation function.

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

Applied locator-fit supplement identities propagate through the calculation, item assessments, migration record, result, web report, projection metadata, and receipt. The migration records unresolved counts before/after, reason counts and full public-safe unresolved records, conflict-routed locator IDs, compatibility classifications made without supplementation, exact scope hash, per-view supplement reference, unchanged-history/non-fit confirmations, and the absence of manually supplied numerical credit or score. These additions remain optional in shared V7 projection schemas so valid earlier V7 artifacts retain schema compatibility; `v7.0.3` records require the original supplement provenance block, while `dimension-score-cli-v7.0.4` and `dimension-score-cli-v7.0.5` records additionally require conflict-routing provenance and fail-closed invariants. V7.0.5 changes only the reachable unresolved-treatment schema alignment and tool identity; the projection schema identities remain unchanged. Tool patch `dimension-score-cli-v7.0.6` adds no artifact field or schema identity. It freezes defect-derived item arrays under `ITEM-PROJECTION-DEFECT-ID-ASC-V1`; the existing migration-schema version gate recognizes V7.0.6 while artifact shapes and score arithmetic remain unchanged.

When a supplemental architecture review is present, its self-hash and file hash
are separately bound for the canonical or counterfactual view. Semantic
validation first reconstructs the base review without the supplement, requires
the declared and actual decision paths to equal that exact unresolved set, and
rejects historical-decision overrides or evidence IDs outside the affected
structured candidate path.

JSON numbers are compared through canonical decimal-safe serialization, so parsing a stored decimal as `Decimal` and reconstructing it as a finite float does not create false drift, while a numeric-value change still fails validation.
