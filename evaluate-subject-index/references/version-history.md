# Methodology version history

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

Identity `subject-index-rubric-v4`. V4 accepted five dimension ratings and the substantive-selectivity rating as evaluator inputs, then applied deterministic scorecard arithmetic. Its original schemas, density behavior, result reader, and score-only migration reader remain available for historical artifacts. V4 results are never silently upgraded or interpreted under V5 or V6.

## Comparability rule

Compare candidate results only when the frozen source, benchmark, judgment policy, page map, chunk manifest, inclusion policy, audit mode, uncertainty policy, rubric, and dimension-calculation profile match. A migration creates a new versioned projection and preserves prior artifacts; it never overwrites history.
