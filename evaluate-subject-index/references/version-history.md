# Methodology version history

## V7 — two-axis locator utility and corrected structure-review units

Identities:

- rubric `subject-index-rubric-v7`;
- dimension profile `subject-index-dimension-calculation-v3`;
- calculations `subject-index-dimension-calculations-v3`;
- result `subject-index-evaluation-result-v8`;
- diagnostic policy `subject-index-item-grading-v3`;
- item assessments `subject-index-item-assessments-v4`;
- native structure audit `structure-audit-v5`;
- structure review `subject-index-structure-locator-review-v1`;
- web report `subject-index-web-report-v6`; and
- migration `subject-index-score-migration-v6-to-v7-v1` with validation receipt V1.

V7 separates page treatment from complete-path fit and combines their deterministic frozen-evidence scores with `min(T,F)`. Treatment values are 1.00, 0.70, 0.25, and 0; fit values are 1.00, 0.70, 0.35, 0.15, and 0. Locator grade is exactly `100 × combined_credit`, while the canonical reliability calculation continues to use the locator-credit ledger rather than grade averages. Expected-treatment recall, weighted F1, strict precision, caps, gates, weights, uncertainty, and rounding remain unchanged.

V7 also corrects locator-string architecture screening. A displayed range counts once for `displayed_locator_count`, retains its own inclusive span, and expands to separate atomic assignments for support auditing. More than six displayed locators and, separately, a range longer than ten pages trigger review only. Neither trigger creates a defect without complete structured evidence of conceptual heterogeneity, meaningful subdivision/access, material retrieval impairment, and nontrivial conceptual division.

The V6-to-V7 migration preserves all prior bytes, may remove a sole structured atomic-threshold false positive only from the active projection, and stops on missing grouping, prose-dependent locator mapping, or newly exposed unreviewed cases. Counterfactual views are recalculated from their own artifacts and provenance. The approved values and thresholds are frozen methodological choices, not Oxford-fitted parameters; the Oxford-shaped locator example is a regression case only.

Tooling patch `dimension-score-cli-v7.0.1` adds the missing resume path
after that fail-closed stop. An authorized narrow follow-up is frozen as a
separate `subject-index-v7-architecture-review-supplement-v1` artifact. The
migration recalculates V6 from its original bytes first, then requires each
canonical or counterfactual supplement to bind its exact V6 input, candidate,
inventory, and historical structure audit and to cover every and only the
mechanically unresolved trigger paths. It projects the decisions in memory,
records the semantic scope explicitly, and binds the supplement in the review,
calculation, migration, and receipt. It does not change V7 formulas,
thresholds, mappings, or historical V6 artifacts.

Tooling patch `dimension-score-cli-v7.0.2` additionally requires the migration
manifest and record to preserve the exact evaluation base, benchmark head,
frozen benchmark commit, and frozen benchmark SHA-256. The frozen benchmark
hash must equal the identity already bound into the V6 calculation, preventing
a later benchmark repository head from silently rebinding the evaluation.

Tooling patch `dimension-score-cli-v7.0.3` adds two fail-closed migration-only compatibility mechanisms without changing any V7 value or formula. First, historical `structure-audit-v3` locator-bound defects that predate `defect_kind` may use `F-COMPAT-LEGACY-CODE-SEVERITY-ONLY-V1` when validated code, severity, scope, binding, and all other structured fields select exactly one existing fit category. Minor remains 0.35, major 0.15, and critical zero. Cosmetic, neutral, unknown, incomplete, contradictory, or multiply classifiable states remain unresolved or invalid; bare `LOC_POS` remains consequence-only.

Second, `subject-index-v7-locator-fit-supplement-v1` transports separately authorized category decisions for every and only the unresolved fit set derived after exact V6 recalculation. It is self-hashed and binds all per-view inputs and representation provenance. It contains no numerical credit or score, applies only to complete-path fit in memory, and is recorded throughout affected V7 provenance. Canonical and counterfactual views validate independently. Existing valid V7 artifact shapes remain schema-valid; new v7.0.3 migration and receipt output adds explicit locator-fit provenance. Synthetic fixtures alone defined and validate these rules; no evaluation result, locator distribution, candidate data, or expected score was used as a target.

Tooling patch `dimension-score-cli-v7.0.4` adds `F-COMPAT-LEGACY-FIT-CONFLICT-TO-SUPPLEMENT-V1`. When at least two individually valid structured classifiers—including a valid legacy compatibility classifier—share the exact evaluation, candidate, audit mode, locator, and normalized complete path but imply different categories, and the disagreement is confined to derived complete-path fit, preflight records `legacy_structured_fit_classification_conflict_requires_adjudication` instead of declaring the evaluation invalid. No classifier wins by precedence or averaging, no historical record changes, and the exact-scope V7 locator-fit supplement may resolve the prospective fit axis. Bare `LOC_POS` remains separately unresolved and unmapped. Identity, schema, assignment, artifact-integrity, prose-only, and broader contradiction failures remain invalid and supplement-ineligible. The patch adds a strict score-free preflight contract, conflict provenance in calculation/migration/receipt artifacts, and generic synthetic regression coverage without changing values, formulas, thresholds, gates, historical identities, or the published `v7.0.3` behavior.

See [rubric-v7.md](rubric-v7.md), [locator-utility-v7.md](locator-utility-v7.md), [structure-audit-v7.md](structure-audit-v7.md), and [score-migration-v6-to-v7.md](score-migration-v6-to-v7.md).

## V6 — weighted locator relevance

Identities:

- rubric `subject-index-rubric-v6`;
- dimension profile `subject-index-dimension-calculation-v2`;
- calculations `subject-index-dimension-calculations-v2`;
- result `subject-index-evaluation-result-v7`;
- diagnostic policy `subject-index-item-grading-v2`;
- item assessments `subject-index-item-assessments-v3`;
- web report `subject-index-web-report-v5`; and
- migration `subject-index-score-migration-v5-to-v6-v1`.

V6 changes the precision input to Page-reference Reliability from strict-only precision to reliability credits `1`, `0.5`, `0.25`, and `0`. The quarter tier is limited to unsupported, inspectable, indexable passing mentions, attribution-only presence, citation-only presence, and incidental examples without an independent `SCP`, `CMP`, `CON`, or `STA` failure. Strict substantive precision remains public. Diagnostic locator grades become 100/70/25/0/neutral.

Tooling patch `dimension-score-cli-v6.0.1` adds deterministic construction and complete path/hash/self-hash validation for representation-adjusted V6 score views. It preserves the V6 artifact identities and arithmetic while preventing unmaterialized or unproven counterfactual views from validating.

Tooling patch `dimension-score-cli-v6.0.2` clarifies judgment-first locator reliability credit. A valid `partially_supported` judgment receives 0.50 with substantive, mixed, or weak-presence treatment, and diagnostic `SCP`, `CMP`, `CON`, or `STA` codes do not override `supported` or `partially_supported`. Treatment class and those codes continue to distinguish 0.25 from 0 for `unsupported` evidence and retain all existing selectivity, defect, cap, gate, and disclosure consequences. Fabricated, nonexistent, out-of-scope, unavailable, and contradictory scope states remain hard failures or zero by precedence. Historical `v6.0.0` and `v6.0.1` migration artifacts remain schema-valid.

Tooling patch `dimension-score-cli-v6.0.3` makes V5-to-V6 artifact binding work in separate sibling version directories. New migration records declare one ancestor-only artifact root and store every individual V5/V6 binding as a normalized descendant without `..`; validators reject filesystem-root selection, non-ancestor roots, parent traversal, and resolved or symlink escape. Equivalent isolated layouts produce byte-identical calculation-derived outputs. The migration identity remains V1 and score arithmetic is unchanged; its schema adds the current root field while historical `v6.0.0`, `v6.0.1`, and `v6.0.2` migration artifacts remain valid without it.

No other dimension formula, weight, cap, gate, density rule, benchmark rule, treatment-recall denominator, or judgment meaning changes. Selectivity still gives the four weak-presence classes zero. V6 adds deterministic V5-to-V6 score-only migration and new projection schemas. Credit values are frozen methodological choices, not candidate-fitted parameters.

## V5 — ledger-derived dimensions

Identities:

- rubric `subject-index-rubric-v5`;
- dimension profile `subject-index-dimension-calculation-v1`;
- calculations `subject-index-dimension-calculations-v1`;
- result `subject-index-evaluation-result-v6`;
- diagnostic policy `subject-index-item-grading-v1`;
- item assessments `subject-index-item-assessments-v2`; and
- web report `subject-index-web-report-v4`.

V5 derives all six ratings from validated raw ledgers, introduced complete arithmetic/cap/uncertainty provenance, kept strict locator precision as the reliability input, corrected the V5-only zero-density edge, and added projection-safe item and web bindings. V5 remains immutable and independently valid. See [rubric-v5.md](rubric-v5.md) and [score-migration-v4-to-v5.md](score-migration-v4-to-v5.md).

## V4 — historical headline-rating scorecard

Identity `subject-index-rubric-v4`. V4 accepted five dimension ratings and the substantive-selectivity rating as evaluator inputs, then applied deterministic scorecard arithmetic. Its original schemas, density behavior, result reader, and score-only migration reader remain available for historical artifacts. V4 results are never silently upgraded or interpreted under V5, V6, or V7.

## Comparability rule

Compare candidate results only when the frozen source, benchmark, judgment policy, page map, chunk manifest, inclusion policy, audit mode, uncertainty policy, rubric, and dimension-calculation profile match. A migration creates a new versioned projection and preserves prior artifacts; it never overwrites history.
