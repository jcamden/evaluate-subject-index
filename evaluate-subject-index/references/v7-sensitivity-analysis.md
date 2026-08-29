# V7 locator-utility sensitivity and adversarial analysis

This analysis uses synthetic mixtures and exact `Decimal` arithmetic. It is not fitted to a candidate or tuned to reproduce an Oxford result. The approved fit values are frozen regression expectations: 1.00, 0.70, 0.35, 0.15, and 0.

## Fit-value sensitivity

The comparison isolates fit by using ten substantive locators: four exact, two partial, two minor mismatch, one major mismatch, and one no-fit. Recall is 1, and no cap applies.

| Profile | Partial | Minor | Major | Weighted precision | Rounded reliability rating |
| --- | ---: | ---: | ---: | ---: | ---: |
| Lower-credit alternative | 0.60 | 0.25 | 0.10 | 0.580 | 3.5 |
| **Approved V7** | **0.70** | **0.35** | **0.15** | **0.625** | **4.0** |
| Higher-credit alternative | 0.80 | 0.45 | 0.25 | 0.675 | 4.0 |

The alternatives show local sensitivity without changing policy. The approved values distinguish material partial fit, repairable mismatch, and severe mismatch while preserving zero for no fit. They are not selected by optimizing a historical evaluation.

## Minimum versus multiplication

| Treatment and fit | V7 minimum | Multiplication rejected by V7 |
| --- | ---: | ---: |
| Mixed 0.70 + partial 0.70 | 0.70 | 0.49 |
| Weak 0.25 + partial 0.70 | 0.25 | 0.175 |
| Weak 0.25 + minor mismatch 0.35 | 0.25 | 0.0875 |

The minimum makes each axis an independent ceiling. Multiplication would penalize the same shared limitation twice.

## Adversarial mixtures

| Synthetic case | V7 outcome | Independent safeguard |
| --- | --- | --- |
| 10 substantive exact locators and 90 semantically fitting weak mentions | weighted precision 0.325; strict precision 0.10; reliability rating 2.5 | Weak presence remains zero for Editorial Selectivity and remains gate/cap evidence where applicable |
| Weighted precision 0.90 but expected-treatment recall 0.25 | weighted F1 0.391304…; rating 2.0 | Unchanged recall and high-value-recall caps prevent precision from hiding omissions |
| 99 exact locators plus one fabricated destination | pre-cap precision 0.99; critical cap yields rating 2.0 | Fabrication gate and cap remain independent |
| One minor wrong relationship and one major wrong stance, both on substantive pages | treatment scores remain 1; fit scores are 0.35 and 0.15; precision 0.25 | Concept/stance defects and gates remain separate |
| Exact, partial, minor-defect, and no-fit weak locators | credits 0.25, 0.25, 0.25, 0; precision 0.1875 | The weak-treatment ceiling and no-fit floor both remain visible |

## Structure boundaries

Exact integer boundary tests confirm that six displayed locators and a ten-page range do not trigger review, while seven and eleven do. Trigger status never changes an architecture grade without the four structured semantic findings. The `5–12, 16–18, 86` regression case reconstructs as three displays, twelve atomic assignments, and maximum range span eight, with neither trigger.

The Oxford-shaped entry is a regression case only. No Oxford evaluation artifact is read, migrated, changed, or used as a calibration target.
