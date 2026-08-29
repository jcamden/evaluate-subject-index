# Judgment policy — V7 additions

This document supplements the unchanged V6 judgment policy. V7 does not reopen benchmark, locator-support, missing-access, treatment, hierarchy, density, or gate judgments.

## Freeze first, calculate second

The evaluator continues to freeze one combined locator state containing `judgment`, `treatment_class`, `source_scope_status`, `error_codes`, `severity`, and any applicable structured defects. V7 calculation then derives page treatment and complete-path fit deterministically. Rationale and evidence-summary prose are display-only.

Valid `partially_supported` states continue to permit substantive, mixed, or weak-presence treatment. The fit score is 0.70. The treatment score remains whatever the frozen treatment class establishes; the combined credit is the lower score.

For historically `unsupported` weak presence, exact fit is allowed only when the exhaustive structured state proves that insufficient treatment/selectivity is the sole limitation. A bare retrieval-consequence code, an unclassified defect, or missing severity is not proof and fails closed.

## Error and defect routing

| Structured evidence | V7 path-fit use |
| --- | --- |
| `SEL` | Treatment/selectivity-only; never an independent path mismatch |
| `SCP`, `CON`, `STA`, `CMP`, `HED`, `SUB` | Fit-relevant when validly attached to the locator |
| `LOC_POS` | Retrieval consequence only; ambiguous if it is the sole asserted basis |
| `MEC` | Fit-neutral |
| `COV`, `LOC_NEG`, `XRF`, `DEN` | Wrong ledger family for locator fit; reject |
| fabrication, nonexistence, out-of-scope, or scope-failure destination kinds | Invalid destination and no fit |
| exact no-fit root-cause families | No fit |

Direct codes and applicable structured defects are considered together. The strongest validated fit severity controls an `unsupported` mismatch. Minor maps to 0.35, major to 0.15, and critical/no-fit evidence to zero. Contradictory positive judgments fail validation.

## Structure review judgment

Do not describe expanded pages as “undivided locators.” Preserve displayed locator, range-span, and atomic-assignment quantities separately.

A long-string or long-range trigger opens a review; it does not answer the review. Record one `v7_architecture_review_decisions` row only after assessing:

- conceptual heterogeneity;
- availability of meaningful subheadings or access routes;
- material scanning/retrieval impairment; and
- whether the proposed division is conceptual and nontrivial.

`defect_confirmed` requires all four booleans true and one or more structured defect IDs. `reviewed_no_defect` requires no defect IDs. An unreviewed triggered case remains `review_required`; it cannot be silently passed or failed.

A long range may be a faithful representation of one sustained discussion. A long displayed list may still represent one coherent subject. Chronology is useful only when it expresses a meaningful conceptual distinction; page-number groupings alone are not subheadings.

## Supplemental review during migration

A supplemental architecture review is narrowly scoped to the triggered path. It may inspect only the frozen structured architecture evidence authorized for that review. It must not reopen source pages, locator support, missing access, or unrelated structure judgments. If semantic evidence is not already frozen and the migration is score-only, stop and request the supplemental determination rather than infer from prose.
