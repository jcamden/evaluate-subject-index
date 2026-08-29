# Subject-index evaluation rubric V5

- Rubric identity: `subject-index-rubric-v5`
- Dimension-calculation profile: `subject-index-dimension-calculation-v1`
- Calculation artifact: `subject-index-dimension-calculations-v1`

V5 scores one finished subject index from 0 to 100. The total is not a percentage correct. Every rating is derived from validated raw ledger statuses by `scripts/dimension_score_cli.py`; canonical V5 scoring does not accept evaluator-selected headline ratings.

Three layers remain distinct:

1. diagnostic item grades explain individual locators, paths, nodes, references, and omissions and are never added into the score;
2. the six dimension calculations produce ratings and weighted points; and
3. publication-readiness gates restrict claims and never alter, add to, subtract from, or override score arithmetic.

## Scorecard and arithmetic

| Public question | Dimension | Weight |
| --- | --- | ---: |
| Does it include what matters? | Meaningful Coverage | 20 |
| Does it leave out what does not belong? | Editorial Selectivity | 15 |
| Does it represent the book accurately? | Conceptual and Stance Fidelity | 15 |
| Does it point to the right pages? | Page-reference Reliability | 25 |
| Can readers find things efficiently? | Findability and Navigation | 20 |
| Is it professionally consistent? | Mechanics and Consistency | 5 |

For every dimension except Editorial Selectivity, apply consequence caps to the full-precision base rating, round the post-cap result to the nearest 0.5 with decimal `ROUND_HALF_UP`, then calculate `final_rating / 5 × dimension_weight` and round awarded points to two decimals the same way. Sum the six displayed awarded-point values and round the total to two decimals.

Editorial Selectivity keeps its 10+5 structure. Round its post-cap substantive rating to a half step, calculate up to 10 points from it, add the half-step density rating as up to 5 points, and display `selectivity_points / 15 × 5` as the equivalent dimension rating. That equivalent may fall off a half step.

Retain the exact decimal base, post-cap unrounded value, cap evaluations, rounding input and output, final rating, weight, and awarded points. Qualitative anchors are a post-calculation reasonableness check only. An anchor mismatch produces a warning; it never permits editing the number.

## Evidence completeness and uncertainty

- `not_applicable` is excluded only when genuine inapplicability is frozen from the benchmark and audit. Candidate absence alone never establishes it.
- `uninspectable` is neutral, disclosed, and never zero.
- In full mode, any required `not_measured` item blocks the affected dimension and total.
- A component is provisionally scoreable when at least 95% of its applicable denominator is measured. The one-item small-denominator exception applies when the denominator is below 20, exactly one item is uninspectable, at least one is measured, and none is `not_measured`.
- For every uninspectable item, calculate a lower bound using the minimum permitted credit and an upper bound using the maximum. Reevaluate every prevalence or recall cap at both bounds. Pilot-mode `not_measured` items are included in the same conservative bounds.
- Publish a numeric dimension rating only when both bounds yield the same public rating and the same applied-cap identity. Otherwise the dimension and total are `not_scored_insufficient_evidence`.
- The separate uninspectable-locator publication gate can fail even when bounds are stable enough for a number.

Every component records original, applicable, measured, excluded, uninspectable, and not-measured denominators plus exclusions by reason. A zero denominator cannot silently become a perfect or renormalized score.

Before arithmetic, the scorer hash-validates the canonical user-approved chunk manifest and requires it to record unique ownership and complete required scope coverage. It then requires exactly one locator audit and one missing-access audit for every manifest source unit. Chunk IDs must be unique, and the manifest, locator-audit, missing-access-audit, and structure-density sets must match exactly; mutually consistent subsets are insufficient. Every audit must bind the same evaluation, candidate, source, benchmark, benchmark lock, judgment policy, page map, chunk manifest, normalized candidate, and item inventory. The frozen structure audit or historical supplement must also bind the requested full/pilot audit mode. A caller cannot relabel pilot evidence as full.

Every locator-derived aggregate is checked against the stable locator ledger before scoring. Global `expanded_locators` equals the expected locator-ID denominator, global `cross_references` equals the expected cross-reference-ID denominator, and global `page_bearing_paths` equals the unique `PATH-*` set when locator coverage is complete. Within each source unit, density occurrences are rebuilt from expected locator IDs and locator-bearing paths from unique path IDs. In pilot mode only, an absent not-measured locator can make the exact path total unknowable; the declared path count must then remain within the reconstructable known-path-through-known-plus-missing range and the calculation discloses that bounded basis. A complete ledger permits no such latitude.

Expected treatments are unique logical `(subject_id, document_page, locator_class)` units, not merely unique record IDs. Every `not_applicable` node component must have a one-to-one frozen `benchmark_genuinely_inapplicable` decision with evidence IDs; otherwise it is not excluded.

## 1. Meaningful Coverage — 20 points

Use each frozen scored subject once with priority weight essential = 3, major = 2, and optional = 1 only when the benchmark explicitly freezes that optional subject as scored. Credits are complete = 1, partial = 0.5, and missing = 0.

`weighted_access = Σ(priority_weight × coverage_credit) / Σ(priority_weight)`

`base_rating = 5 × weighted_access`

Essential subjects are already weight 3 in the base. They enter again only through this non-additive miss-rate cap:

| Essential miss rate | Maximum rating |
| ---: | ---: |
| 0% | 5.0 |
| >0% through 5% | 4.5 |
| >5% through 10% | 4.0 |
| >10% through 20% | 3.5 |
| >20% through 35% | 3.0 |
| >35% through 50% | 2.0 |
| >50% | 1.0 |

An explicitly critical central omission caps the dimension at 2.0. Use the most restrictive applicable cap only.

## 2. Editorial Selectivity — 15 points

### Substantive selectivity — 10 points

Use locator treatment classes that answer the selectivity question: substantive = 1, mixed = 0.5, and passing mention, attribution only, citation only, and incidental example = 0. Absent, out-of-scope, unavailable, and ambiguous assignments remain owned by reliability, scope, or missing-data handling and do not enter the ordinary denominator.

`substantive_rate = Σ(locator_credit) / selectivity_applicable_locators`

`substantive_base_rating = 5 × substantive_rate`

A zero-credit pattern is systemic only when it contains at least 10 applicable locators and reaches at least 25% of approved source units:

| Systemic zero-credit rate | Maximum substantive rating |
| ---: | ---: |
| Below 5% | none |
| 5% to below 15% | 4.0 |
| 15% to below 30% | 3.0 |
| 30% to below 50% | 2.0 |
| At least 50% | 1.0 |

Locator-bearing output with no substantive or mixed-supported access receives a zero substantive subscore. An empty or not-meaningfully-attempted index receives zero rather than favorable undefined treatment.

### Density fit — 5 points

Use the existing chapter-level profile once, only here:

| Metric | Target | Target band | Broad tolerance band | Weight |
| --- | ---: | ---: | ---: | ---: |
| Locator-bearing complete heading paths per 1,000 indexable source words | 8 | 6–10 | 4–12 | 50% |
| Expanded locator occurrences per 1,000 indexable source words | 20 | 15–25 | 10–30 | 50% |

For each metric, the rating is 5 inside the target band, 4 inside broad tolerance, 3 up to 25% outside broad tolerance, 2 above 25% through 50%, 1 above 50% through 100%, and 0 beyond 100%. V5 adds one explicit edge rule: a metric value of exactly zero receives 0, not 1. Average the two metrics per source unit, calculate the indexable-source-word-weighted unit mean, and round the final density rating to 0.5 with decimal half-up. Historical V4 validation retains its original zero-to-1 behavior; the V5 correction is applied only by the V5 calculation profile and never silently rewrites V4 artifacts.

The structure worker records indexable source words and its observed counts, but the scorer never treats those count aggregates as independent truth. It recomputes occurrence counts and, whenever complete, path counts from the exact chunk-owned locator records, rejects any mismatch, and records count provenance in the calculation artifact.

`selectivity_points = substantive_rating / 5 × 10 + density_rating / 5 × 5`

Density is calibration, not a quota, minimum, hard ceiling, benchmark-discovery rule, or second penalty elsewhere.

## 3. Conceptual and Stance Fidelity — 15 points

Use every applicable raw node-component status: pass = 1.00, minor = 0.85, major = 0.55, and fail = 0.

`base_rating = 5 × Σ(node_credit) / measured_nodes`

Apply the most restrictive applicable cap:

| Condition | Maximum rating |
| --- | ---: |
| Any validated localized major `CON`, `STA`, or `CMP` defect | 4.5 |
| Major stance reversal or seriously misleading relationship | 4.0 |
| Major-or-fail node prevalence at least 5% | 3.5 |
| Major-or-fail prevalence at least 15% | 2.5 |
| Major-or-fail prevalence at least 30% | 1.5 |
| Any critical `CON`, `STA`, or `CMP` defect | 2.0 |

Every major or failed node must cite a validated structured defect record. Aggregate raw node statuses, never diagnostic item-grade scores or subject `stance_preserved` fields.

## 4. Page-reference Reliability — 25 points

Strict precision treats partial support as incorrect while still reporting it separately:

`P = supported / (supported + partially_supported + unsupported)`

Expected-treatment recall uses unique subject-ID/document-page/locator-class treatment units:

`R = found / (found + missed)`

`F1 = 2PR / (P + R)`, or 0 when `P + R = 0`

`base_rating = 5 × F1`

When expected treatments exist but the candidate supplies no assessable locators, the dimension is zero. Pool principal plus synthesis/conclusion units for the high-value safeguard; supporting treatments remain in overall recall.

| High-value treatment recall | Maximum rating |
| ---: | ---: |
| At least 90% | none |
| 75% to below 90% | 4.0 |
| 50% to below 75% | 3.0 |
| 25% to below 50% | 2.0 |
| Below 25% | 1.0 |

Any critical fabricated, nonexistent, or out-of-scope locator caps the dimension at 2.0. A reliability-owned unsupported pattern must carry `LOC_POS`, `SCP`, `CMP`, `CON`, or `STA`, exclude failures whose only consequence is selectivity or architecture, and affect at least 25% of source units:

| Distributed reliability-owned unsupported rate | Maximum rating |
| ---: | ---: |
| Below 1% | none |
| 1% to below 3% | 4.5 |
| 3% to below 7.5% | 4.0 |
| 7.5% to below 15% | 3.5 |
| 15% to below 30% | 2.5 |
| At least 30% | 1.5 |

## 5. Findability and Navigation — 20 points

Use 60% coverage-conditioned reader-task success, 30% heading/access architecture, and 10% cross-reference validity.

- Tasks: succeeds = 1, partially succeeds = 0.5, fails = 0.
- Architecture nodes: pass = 1.00, minor = 0.85, major = 0.55, fail = 0.
- References: supported = 1, partially supported = 0.5, unsupported = 0.

A task is eligible only when every required frozen subject has at least partial access. Report all excluded tasks with `excluded_due_to_missing_access`; the UI must label the component “navigation success among subjects having at least partial access.” If a meaningful candidate attempt has tasks but every task is excluded by missing or uncertain coverage, the task component—and therefore the navigation dimension—is not scoreable; do not convert the absence of coverage-eligible evidence into an explicit zero. The separate explicit-zero rule applies only to an empty or structurally incomplete navigation attempt.

When required-subject coverage is uninspectable in pilot mode, vary task eligibility and task credit jointly. The adverse endpoint may resolve the subject as accessible and include the task at its minimum permitted credit; it may not improve the lower bound merely by excluding the uncertain task. The favorable endpoint chooses the permitted eligibility/result combination that maximizes conditional success. Both endpoints reevaluate task-failure counts and caps and record which coverage-uncertain task IDs were included.

`base_rating = 5 × (0.60T + 0.30A + 0.10X)`

The reference component is genuinely inapplicable only when no references are delivered and the frozen audit identifies neither a warranted reference obligation nor a reference defect. Freeze both the obligation count and exact subject/task/treatment/node or `GLOBAL-STRUCTURE` IDs for obligations that were warranted but not delivered; a delivered `XREF-*`, locator, or path ID is not an obligation. Then renormalize 60/30 to two-thirds/one-third. Every warranted-but-undelivered route is a measured zero even when other references were delivered. When no route or obligation was recorded, only a structured findability-navigation `XRF` defect may supply applicable adverse zero evidence, and the frozen reference-defect IDs must exhaustively name every such structured defect; a defect owned by another dimension cannot be reclassified or silently omitted.

Apply the most restrictive applicable cap:

| Condition | Maximum rating |
| --- | ---: |
| Any localized major navigation/reference defect | 4.5 |
| Substitutive `see`, circular/chained route, or comparable misleading failure that destroys essential/major access | 3.5 |
| Any critical navigation defect | 2.0 |
| Eligible-task failure rate at least 10% / 25% / 50% | 4.0 / 3.0 / 2.0 |
| Major-or-fail architecture prevalence at least 5% / 15% / 30% | 4.0 / 3.0 / 2.0 |

For unsupported delivered references, require both rate and recurrence count: at least 2 and 10% caps at 4.0; at least 2 and 25% caps at 3.0; at least 3 and 50% caps at 2.0. A single unresolved target remains localized unless structured evidence establishes a more consequential defect.

## 6. Mechanics and Consistency — 5 points

Use every applicable mechanics node: pass = 1.00, cosmetic = 0.95, minor = 0.85, major = 0.55, and fail/critical = 0.

`base_rating = 5 × Σ(node_credit) / measured_nodes`

Every deterministic invariant failure must attach to affected nodes or to a global structural failure. Apply the most restrictive cap:

| Condition | Maximum rating |
| --- | ---: |
| Structurally incomplete or unparseable output | 0 |
| Any critical mechanics defect | 2.0 |
| Any localized unresolved major mechanics defect | 4.5 |
| Same major root-cause family affects at least 3 nodes and either 1% of nodes or 2 structural sections | 4.0 |
| Same major root-cause family affects at least 3 nodes and either 10% of nodes or 50% of relevant structural sections | 3.0 |
| Aggregate cosmetic/minor prevalence at least 5% | 4.5 |
| Aggregate cosmetic/minor prevalence at least 20% | 4.0 |

Localized cosmetic or minor defects have no cap. Empty or structurally incomplete output receives zero rather than a favorable empty denominator.

## Structured defect provenance

A cap never triggers from free-text rationale. Each scoring defect freezes and validates:

- defect ID, code, and one dimension owner;
- severity and operational `severity_basis`;
- realistic retrieval consequence: blocks, misleads, slows, or none;
- affected item IDs, source sections, and structural sections;
- recurrence/root-cause family;
- affected and applicable counts plus reconstructable rates;
- source- and structure-section denominators and rates; and
- whether a misleading route destroys essential/major access.

Critical bases are fabrication, central reversal, broken scope, or systemic nonuse. Major bases are materially misleading or blocked retrieval. Minor means localized repairable friction with a usable route. Cosmetic means no retrieval consequence. Basis, defect kind, owner, code, and consequence must be compatible. `systemic_nonuse` requires at least three affected items and either a 10% item rate or a 50% source/structural-section rate; a one-item defect cannot claim systemic criticality. A defect's affected IDs must belong to one reconstructable item family, and `applicable_count` must equal that family's original denominator: stable expected locator IDs, unique locator-ledger path IDs, stable subject/task/treatment/node/cross-reference IDs, or the one global structure. Complete-ledger path totals must match exactly; a pilot ledger with absent not-measured locator records permits only the disclosed reconstructed range. Source-section IDs must resolve to approved chunks, structural-section IDs to audited main headings, and both denominators must equal those frozen sets. `high_priority_access_destroyed` is valid only when the defect names an affected essential or major subject. Historical ledgers lacking these fields require a separate hash-bound `subject-index-v5-migration-supplement-v1`; never edit the historical audit or infer a cap from its prose.

The calculation artifact records every evaluated cap, including non-triggered caps, its exact threshold, structured observed values, affected evidence IDs, and the one most restrictive applied cap. Caps never stack or subtract points.

## Qualitative anchors and interpretation

The familiar 5/4/3/2/1/0 descriptions remain useful editorial checks: excellent, strong, mixed, weak, poor, and missing/invalid. They are not numerical inputs. Review a surprising formula result by correcting a ledger judgment, structured defect record, formula version, or implementation—not by manually changing the rating.

| Total | Interpretation |
| ---: | --- |
| 90–100 | Excellent finished index; potentially near publication-ready after full review |
| 80–89 | Strong index; meaningful editorial review still needed |
| 70–79 | Useful foundation; substantial revision required |
| 60–69 | Weak finished index; major reconstruction required |
| Below 60 | Poor reader access; not suitable as delivered |

No band means publication-ready. Publication gates remain separately displayed claim restrictions.

## Versioning and comparability

V4 accepted five headline ratings and the substantive-selectivity rating from the evaluator, then performed deterministic weighted arithmetic. V5 derives all six dimensions from ledgers and stores reconstructable provenance. V4 and V5 totals are therefore not directly comparable and a V5 result must never silently replace V4 history.

The frozen source benchmark, source judgments, page map, chunks, candidate normalization, locator audits, missing-access audits, and structure judgments remain valid when only the score calculation profile changes and the sufficiency preflight confirms the required V5 inputs. A score-profile change invalidates only dimension calculations, the active evaluation result, and the web report. See [score-migration-v4-to-v5.md](score-migration-v4-to-v5.md).
