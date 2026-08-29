# V6 weighted-locator sensitivity analysis

This note examines the frozen V6 reliability credits; it is not an empirical fit to a candidate. Arithmetic is covered by `tests/test_dimension_scoring_v6.py` and uses `Decimal` plus decimal half-up rounding.

Unless a row states otherwise, expected-treatment recall is `R = 1`, no uncertainty is present, and no cap is triggered. “Points” is the Page-reference Reliability contribution out of 25, not the total evaluation score.

| Mix of assessable locators | Weighted `Pw` | Strict precision | `F1w` | Base rating | Rounded rating | Reliability points |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 100% supported | 1.0000 | 1.0000 | 1.0000 | 5.0000 | 5.0 | 25.00 |
| 100% partially supported | 0.5000 | 0.0000 | 0.6667 | 3.3333 | 3.5 | 17.50 |
| 100% eligible weak presence | 0.2500 | 0.0000 | 0.4000 | 2.0000 | 2.0 | 10.00 |
| One supported, one partial, one weak, one wholly unsupported | 0.4375 | 0.2500 | 0.6087 | 3.0435 | 3.0 | 15.00 |
| 10 supported and 90 eligible weak | 0.3250 | 0.1000 | 0.4906 | 2.4528 | 2.5 | 12.50 |

The separation is deliberate. Weighted precision recognizes degree of misdirection, while strict precision continues to show how rarely the destinations are actually substantive.

## Adversarial cases

| Case | Arithmetic effect | Independent safeguard |
| --- | --- | --- |
| Concordance-like index: 10 supported and 90 weak mentions, `R = 1` | `Pw = .325`, strict = `.10`, base `2.4528`, rounded reliability `2.5`, 12.50/25 | Weak locators receive zero selectivity credit; systemic mention/entity/citation clutter can cap selectivity and fail a publication gate. The reliability score is not strong. |
| High locator relevance but poor recall: `Pw = .90`, `R = .25` | `F1w = .3913`, base `1.9565`, rounded `2.0`, 10.00/25 | Expected-treatment recall already depresses F1; pooled high-value recall can cap the rating at 2.0. |
| Excellent recall obtained through only weak locators: `Pw = .25`, `R = 1` | `F1w = .4`, rating `2.0`, 10.00/25; strict precision is 0 | Selectivity is zero for those locators, distributed unsupported/incidental patterns remain eligible for caps, and clutter/systematic-unsupported gates can fail. |
| Ninety-nine supported locators plus one critical fabricated locator, `R = 1` | Before caps, `Pw = .99`, base `4.9749` | The unchanged critical fabricated/nonexistent/out-of-scope cap reduces the rating to 2.0 (10.00/25), and the publication gate fails without score-based override. |

These cases show why the quarter credit cannot make a concordance-like or fabricated index publication-ready. The reliability formula is only one layer: strict precision stays visible, Editorial Selectivity still asks whether access deserved inclusion, reliability caps preserve high-consequence safeguards, and gates remain independent claim restrictions.

## Recall and rounding behavior

At `R = 1`, `Pw = 1`, `.5`, `.25`, and `0` yield weighted F1 values `1`, `2/3`, `.4`, and `0`, with unrounded ratings `5`, `3.333…`, `2`, and `0`. At `R = 0`, weighted F1 is zero regardless of precision. When `Pw + R = 0`, the defined result is zero.

The tests exercise decimal half-up values immediately below, exactly at, and immediately above each relevant half-step. They also include uninspectable evidence that changes the rounded endpoint and a separate case in which uncertainty changes the applied-cap identity; both suppress a single published number under the unchanged sufficiency rule.

## Conclusion

The values `1`, `0.5`, `0.25`, and `0` are method choices for the intended distinction: substantive support, partial path support, genuine but non-substantive presence, and false/independently invalid destination. They were not tuned against the Oxford evaluation, and no Oxford artifact is migrated by V6 implementation work.
