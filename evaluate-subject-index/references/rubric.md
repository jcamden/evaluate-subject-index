# Subject-index evaluation rubric v3

The rubric scores one finished subject index from 0 to 100. The total is not a percentage correct. Publish component scores, measured rates, gates, scope, and examples with it.

## Scorecard

| Public question | Dimension | Weight |
| --- | --- | ---: |
| Does it include what matters? | Meaningful coverage | 20 |
| Does it leave out what does not belong? | Editorial selectivity, including density fit | 15 |
| Does it represent the book accurately? | Conceptual and stance fidelity | 15 |
| Does it point to the right pages? | Page-reference reliability | 25 |
| Can readers find things efficiently? | Findability and navigation | 20 |
| Is it professionally consistent? | Mechanics and consistency | 5 |

Rate five dimensions from 0 to 5 in half-point increments; their weighted points are `rating / 5 * weight`. Editorial Selectivity is calculated from two transparent subscores: substantive selectivity contributes 10 points and density fit contributes 5. Display its equivalent 0–5 rating for readability, but retain the two subscore calculations.

| Rating | Meaning |
| ---: | --- |
| 5 | Excellent; consistently strong with only minor localized defects |
| 4 | Strong; reliable overall, but editorial correction is needed |
| 3 | Mixed; useful, but substantial problems reduce trust or usability |
| 2 | Weak; major omissions, excesses, inaccuracies, or structural defects |
| 1 | Poor; fragmentary, misleading, concordance-like, or largely unusable |
| 0 | Missing, invalid, or not meaningfully attempted |

## Required supporting measures

- Weighted concept recall: essential weight 3, major weight 2. Optional concepts do not enter the denominator unless frozen as scored.
- Essential-concept miss rate and localized-subject recall.
- Valid-entry precision and passing-mention/attribution/example clutter rates.
- Claim accuracy, stance preservation, and distinction preservation.
- Locator precision, locator recall, and optional F1, with denominators.
- Direct-access adequacy, reader-task success, cross-reference validity, and structural defect counts.
- Mechanics scan counts and manual adjudications.
- Density metrics, frozen bands, fit rating, and distribution diagnostics.

## Density scoring

Density measures whether the amount and distribution of access fit this source and audience. It is not a universal quota and does not replace source-grounded coverage or selectivity.

Before any candidate is opened, freeze at least one primary metric and preferably two corroborating metrics. Recommended metrics are:

- page-bearing heading paths per 100 indexable source pages;
- expanded locator assignments per 100 indexable source pages;
- standardized index footprint, such as index words per 10,000 source words when reliable text is available;
- median and upper-tail locators per page-bearing path;
- share of access concentrated in the densest 10% of headings; and
- chapter-level access distribution compared with substantive source distribution.

Each scored metric declares `ideal_min`, `ideal_max`, `acceptable_min`, and `acceptable_max`, with `acceptable_min <= ideal_min <= ideal_max <= acceptable_max`. The policy also records provenance and rationale. If no defensible bands can be established before candidates are viewed, mark density `descriptive_only`; do not fabricate a scored ideal after seeing the outputs.

For a scored primary density metric, let `x` be the candidate value and measure distance outside the acceptable band relative to the nearest acceptable boundary:

- within ideal band: density fit rating 5;
- within acceptable but outside ideal: 4;
- outside acceptable by up to 25% of the nearest boundary: 3;
- outside by more than 25% and up to 50%: 2;
- outside by more than 50% and up to 100%: 1;
- outside by more than 100%: 0.

Use predeclared metric weights if more than one metric is scored. Round only the resulting density fit rating to the nearest 0.5.

Within Editorial Selectivity, calculate `substantive_selectivity_rating / 5 * 10 + density_fit_rating / 5 * 5`. This makes density affect the total once. The equivalent dimension rating is `selectivity_points / 15 * 5`; it need not fall on a half step. Coverage and navigation may still reflect demonstrated omissions or friction, but they must not be penalized merely because the index is short or long.

Density cannot be interpreted without distribution. A candidate inside the global band may still have serious local overindexing, thin chapters, or catch-all headings; record those as source-grounded selectivity or navigation defects.

## Dimension anchors

- **Meaningful coverage:** 5 means all essential and nearly all major source subjects have proportionate useful access; 3 means most central material appears but important gaps or imbalances remain; 1 means fragmentary or superficial coverage.
- **Editorial selectivity:** 5 means almost every page-bearing access point is substantively justified and density fits the frozen profile; 3 means recurring clutter or material density mismatch; 1 means concordance-like excess or severe thinness. Report the selectivity evidence and density contribution separately.
- **Conceptual and stance fidelity:** 5 means headings preserve meaning, relationships, distinctions, and stance; 3 means recognizable but repeatedly vague/conflated/misleading; 1 means regular invention, reversal, or obscurity.
- **Page-reference reliability:** 5 means highly precise and complete with no systemic failure; 3 means useful but false pages and missed treatments reduce trust; 1 means locators are unreliable.
- **Findability and navigation:** 5 means terminology, hierarchy, direct access, subdivisions, and references work coherently; 3 means recurring burial, fragmentation, under/overdivision, or weak references; 1 means readers repeatedly encounter false trails.
- **Mechanics and consistency:** 5 means publication-quality filing, formatting, names, locators, and references; 3 means recurrent repairable defects; 1 means disorder materially obstructs use.

## Critical gates

An index cannot be called publication-ready if any applicable gate fails:

- central subject or conclusion missing;
- central claim fabricated, reversed, or materially misrepresented;
- nonexistent or fabricated page references;
- systematic term-matching or broad-overassignment failure;
- material unresolved, circular, or chained `see` references;
- wrong source span; or
- structurally invalid or incomplete output.

Freeze project-specific gates before candidate review.

## Interpretation bands

| Total | Interpretation |
| ---: | --- |
| 90–100 | Excellent finished index; potentially near publication-ready after full review |
| 80–89 | Strong index; meaningful editorial review still needed |
| 70–79 | Useful foundation; substantial revision required |
| 60–69 | Weak finished index; major reconstruction required |
| Below 60 | Poor reader access; not suitable as delivered |

No band alone means publication-ready. A failed gate overrides that claim, not the arithmetic score.

## Public reporting

Lead with one restrained conclusion limited to this source and candidate version. Show the six scores, gates, precision/recall, density fit, strongest evidence, most consequential defects, at least one genuine strength, audit scope, evaluator relationship, and limitations. Select examples by predefined error category or recurring pattern, not by embarrassment value.
