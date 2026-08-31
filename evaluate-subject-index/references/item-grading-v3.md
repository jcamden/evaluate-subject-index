# Diagnostic item grading — V7

V7 item assessments use `subject-index-item-grading-v3` and `subject-index-item-assessments-v4`. They are a presentation layer, not a seventh dimension and not an additive decomposition of the 100-point score.

## Locator grade

Each measured locator exposes its complete `locator_utility` ledger row. Its grade is exactly:

\[
G_j=100\min(T_j,F_j).
\]

Possible measured grades are 100, 70, 35, 25, 15, and 0. Uninspectable or pilot-only unmeasured locators remain neutral. The popover shows:

- frozen judgment, treatment class, scope/inspectability, codes, defects, and severity;
- treatment category, score, and rule ID;
- fit category, score, and rule ID;
- minimum combination rule, credit, and grade; and
- bounded/excluded/rejected reason.

When historical code/severity compatibility, conflict routing, or a locator-fit supplement supplied the fit classification, the row also exposes the stable compatibility/conflict rules or supplemental decision/evidence identities. These are provenance, not additional grade inputs and not a declaration that one historical classifier was correct. A supplement cannot supply `G_j`; item construction still derives it exactly from the calculation's `combined_credit`.

The grade equals the calculation credit on a 0–100 display scale. Page-reference Reliability never averages grades. Its only canonical precision input is `reliability_provenance.locator_utility_assignments[].combined_credit`.

## Complete-path display

V7 does not publish a canonical mean reliability grade for a path. Each locator remains visible individually. The path popover includes a non-scoring locator-string review with:

- delivered display IDs and displayed count;
- singleton/range/other kind;
- range endpoints and inclusive spans;
- maximum range span;
- expanded atomic IDs and atomic count;
- both numeric review triggers;
- independent architecture evidence;
- applicable defect IDs; and
- final disposition and deterministic rule IDs.

Required language:

> A displayed locator is one delivered page reference or continuous range. A range is audited as multiple atomic page assignments but counts as one displayed locator for scanning and subdivision review.

Do not call expanded pages “undivided locators.” Do not describe a long range as a long locator list. Do not imply that either trigger automatically lowered a grade.

The path’s Page-reference Reliability factor is `locator_level_only` with no score. Its overall display summary is recalculated from the remaining non-reliability diagnostics using the existing item-display reweighting rule. Thus neither old V6 locator grades nor new V7 locator grades are averaged into a complete-path display score.

## Other item families

Heading-node, cross-reference, source-subject, and non-reliability path diagnostics retain the V6 evidence and mappings. When migration deterministically removes a sole false-positive architecture penalty, the active V7 node/path diagnostic is rebuilt from a derived in-memory structure projection and the historical V6 item artifact remains unchanged.

Editorial Selectivity stays separate. A weak-presence locator can show grade 25 while still receiving zero substantive-selectivity credit. Publication caps and gates also remain separate and visible.

Applied locator-fit supplement schema, identity, file hash, self-hash, scope hash, and decision count are copied into the item artifact's provenance. The historical locator audit and V6 item artifact remain byte-identical.
