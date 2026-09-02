# Locator utility — V7

## Two axes

Page treatment measures how much relevant treatment is present at the destination. Complete-path fit measures whether the full heading path accurately identifies that treatment. Derive both from current structured audit fields and use the lower score.

| Axis category | Credit |
| --- | ---: |
| substantive / exact | 1.00 |
| mixed / material partial | 0.70 |
| weak presence | 0.25 treatment ceiling |
| minor fit mismatch | 0.35 fit ceiling |
| major fit mismatch | 0.15 fit ceiling |
| absent, invalid destination, or no fit | 0.00 |

Uninspectable evidence produces a neutral uncertainty bound. A required `not_measured` record prevents a full score.

## Validation

Current structured fields must agree on judgment, treatment, scope, error codes, severity, path identity, and applicable defects. A bare consequence code such as `LOC_POS` cannot establish a semantic fit cause. Unknown, incomplete, identity-inconsistent, or contradictory states fail validation. Prose is explanatory only.

## Reporting

Each locator reports treatment category and score, fit category and score, the minimum combined credit, diagnostic grade, rule IDs, disposition, and uncertainty endpoints. Weighted locator precision uses combined credit; strict substantive precision remains a separate public diagnostic.
