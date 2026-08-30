# Subject Index Evaluation technical rubric — V7

## Version identity and scope

V7 uses:

- rubric `subject-index-rubric-v7`;
- calculation profile `subject-index-dimension-calculation-v3`;
- calculation artifact `subject-index-dimension-calculations-v3`;
- result `subject-index-evaluation-result-v8`;
- item-grading policy `subject-index-item-grading-v3`;
- item artifact `subject-index-item-assessments-v4`;
- web report `subject-index-web-report-v6`; and
- migration `subject-index-score-migration-v6-to-v7-v1`.

V7 changes the per-locator precision input to Page-reference Reliability and corrects the counting unit used for locator-string architecture review. Benchmark construction, blindness, locator and missing-access judgments, expected-treatment recall, treatment-unit coalescing, weights, the other dimension formulas, Editorial Selectivity, density, caps, gates, uncertainty, rounding, defect ownership, and representation-adjustment provenance remain unchanged. Historical V4, V5, and V6 artifacts retain their original readers and identities.

## Two independent locator facts

For assessable locator (j), V7 derives two independent ceilings from frozen structured evidence:

\[
T_j=\text{page-treatment score},\qquad F_j=\text{complete-path-fit score}.
\]

It combines them with:

\[
L_j=\min(T_j,F_j),\qquad G_j=100L_j.
\]

The minimum is deliberate. It prevents multiplication from double-counting a limitation already represented by both `mixed` treatment and `partially_supported` fit. Substantial relevant discussion can therefore retain limited treatment credit even when a relationship or stance is wrong. The displayed grade and calculation credit use the same scale, but grades remain non-additive and are never averaged to reconstruct Page-reference Reliability.

### Page treatment

| Frozen structured state | Category | (T_j) | Rule |
| --- | --- | ---: | --- |
| `substantive` | substantive | 1.00 | `T-SUBSTANTIVE-100` |
| `mixed` | mixed | 0.70 | `T-MIXED-070` |
| `passing_mention`, `attribution_only`, `citation_only`, or `incidental_example` | weak presence | 0.25 | `T-WEAK-025` |
| `absent` | absent | 0.00 | `T-ABSENT-000` |
| fabricated, nonexistent, out-of-scope, or nonindexable destination | invalid destination | 0.00 | `T-INVALID-DESTINATION-000` |
| `uninspectable` | neutral uncertainty | 0–1 bound | `T-UNINSPECTABLE-BOUND` |
| required `not_measured` in full mode | validation failure | — | `T-NOT-MEASURED-REJECT` |

Treatment is derived only from `treatment_class`, `source_scope_status`, and inspectability. Rationale and evidence prose are prohibited inputs. Editorial Selectivity keeps its own substantive, mixed, and weak-presence mapping; weak presence still receives zero selectivity credit.

### Complete-path fit

| Frozen structured state | Category | (F_j) | Rule |
| --- | --- | ---: | --- |
| `supported` with a valid combined state | exact fit | 1.00 | `F-SUPPORTED-100` |
| `partially_supported` with a valid combined state | material partial fit | 0.70 | `F-PARTIAL-070` |
| historically `unsupported` weak presence, with exhaustive proof that treatment/selectivity is the only limitation | exact fit | 1.00 | `F-WEAK-TREATMENT-ONLY-100` |
| `unsupported` with a validated minor fit defect | material mismatch | 0.35 | `F-MINOR-MISMATCH-035` |
| `unsupported` with a validated major fit defect | severe mismatch | 0.15 | `F-MAJOR-MISMATCH-015` |
| absent subject, wrong subject/sense, invalid destination, or another structured no-fit state | no fit | 0.00 | `F-NO-FIT-000` |
| `uninspectable` | neutral uncertainty | 0–1 bound | `F-UNINSPECTABLE-BOUND` |
| required `not_measured` in full mode | validation failure | — | `F-NOT-MEASURED-REJECT` |

The closed code inventory is:

| Code | Locator-fit role |
| --- | --- |
| `SEL` | treatment/selectivity-only |
| `SCP`, `CON`, `STA`, `CMP`, `HED`, `SUB` | fit-relevant when attached to the locator through structured fields |
| `LOC_POS` | consequence-only; it cannot establish fit by itself |
| `MEC` | fit-neutral |
| `COV`, `LOC_NEG`, `XRF`, `DEN` | invalid on a locator-fit mapping and rejected |

Fabrication/nonexistence/out-of-scope/scope-failure defect kinds and exact structured no-fit root-cause families override nominal fit. Minor and major are the only mismatch severities; a critical fit failure establishes no fit. A bare `LOC_POS`, unclassified material treatment, contradictory severity, or incompatible code/defect combination fails closed. Free text cannot repair an incomplete state.

## Page-reference Reliability

For assessable locators:

\[
P_W=\frac{\sum_j L_j}{N_{\mathrm{assessable}}}.
\]

Expected-treatment recall remains:

\[
R_T=\frac{\mathrm{found}}{\mathrm{found}+\mathrm{missed}}.
\]

The unchanged harmonic mean and base rating are:

\[
F_{1W}=\frac{2P_WR_T}{P_W+R_T},\qquad \text{base rating}=5F_{1W},
\]

with zero when (P_W+R_T=0). Existing reliability caps, uncertainty endpoints, defined-zero rules, rounding, and gates apply unchanged.

Strict substantive precision remains separately public:

\[
\text{strict precision}=\frac{\mathrm{supported}}{\mathrm{supported}+\mathrm{partially\ supported}+\mathrm{unsupported}}.
\]

It is not renamed, and the new two-axis precision is not described as strict precision.

## Three structure quantities

> A displayed locator is one delivered page reference or continuous range. A range is audited as multiple atomic page assignments but counts as one displayed locator for scanning and subdivision review.

V7 preserves three noninterchangeable quantities:

| Quantity | Meaning | Permitted use |
| --- | --- | --- |
| `displayed_locator_count` | Delivered `DISPLAY-*` records after one complete path; a range counts once | Locator-string scanning and subdivision review |
| per-range inclusive span and `maximum_range_span` | Atomic pages owned by one continuous `RANGE-*` | Separate long-continuous-range review |
| `atomic_assignment_count` | Expanded `LOC-*` path/page assignments | Locator auditing, precision, recall, routing, and existing density formulas |

The deterministic review triggers are:

\[
\text{displayed locator count}>6
\]

and, separately,

\[
\text{inclusive continuous-range span}>10.
\]

Six displayed locators and a ten-page range do not trigger; seven and eleven do. Atomic assignments are never the locator-string denominator.

These frozen V7 thresholds operationalize professional guidance while keeping the semantic judgment separate. The [American Society for Indexing checklist](https://asindexing.org/about-indexing/index-evaluation-checklist/) discusses roughly 5–7 locators and separately flags extensive ranges. [University of Georgia Press guidance](https://www.ugapress.org/indexing-guidelines/) likewise distinguishes a long locator list from a range covering many pages. The [Society of Indexers](https://www.indexers.org.uk/posts/commissioning-an-indexer-part-3/) also discusses locator strings and long spans as separate review questions. An editor/indexer vocabulary explanation explicitly notes that a page range represents multiple pages but one locator ([An American Editor](https://americaneditor.wordpress.com/2018/05/21/book-indexes-part-1-basic-vocabulary/)).

### Review is not a defect

Neither threshold changes a grade by itself. A structured architecture defect requires all of the following:

1. conceptually distinguishable treatments;
2. meaningful subheadings or alternative access routes;
3. material scanning or retrieval impairment; and
4. a conceptual, nontrivial subdivision—not a merely page-based, chronological-without-conceptual-value, grammatical, or trivial division.

Free-text explanation alone cannot create a defect or cap. A sustained discussion may justify a long range; one coherent subject may justify a long displayed list.

## Required calculation provenance

Every locator row records frozen judgment/treatment/scope, inspectability, codes, structured-defect IDs, locator and effective severity, both categories and scores, both rule IDs, the combined rule, (L_j), (G_j), disposition, exclusion/bound/rejection reason, and uncertainty endpoints. Reliability records complete counts by judgment, treatment class/tier, fit tier, and combined credit, all numerators/denominators, both precisions, recall, F1, caps, uncertainty, rounding, final rating, and points.

Every locator-bearing path records delivered display IDs, display kind, range identity/endpoints/span, exact display-to-atomic binding, all expanded atomic IDs, the three counts, both triggers, independent architecture evidence, applicable defects, final disposition, and derivation/mapping rules. Runtime validation rejects range splitting, missing ownership, trigger-only defects, and unreviewed triggered cases treated as passing or failing.

## Migration

`subject-index-score-migration-v6-to-v7-v1` is calculation-only and display-only. It preserves V6 evidence and projections as immutable history, requires exact normalized-candidate and inventory hashes, rejects prose inference, derives structure counts mechanically, recalculates representation-adjusted views from each view’s own inputs/provenance, preserves gates, and emits a receipt covering active and historical projections.

A sole historical defect with the exact structured atomic-threshold-only basis may be removed from the active V7 projection when corrected triggers are both false and no independent architecture evidence remains. A newly exposed trigger cannot invent a semantic judgment: it becomes `review_required`, and full scoring stops pending a narrow supplemental architecture review. Source pages, locator-support judgments, missing-access audits, and unrelated structure judgments are never reopened.
