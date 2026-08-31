# V7 structure-audit instructions

## Judgment unit

Judge each unique `NODE-*` and complete `PATH-*` in the context of the whole delivered index. Preserve all V6 hierarchy, direct-access, cross-reference, coherence, density, and mechanics rules. V7 corrects only the unit used to screen locator strings and adds a separate continuous-range review.

> A displayed locator is one delivered page reference or continuous range. A range is audited as multiple atomic page assignments but counts as one displayed locator for scanning and subdivision review.

## Deterministic quantities

Derive these fields from `candidate-index-v2` and `subject-index-item-inventory-v2`, never from `original_displayed_form` or explanation prose:

- ordered delivered `DISPLAY-*` IDs and `displayed_locator_count`;
- each display’s `point`, `range`, `malformed`, or `unknown` delivered kind and V7 singleton/range/other projection;
- for a range, its one `RANGE-*` ID, delivered endpoints, atomic endpoint IDs, inclusive document-page span, and exact owned `LOC-*` list;
- `maximum_range_span`;
- ordered expanded `LOC-*` IDs and `atomic_assignment_count`; and
- exact SHA-256 bindings to candidate, inventory, and structure artifacts.

One range must remain one displayed locator. The ordered concatenation of each display’s atomic ownership list must equal the path’s atomic ledger. Missing ownership, noncontiguous range pages, candidate/inventory ID drift, unresolved grouping, or an unsupported delivered form stops derivation; display text must not be reparsed to repair it.

## Review boundaries

Use exact integer comparisons:

- `displayed_locator_count > 6` for long displayed-locator-string review;
- `inclusive_range_span > 10` for long-continuous-range review.

Record the long-range trigger per range and the path-level maximum. Six and ten are non-triggering boundary values. Atomic assignments are prohibited as the locator-string denominator and remain unchanged inputs to locator auditing, reliability, expected-treatment recall, routing, and density.

## Review decision

A trigger alone records `review_required`. It supplies no score, defect, severity, cap, or automatic status. To record `defect_confirmed`, freeze structured booleans establishing all four criteria:

1. destinations contain conceptually distinguishable treatments;
2. useful subheadings or alternative access routes could represent them;
3. the current undifferentiated presentation materially impairs scanning or retrieval; and
4. the proposed division is conceptual and nontrivial, not merely page-based, grammatical, trivial, or chronological without conceptual value.

Bind at least one evidence ID and one applicable `DEFECT-*` ID. A `reviewed_no_defect` decision requires evidence, no defect IDs, and at least one criterion false. Explanation text may communicate the decision but cannot create it.

Native V7 structure audits use `structure-audit-v5` and `v7_architecture_review_decisions`. Historical V3/V4 structure audits remain immutable. During score-only migration, `subject-index-structure-locator-review-v1` records the mechanical derivation and any deterministic historical disposition.

If a historical migration first exposes an unreviewed trigger, preserve the
historical structure audit and freeze the authorized follow-up separately as
`subject-index-v7-architecture-review-supplement-v1`. The migration requires
the supplement's decision set to equal the unresolved trigger set exactly,
projects those decisions only in memory, and hash-binds the supplement in every
affected score view. It never upgrades or rewrites the V3/V4 file in place.

A `subject-index-v7-locator-fit-supplement-v1` is a different semantic input. It cannot add, remove, reinterpret, or replace a structure defect or architecture decision. Even when a decision cites an applicable historical structured defect ID, its sole effect is the affected locator's complete-path-fit category in memory; structure counts, dispositions, gates, and historical bytes remain unchanged.

## Migration dispositions

| Disposition | Meaning |
| --- | --- |
| `no_numeric_review_trigger` | Both corrected triggers are false and no associated architecture disposition applies |
| `review_required` | A trigger is true but no structured semantic review is frozen; full scoring stops |
| `reviewed_no_defect` | A structured review found no architecture defect |
| `structured_defect_confirmed` | Trigger plus complete structured semantic evidence and defect binding |
| `historical_false_positive_removed` | A sole atomic-threshold penalty is removed only from the active V7 projection |
| `historical_defect_retained` | The old defect cannot satisfy the narrow deterministic removal rule |
| `independent_architecture_disposition_retained` | A non-threshold architecture basis remains valid |
| `derivation_failed` | Frozen grouping or span cannot be reconstructed; scoring stops |

False-positive removal additionally requires an atomic count above six, no corrected trigger, no independent/unclassified architecture defect, no conflicting review, and a uniquely restorable adverse node status. A newly triggered case is never converted into a defect automatically.

## Display language

Report displayed locator count, atomic page count, and longest range separately. Never call expanded pages “undivided locators.” Explain long ranges separately from long locator lists, and state that neither numerical condition alone lowered a grade.
