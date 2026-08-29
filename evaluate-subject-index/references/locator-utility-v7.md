# V7 two-axis locator-utility mapping

This document is the closed, deterministic mapping inventory for rubric V7. It was prepared before the V7 calculator was implemented. The mapping consumes only frozen structured fields; `rationale`, `evidence_summary`, popover text, and other prose are never classification inputs.

## Inputs and closed-world rule

For each locator, V7 reads:

- `locator_id`;
- `judgment`;
- `treatment_class`;
- `source_scope_status`;
- locator `error_codes` and `severity`; and
- structured defects whose `affected_item_ids` contain that locator ID, including each defect's code, owner, kind, severity, and ID.

The validated locator audit and scoring-context defect ledger are exhaustive for the frozen evaluation. Absence of a fit-relevant code or locator-bound defect may therefore prove that an unsupported weak-presence locator has no independent path-fit failure. If the available fields are incomplete, contradictory, or permit more than one fit category, V7 rejects the locator instead of reading prose or choosing the more favorable category.

## Current-code inventory

| Code | Existing owner or role | V7 locator-fit classification |
| --- | --- | --- |
| `SCP` | Source or asserted scope | Scope-invalidating when the destination is excluded/nonindexable or a locator-bound defect establishes `out_of_scope_locator` or `scope_failure`; otherwise fit-relevant for an indexable path-scope mismatch |
| `COV` | Meaningful-coverage recall | Not a locator-fit classifier; locator-bound use is invalid |
| `SEL` | Editorial selectivity | Treatment/selectivity-only; does not lower complete-path fit |
| `CON` | Conceptual fidelity | Fit-relevant; severity determines a material or severe mismatch unless another structured state establishes no fit |
| `STA` | Stance fidelity | Fit-relevant; severity determines a material or severe mismatch unless another structured state establishes no fit |
| `LOC_POS` | Locator-precision consequence | Does not identify the semantic cause by itself; it may accompany another classifying state but cannot alone prove a favorable fit tier for an otherwise ambiguous unsupported locator |
| `LOC_NEG` | Missing-treatment recall | Not a locator-fit classifier; locator-bound use is invalid |
| `CMP` | Compound-path scope | Fit-relevant; severity determines a material or severe mismatch unless a critical/no-fit state applies |
| `HED` | Main-heading architecture | Fit-relevant when attached to the locator; severity determines a material or severe heading mismatch |
| `SUB` | Subheading architecture | Fit-relevant when attached to the locator; severity determines a material or severe heading mismatch |
| `XRF` | Cross-reference navigation | Not a page-locator fit classifier; locator-bound use is invalid |
| `DEN` | Chapter density | Not a locator-fit classifier; locator-bound use is invalid |
| `MEC` | Mechanics | Fit-neutral. It remains diagnostic but cannot justify an `unsupported` semantic judgment by itself |

Current structured defect kinds are also inventoried explicitly:

| Defect kind | V7 locator role |
| --- | --- |
| `fabricated_locator`, `nonexistent_locator`, `out_of_scope_locator`, `scope_failure` | Known invalid destination; treatment and fit are both zero |
| `stance_reversal`, `misleading_relationship`, `misleading_access_route` | Fit-relevant when locator-bound; minor maps to 0.35, major maps to 0.15, and critical maps to no fit |
| `clutter_pattern`, `density_distribution` | Treatment/selectivity or density diagnostics only |
| `central_omission`, `substitutive_see`, `circular_or_chained_reference`, `unsupported_reference` | Other-stage evidence; locator-bound use is invalid |
| `mechanical_invariant`, `representation_corruption` | Not a semantic fit classifier; it cannot justify `unsupported` by itself |
| `generic` | Uses its compatible structured error code and severity. A bare generic `LOC_POS` state remains ambiguous and is rejected |

The current locator-audit schema permits `SCP`, `SEL`, `CON`, `STA`, `LOC_POS`, `CMP`, `HED`, `SUB`, `XRF`, `DEN`, and `MEC`. `COV` and `LOC_NEG` exist in the complete defect vocabulary but are not valid locator-audit error codes. V7 preserves those historical schemas and validates this inventory at the calculation layer.

## Treatment axis

Treatment is a property of the cited destination, independent of whether the complete path describes that treatment correctly.

| Rule ID | Frozen state | Category | `T_j` |
| --- | --- | --- | ---: |
| `T-SUBSTANTIVE-100` | `substantive`, inspectable, indexable destination | substantive treatment | 1.00 |
| `T-MIXED-070` | `mixed`, inspectable, indexable destination | mixed treatment | 0.70 |
| `T-WEAK-025` | passing mention, attribution only, citation only, or incidental example | weak presence | 0.25 |
| `T-ABSENT-000` | `absent` | absent treatment | 0.00 |
| `T-INVALID-DESTINATION-000` | excluded/nonindexable scope or a locator-bound fabricated, nonexistent, out-of-scope, or scope-failure defect | invalid destination | 0.00 |
| `T-UNINSPECTABLE-BOUND` | unavailable or ambiguous scope/treatment with `uninspectable` judgment | neutral uncertainty bound | null |
| `T-NOT-MEASURED-REJECT` | required full-audit locator not measured | validation failure | null |

Invalid-destination precedence applies before the nominal treatment class. No treatment category is inferred from prose.

## Complete-path-fit axis

Fit asks whether the frozen treatment supports the complete heading path. Positive judgments retain their frozen meaning; `unsupported` records require the additional structured classification below.

| Rule ID | Frozen state | Category | `F_j` |
| --- | --- | --- | ---: |
| `F-SUPPORTED-100` | valid `supported` combined state | exact fit | 1.00 |
| `F-PARTIAL-070` | valid `partially_supported` combined state | material partial fit | 0.70 |
| `F-WEAK-TREATMENT-ONLY-100` | `unsupported` weak presence with no independent fit, scope, or no-fit code/defect | semantically fitting path | 1.00 |
| `F-MINOR-MISMATCH-035` | `unsupported` with a validated minor fit-relevant code or locator-bound defect | material mismatch | 0.35 |
| `F-MAJOR-MISMATCH-015` | `unsupported` with a validated major fit-relevant code or locator-bound defect | severe mismatch | 0.15 |
| `F-NO-FIT-000` | absent treatment; invalid destination; critical fit failure; or another structured no-fit state | no fit | 0.00 |
| `F-UNINSPECTABLE-BOUND` | unavailable or ambiguous evidence with `uninspectable` judgment | neutral uncertainty bound | null |
| `F-NOT-MEASURED-REJECT` | required full-audit locator not measured | validation failure | null |

When more than one validated fit-relevant defect applies to an unsupported locator, the strongest applicable severity controls: critical/no-fit, then major, then minor. Cosmetic evidence cannot justify an `unsupported` judgment. A `supported` state with a non-cosmetic independent fit defect or a known invalid destination is contradictory. A positive `partially_supported` state remains 0.70 unless a known invalid/no-fit destination makes that combined state contradictory.

Weak-presence exact fit is deliberately narrow. It requires an indexable, inspectable weak-presence treatment, `unsupported` judgment, and exhaustive absence of `SCP`, `CON`, `STA`, `CMP`, `HED`, or `SUB` causes and locator-bound no-fit or fit-relevant defects. `SEL` is permitted. A bare `LOC_POS` without a classifying cause is ambiguous and fails closed.

## Combination and grade

For every assessable locator:

```math
L_j=\min(T_j,F_j)
```

and:

```math
G_j=100L_j
```

The minimum is an independent-ceilings rule. It is not multiplication: mixed treatment plus partial fit is 0.70, not 0.49; weak presence plus partial fit is 0.25, not 0.175. The calculation ledger uses `L_j` directly. `G_j` is the matching non-additive display grade and is never averaged to reconstruct Page-reference Reliability.

## Validation failures

V7 rejects, at minimum:

- missing required structured fields;
- unknown judgment, treatment, scope, code, defect kind, or severity;
- positive judgment on excluded, fabricated, nonexistent, or otherwise invalid destination;
- `supported` with weak or absent treatment;
- `partially_supported` with absent treatment;
- `unsupported` substantive or mixed treatment without a classifying fit/no-fit state;
- unsupported weak presence with ambiguous bare `LOC_POS` evidence;
- `unsupported` justified only by cosmetic or fit-neutral evidence;
- locator-bound `COV`, `LOC_NEG`, `XRF`, `DEN`, or unrelated-stage defect kinds;
- conflicting no-fit and positive-fit states; and
- any state whose classification would require rationale or evidence-summary prose.

These failures are calculation-sufficiency failures. They do not alter the frozen audit and do not authorize a new semantic judgment.
