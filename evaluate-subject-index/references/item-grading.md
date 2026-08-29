# Diagnostic item grading and interactive display V2

- Item-assessment identity: `subject-index-item-assessments-v3`
- Diagnostic policy: `subject-index-item-grading-v2`
- Associated rubric: `subject-index-rubric-v6`

Diagnostic item grades explain individual evidence. They are a non-additive presentation layer: never add or average them to reconstruct the six dimension ratings or the 100-point score. Historical V5 displays retain [item-grading-v1.md](item-grading-v1.md), `subject-index-item-assessments-v2`, and `subject-index-item-grading-v1` unchanged.

## Locator grades

Apply the same validated combined locator state and precedence used by the V6 reliability calculator:

| Evidence | Grade | Status |
| --- | ---: | --- |
| `supported` | 100 | measured |
| `partially_supported` | 70 | measured |
| eligible weak-but-genuine presence | 25 | measured |
| other `unsupported` | 0 | measured |
| `uninspectable` | null | neutral/not measured for display |

Eligible weak presence is limited to an inspectable, indexable `unsupported` assignment classified as `passing_mention`, `attribution_only`, `citation_only`, or `incidental_example`, with no validated `SCP`, `CMP`, `CON`, or `STA` disqualifier and no structured fabricated, nonexistent, or out-of-scope defect.

The grade of 70 is intentionally retained for partial support even though its dimension-calculation credit is 0.50. It applies to every valid `partially_supported` judgment, including one paired with a weak-presence treatment class or a diagnostic `SCP`, `CMP`, `CON`, or `STA` code. Those fields explain the limitation and retain their non-reliability consequences; they do not override the judgment. The grade of 25 is likewise not the 0.25 precision numerator by another name; the two policies happen to distinguish the same `unsupported` weak-presence state on different scales.

Every grade-25 popover must state plainly that:

- the page contains the subject only weakly, incidentally, or as attribution/citation;
- the page does not qualify as substantive index treatment;
- the locator remains editorially unjustified; and
- limited diagnostic credit only distinguishes it from a wholly false destination.

Each locator assessment also exposes its dimension reliability credit, credit tier, source-scope status, codes that actually disqualified `unsupported` weak presence, and disqualifying defect IDs. Diagnostic codes on positive judgments remain in the bound locator ledger rather than being mislabeled as credit disqualifiers. A weak grade never changes the underlying `unsupported` judgment, erases a defect, clears a gate, or earns selectivity credit.

## Complete-path grades

A complete-path diagnostic remains a presentation summary of the entry as delivered. Where Page-reference Reliability appears as a diagnostic factor, use the locator grades `100/70/25/0` (neutral items excluded) and then apply the existing path-specific severity caps. Recompute the complete-path grade from its diagnostic components.

The path popover must disclose that this is a mean diagnostic locator grade and does not replace weighted locator precision or the V6 Page-reference Reliability formula.

All other complete-path component definitions and weights remain unchanged:

| Component | Diagnostic weight |
| --- | ---: |
| Meaningful Coverage | 20 |
| Editorial Selectivity | 15 |
| Conceptual and Stance Fidelity | 15 |
| Page-reference Reliability | 25 |
| Findability and Navigation | 20 |
| Mechanics and Consistency | 5 |

Unavailable or genuinely unmeasured components are reweighted rather than converted to zero, exactly as under V1.

## Other item families

Heading-node, cross-reference, and source-subject diagnostic rules, grade bands, semantic color tokens, confidence handling, caps, and evidence links remain unchanged from [item-grading-v1.md](item-grading-v1.md).

Every locator, complete path, heading node, cross-reference, and expected source subject must have exactly one stable assessment in a full audit. Pilot omissions are explicit neutral records. Every popover remains keyboard/focus/touch accessible and public-safe, using evidence IDs and short paraphrases rather than long copyrighted text.

## Validation

`scripts/item_grade_cli.py build-assessments --grading-policy subject-index-item-grading-v2` produces the V6 item policy for a native V6 run when the exact projection-safe V2 evidence identity is available. For score-only migration, `upgrade-v6-assessments` accepts the immutable V2 item artifact plus the exact bound locator-audit set and structure audit; it verifies their hashes before writing a separate V3 artifact. Both paths refuse a legacy display artifact that cannot be bound to frozen calculation evidence.

The V3 schema checks the new identity, mappings, per-locator tier and disqualifiers, and unchanged item-family completeness. V6 projection validation additionally checks the required grade-25 explanation and exact evidence binding.
