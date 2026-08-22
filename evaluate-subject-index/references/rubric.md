# Subject-index evaluation rubric v4

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

Rate the five non-selectivity dimensions from 0 to 5 in half-point increments; their weighted points are `rating / 5 * weight`. Calculate Editorial Selectivity from two transparent subscores: substantive selectivity contributes 10 points and density fit contributes 5. Display its equivalent 0–5 rating for readability, but retain the two subscore calculations.

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

Density measures whether the amount and distribution of access fit this source. It is not a quota and does not replace source-grounded coverage or selectivity. Apply the built-in profile before any candidate is opened:

| Metric | Target | Target band | Broad tolerance band | Weight |
| --- | ---: | ---: | ---: | ---: |
| Locator-bearing complete heading paths per 1,000 indexable source words | 8 | 6–10 | 4–12 | 50% |
| Expanded locator occurrences per 1,000 indexable source words | 20 | 15–25 | 10–30 | 50% |

Measure each approved chapter or intellectual unit. Average its two metric ratings, then calculate the indexable-source-word-weighted mean across units and round only the final fit rating to the nearest 0.5. Retain chapter outliers and whole-index totals as diagnostics. Treat exceptionally short units as descriptive or combine them with a declared adjacent unit when rates are unstable.

The targets are calibration points, not quotas, minimums, hard ceilings, or instructions to prune valid access. The target bands allow ordinary variation; the broad tolerance bands delay meaningful score loss until an index is substantially sparse or dense. Do not use this profile to determine how many subjects belong in the source benchmark.

For each metric, let `x` be the candidate value and measure distance outside the broad tolerance band relative to the nearest boundary:

- within target band: density fit rating 5;
- within broad tolerance but outside target: 4;
- outside broad tolerance by up to 25% of the nearest boundary: 3;
- outside by more than 25% and up to 50%: 2;
- outside by more than 50% and up to 100%: 1;
- outside by more than 100%: 0.

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

- fabricated, nonexistent, or out-of-scope locator;
- systematic incidental or unsupported locator pattern;
- central subject or conclusion materially omitted;
- central claim fabricated, reversed, or materially misrepresented;
- compound heading whose locators support only separate components;
- `see` source replacing a warranted substantive entry;
- unresolved, self-referential, circular, or chained cross-reference;
- any third-level heading;
- systematic named-entity, example, or citation clutter;
- critical or major unresolved grounding;
- more than 1% of in-scope locator assignments uninspectable without a frozen alternative tolerance;
- wrong source span; or
- structurally invalid or incomplete output.

These are the standardized gates. Add a source-specific gate only before candidate review and record its rationale.

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

Lead with one restrained conclusion limited to this source and candidate version. Show the six scores, gates, precision/recall, strongest evidence, most consequential defects, at least one genuine strength, audit scope, evaluator relationship, and limitations. Select examples by predefined error category or recurring pattern, not by embarrassment value.

Show density as a separate plain-language calibration card. State the framework targets—8 locator-bearing heading paths and 20 locator occurrences per 1,000 indexable source words—the target and broad tolerance bands, chapter-level basis, observed distribution, fit rating, and five-point maximum contribution. Call them this framework’s standardized calibration targets, not universal professional requirements or hard limits.
