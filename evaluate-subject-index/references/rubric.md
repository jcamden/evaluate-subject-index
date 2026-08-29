# Subject-index evaluation rubric V6

- Rubric identity: `subject-index-rubric-v6`
- Dimension-calculation profile: `subject-index-dimension-calculation-v2`
- Calculation artifact: `subject-index-dimension-calculations-v2`

V6 scores one finished subject index from 0 to 100. It changes one scored measure: Page-reference Reliability now distinguishes an unsuccessful locator that reaches weak but genuine subject presence from one that reaches no relevant treatment. It does not change the substantive-indexing standard.

The other five dimension formulas, the six dimension weights, every cap, every publication gate, expected-treatment recall, treatment-unit coalescing, density, benchmark construction, and candidate-audit judgments are identical to V5. Their complete technical definitions remain preserved in [rubric-v5.md](rubric-v5.md) and are incorporated into V6 without modification.

Three layers remain separate:

1. diagnostic item grades explain individual locators, paths, nodes, references, and omissions but are never added into the score;
2. six dimension calculations produce ratings and weighted points; and
3. publication-readiness gates restrict claims and never alter or override score arithmetic.

## Scorecard and arithmetic

| Public question | Dimension | Weight | V6 status |
| --- | --- | ---: | --- |
| Does it include what matters? | Meaningful Coverage | 20 | unchanged |
| Does it leave out what does not belong? | Editorial Selectivity | 15 | unchanged |
| Does it represent the book accurately? | Conceptual and Stance Fidelity | 15 | unchanged |
| Does it point to the right pages? | Page-reference Reliability | 25 | weighted locator precision |
| Can readers find things efficiently? | Findability and Navigation | 20 | unchanged |
| Is it professionally consistent? | Mechanics and Consistency | 5 | unchanged |

All scored arithmetic uses `Decimal`. Consequence caps are applied to the full-precision base rating. The post-cap value is rounded to the nearest 0.5 using decimal `ROUND_HALF_UP`, awarded points are calculated as `final_rating / 5 × dimension_weight`, and points are rounded to two decimal places using the same policy. Editorial Selectivity retains its unchanged 10-point substantive plus 5-point density structure.

## Combined locator evidence state

Each locator assignment must retain all of these structured fields before V6 scoring or migration:

- locator judgment;
- treatment class;
- source-scope status;
- error codes and applicable structured defects; and
- inspectability status.

The calculator rejects contradictory or incomplete combinations. It does not infer a treatment class from prose and does not silently select the more favorable state. Examples of invalid combinations include a positive judgment on excluded or unavailable material, a `supported` judgment with non-material treatment, and an `unsupported` substantive or mixed treatment with no structured reason for the failure. A `partially_supported` judgment may pair with substantive, mixed, or weak-presence treatment, and diagnostic error codes do not override a positive judgment's reliability credit.

## Locator reliability credit

V6 applies exactly one deterministic credit to every assessable locator assignment:

| Combined locator evidence | Reliability credit |
| --- | ---: |
| `supported` | 1.00 |
| `partially_supported` | 0.50 |
| eligible weak-but-genuine presence | 0.25 |
| other `unsupported` | 0.00 |
| `uninspectable` | neutral; uncertainty bounds |
| required `not_measured` in full mode | validation failure |

Weak-but-genuine presence is limited to `passing_mention`, `attribution_only`, `citation_only`, and `incidental_example`. The 0.25 tier is available only when the source page is inspectable and indexable, the judgment is `unsupported`, and no known scope, compound-scope, conceptual, relational, sense, or stance failure independently requires zero.

Apply this precedence:

1. A known out-of-scope, nonexistent, fabricated, or nonindexable destination receives 0.
2. A consistent `supported` assignment receives 1.
3. A consistent `partially_supported` assignment receives 0.5 regardless of whether its genuine relevant presence is substantive, mixed, passing, attribution-only, citation-only, or an incidental example.
4. An `unsupported` assignment in one of the four weak-presence classes receives 0.25 unless a validated `SCP`, `CMP`, `CON`, or `STA` failure requires 0.
5. Every remaining `unsupported` assignment receives 0.
6. `uninspectable` remains neutral and enters the established lower/upper calculation.

The per-locator provenance records the assigned tier, credit, rationale, any code that actually disqualified an `unsupported` weak-presence assignment, and the ID of any structured fabricated, nonexistent, or out-of-scope defect. Diagnostic codes attached to `supported` or `partially_supported` evidence remain in the frozen ledger and retain their other consequences without being mislabeled as reliability disqualifiers.

## Page-reference Reliability — 25 points

Let the assessable denominator contain measured `supported`, `partially_supported`, and `unsupported` assignments only.

`Pw = Σ(locator_reliability_credit) / assessable_locator_assignments`

Expected-treatment recall is unchanged and uses unique `(subject_id, document_page, locator_class)` units:

`R = found / (found + missed)`

`F1w = 2 × Pw × R / (Pw + R)`, or 0 when `Pw + R = 0`

`base_rating = 5 × F1w`

Apply the unchanged V5 safeguards after calculating this base:

- pooled principal plus synthesis/conclusion high-value recall cap;
- critical fabricated, nonexistent, or out-of-scope locator cap;
- distributed reliability-owned unsupported-pattern cap; and
- empty, structurally incomplete, unparseable, and no-locator defined-zero rules.

The central denominator excludes `uninspectable` and legitimately unavailable assignments. Unknown locator and expected-treatment evidence enters the established adverse/favorable endpoint calculation; every cap is recalculated at both endpoints. Publish a number only when the endpoint rating and applied-cap identity are stable. Required `not_measured` evidence still blocks a full audit.

## Strict substantive precision remains public

V5 strict precision is retained as a separately reported diagnostic:

`strict_substantive_precision = supported / (supported + partially_supported + unsupported)`

Only `supported` receives strict credit. Partial support, weak presence, and all other unsupported assignments receive zero. Strict precision answers whether a destination provides substantive treatment. Weighted precision answers how severely an unsuccessful destination misdirects the reader. Weighted precision must never be labeled strict precision, and diagnostic item grades must never be averaged to reconstruct either dimension arithmetic or the 100-point score.

## Editorial Selectivity remains unchanged

| Treatment class | Selectivity credit |
| --- | ---: |
| `substantive` | 1.00 |
| `mixed` | 0.50 |
| `passing_mention` | 0.00 |
| `attribution_only` | 0.00 |
| `citation_only` | 0.00 |
| `incidental_example` | 0.00 |

Absent, out-of-scope, unavailable, and ambiguous assignments retain their existing ownership and exclusions. Reliability asks how misleading the cited destination is. Selectivity asks whether the locator deserved inclusion in a subject index. A weak mention therefore receives limited reliability credit but remains editorially unjustified.

## Worked locator examples

Assume each page is inspectable and indexable unless stated otherwise.

| Source-page evidence for the complete path | Judgment and treatment | Reliability credit | Strict credit | Diagnostic grade | Selectivity credit |
| --- | --- | ---: | ---: | ---: | ---: |
| A section explains the subject and supports the asserted relation and stance | `supported` + `substantive` | 1.00 | 1 | 100 | 1.00 |
| The subject is materially discussed, but the delivered heading is broader than the page supports | `partially_supported` + `mixed` | 0.50 | 0 | 70 | 0.50 |
| A passing mention, attribution, citation, or incidental example genuinely but only partly supports the asserted path | `partially_supported` + a weak-presence class | 0.50 | 0 | 70 | 0.00 |
| The subject appears once as an incidental illustration | `unsupported` + `incidental_example` | 0.25 | 0 | 25 | 0.00 |
| A person or work appears only in attribution or a citation | `unsupported` + `attribution_only` or `citation_only` | 0.25 | 0 | 25 | 0.00 |
| The asserted subject is absent | `unsupported` + `absent` | 0.00 | 0 | 0 | excluded from ordinary selectivity ownership |
| The same words occur in the wrong sense, relation, or stance | `unsupported` plus `CON` or `STA` | 0.00 | 0 | 0 | unchanged ownership |
| A compound path combines components that are not all supported on the page | `unsupported` + `CMP` | 0.00 | 0 | 0 | unchanged ownership |

The diagnostic grade of 25 must explain that the page contains the subject only weakly, incidentally, or as attribution/citation; it is not substantive index treatment; the locator remains editorially unjustified; and the limited grade distinguishes it only from a wholly false destination.

Judgment controls the 1.00 and 0.50 reliability tiers. Treatment class distinguishes 0.25 from 0 only after the frozen judgment is `unsupported`. Error codes explain the evidence state and continue to affect their owning dimensions, defects, caps, gates, and disclosures; they do not silently rewrite `supported` or `partially_supported` for reliability arithmetic.

## V5 versus V6

At `R = 1`, the isolated effect of the precision change is:

| Locator evidence | V5 strict `P` used in F1 | V6 weighted `Pw` used in F1 | V6 strict diagnostic |
| --- | ---: | ---: | ---: |
| supported | 1.00 | 1.00 | 1.00 |
| partially supported | 0.00 | 0.50 | 0.00 |
| eligible weak presence | 0.00 | 0.25 | 0.00 |
| other unsupported | 0.00 | 0.00 | 0.00 |

For four locators, one in each assessable tier, V6 gives `Pw = (1 + 0.5 + 0.25 + 0) / 4 = 0.4375` and strict precision `1 / 4 = 0.25`. V5 would have used strict precision `0.25` as the F1 precision input. Neither version treats the weak locator as substantive.

## Diagnostic locator grades

The V6 presentation policy is `subject-index-item-grading-v2`:

| Locator evidence | Diagnostic grade |
| --- | ---: |
| `supported` | 100 |
| `partially_supported` | 70 |
| eligible weak-but-genuine presence | 25 |
| other `unsupported` | 0 |
| `uninspectable` | null/neutral |

The intentionally retained grade of 70 is not the 0.50 dimension credit. Complete-path diagnostic calculations use these revised locator grades wherever Page-reference Reliability appears diagnostically. This non-additive display calculation does not replace `F1w`.

## Gates and defect consequences

V6 does not weaken a publication-readiness gate. In particular, limited reliability credit cannot clear or suppress:

- a systematic incidental or unsupported locator pattern;
- systematic named-entity, example, or citation clutter;
- a fabricated, nonexistent, or out-of-scope locator;
- compound-scope failure;
- a critical or major grounding failure; or
- any other V5 gate.

An eligible weak locator remains `unsupported`, retains its applicable error/defect record, counts in unchanged unsupported-pattern safeguards, and receives zero selectivity credit. Structured defect ownership and anti-double-counting rules remain unchanged.

## Structured calculation provenance

The Page-reference Reliability record is reconstructable from structured data. It retains the original, assessable, uninspectable, and not-measured locator denominators; counts by judgment, treatment class, and credit tier; every locator credit and disqualifier; both precision numerators, denominators, and values; expected-treatment recall; weighted F1; pre-cap rating; every central and endpoint cap evaluation; applied cap; uncertainty endpoints; rounding operation; final rating; dimension weight; and awarded points. V6 result and web-report projections expose both precision measures and bind the exact calculation and item-assessment identities.

## Versioning, compatibility, and migration

V5 artifacts retain their original identities and semantics. The V5 calculator, schemas, result reader, web-report reader, item-grading policy, and tests remain available; V6 uses new calculation, result, item-assessment, web-report, and migration identities. A V6 projection cannot validate as V5 or silently replace V5 history.

A V5-to-V6 score-only migration may reuse frozen evidence only after deterministic preflight verifies sufficient structured locator states. It preserves the benchmark, normalization, judgments, gates, representation-correction provenance, historical calculations/result, and immutable historical web-report bytes. Only calculation-derived active projections are invalidated. It never infers treatment from prose or reopens the source. See [score-migration-v5-to-v6.md](score-migration-v5-to-v6.md).

The credits `1`, `0.5`, `0.25`, and `0` are frozen methodological choices, not values tuned to an Oxford result. See [v6-sensitivity-analysis.md](v6-sensitivity-analysis.md) for test-backed adversarial mixtures.
