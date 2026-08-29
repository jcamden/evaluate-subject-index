# V6 web-report field guide

`subject-index-web-report-v5` is the public display projection for `subject-index-rubric-v6`. It is built from a validated `subject-index-dimension-calculations-v2`, `subject-index-item-assessments-v3`, and `subject-index-v6-projection-metadata-v1` artifact. It never supplies score inputs.

## Top-level fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Exact V6 web identity: `subject-index-web-report-v5` |
| `report_id` | Stable display/report identifier |
| `headline`, `summary`, `grade` | Customer-facing conclusion and total-score presentation |
| `scorecard` | Six exact dimension projections, including raw components, denominators, caps, bounds, rounding, and points |
| `calculation_explainer` | Calculation path/hash and explicit declarations that item grades and gates were not used in arithmetic |
| `precision_diagnostics` | Public weighted and strict precision measures, their exact operands, treatment recall, and weighted F1 |
| `key_metrics`, `density` | Other display metrics and unchanged density presentation |
| `gate_status` | Exact critical-gate array and canonical hash; `used_in_score_arithmetic` is always false |
| `strengths`, `defects`, `examples` | Public-safe evidence summaries supplied by projection metadata |
| `item_grade_index` | Exact V3 item artifact/hash, V2 grading policy, semantic legend, summary, and interaction rules |
| `migration_comparison` | `not_applicable` or an exact V5-to-V6 old/new comparison bound to the migration record |
| `score_views` | Canonical observed score and any separately proven representation-correction counterfactual |
| `methodology`, `comparability`, `disclosures`, `limitations` | Version, comparison, and interpretation context |
| `evidence_index` | Public-safe evidence-ID lookup metadata |

## Precision diagnostics

`precision_diagnostics` is copied from the structured Page-reference Reliability provenance and contains:

| Field | Reconstruction role |
| --- | --- |
| `weighted_locator_precision` | V6 scored precision: sum of `1`, `0.5`, `0.25`, and `0` credits divided by assessable assignments |
| `weighted_precision_numerator`, `weighted_precision_denominator` | Exact weighted ratio operands |
| `strict_substantive_precision` | Diagnostic rate counting only `supported` assignments |
| `strict_precision_numerator`, `strict_precision_denominator` | Exact strict ratio operands |
| `treatment_recall` | Unchanged unique expected-treatment recall |
| `treatment_recall_numerator`, `treatment_recall_denominator` | Exact recall operands |
| `weighted_f1` | Harmonic mean used in the V6 reliability base |
| `weighted_role`, `strict_role`, `weak_presence_is_substantive` | Machine-readable explanation that weighted precision is scored, strict precision remains diagnostic, and weak presence is not substantive |

The Page-reference Reliability `scorecard` record carries the full `reliability_provenance`: counts by judgment, treatment class, and reliability tier; per-locator credits and disqualifiers; weighted, strict, recall, F1, and uncertainty operands; pre-cap rating; every cap evaluation; applied cap; lower/upper outcomes; rounding; final rating; weight; and points. Projection validation compares the repeated data to the bound calculation byte-for-byte at the structured-value level.

## Display requirements

- Label the two rates **weighted locator precision** and **strict substantive precision**. Do not substitute one label for the other.
- Explain that weak presence is not substantive treatment and receives zero selectivity credit.
- For any diagnostic grade of 25, use the required four-part explanation from [item-grading.md](item-grading.md).
- Do not average diagnostic locator grades to display precision, a dimension rating, or total score.
- Keep gates visibly separate from score arithmetic. A score does not override a failed gate.
- Render null/neutral uncertainty as unavailable evidence, not a zero or failure color.
- Use evidence IDs and short paraphrases; never project restricted source text, candidate reconstruction data, credentials, absolute paths, or Library identifiers.
