# V7 web-report fields — schema V6

`subject-index-web-report-v6` is the V7 display contract. It binds `subject-index-dimension-calculations-v3`, `subject-index-item-assessments-v4`, `subject-index-v7-projection-metadata-v1`, `subject-index-structure-locator-review-v1`, and, for migration, `subject-index-score-migration-v6-to-v7-v1`.

## Reliability display

Expose these fields distinctly:

- `weighted_locator_precision`: arithmetic precision from the frozen `combined_credit` ledger;
- `strict_substantive_precision`: supported divided by all assessable locator judgments;
- expected-treatment recall and weighted F1;
- complete treatment-tier, fit-tier, and combined-credit counts;
- both axis numerators/denominators and weighted/strict precision numerators/denominators;
- locator utility rows with rule IDs, exclusion/bound reasons, and grades;
- cap evaluations, applied cap, uncertainty endpoints, rounding, final rating, and points; and
- `diagnostic_grades_used_in_dimension_arithmetic: false`.

Do not label weighted two-axis precision as strict precision. Explain that treatment and complete-path fit are separate facts, the lower score controls, and the minimum avoids double-counting a shared limitation. Keep Editorial Selectivity, caps, and gates visibly separate.

## Locator and path popovers

Each locator popover shows treatment and fit factors independently plus `100 × min(T,F)`. Each locator-bearing path exposes:

- delivered display IDs and count;
- singleton/range/other kind;
- each range ID, endpoints, inclusive span, and atomic ownership;
- maximum range span;
- expanded atomic IDs and count;
- both review triggers;
- structured semantic evidence and defect IDs; and
- final architecture disposition and derivation/mapping rules.

Required explanatory language separates a long locator list from a long continuous range. It must never describe expanded pages as “undivided locators” and must state that a numerical trigger alone is not a defect.

## Score views and migration

`score_views.primary_view_id` remains `canonical_as_delivered`. Every counterfactual view includes a distinct V7 calculation, structure-review reference, and complete representation-provenance references; its score is derived from its calculation rather than copied.

`migration_comparison` exposes old/new totals, all dimension comparisons, unchanged gates, methodology commit, and complete structure-count dispositions. For each removed or retained historical architecture defect, the disposition includes its hash-bound frozen structured basis, corrected displayed/range/atomic metrics, mapping rule, and active status. The report states that historical artifacts were not modified, source evidence was not reopened, no new semantic judgment came from a threshold, no Oxford artifact was changed, and the formula was not tuned to an Oxford score.

## Presentation hierarchy

Use progressive disclosure:

1. overall score and publication-readiness status;
2. six quality questions;
3. precision/recall, locator utility, structure metrics, representative strengths/defects, and gates; and
4. full formulas, mapping tables, provenance, migration invariants, uncertainty, and limitations.
