# Judgment policy — V7 additions

This document supplements the unchanged V6 judgment policy. V7 does not reopen benchmark, locator-support, missing-access, treatment, hierarchy, density, or gate judgments.

## Freeze first, calculate second

The evaluator continues to freeze one combined locator state containing `judgment`, `treatment_class`, `source_scope_status`, `error_codes`, `severity`, and any applicable structured defects. V7 calculation then derives page treatment and complete-path fit deterministically. Rationale and evidence-summary prose are display-only.

For current work, `locator-audit-v2` retains two explanation fields from the same source inspection. Every measured locator requires one locator-specific, public-safe `evidence_summary` describing what the page contains and why the treatment class applies. That summary is the primary page-treatment explanation; no second bespoke treatment paragraph is required. A separate concise `fit_rationale` is required when treatment and fit scores differ, fit is below 100, structured fit classifiers conflict, or a supplemental decision supplies fit. A routine supported, substantive, exact-fit record may omit authored fit prose; the projection then explains fit mechanically from the structured category and rule. Prose never repairs, selects, or changes a structured category.

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

At the immutable `structure-audit-v3` history boundary only, a missing `defect_kind` may be tolerated through `F-COMPAT-LEGACY-CODE-SEVERITY-ONLY-V1`. The code, severity, locator binding, scope, and all other structured fields must be valid. Do not invent a kind. Cosmetic evidence, bare `LOC_POS`, `MEC`, `SEL`, and unknown or missing fields cannot complete the mapping.

When otherwise valid historical structured classifiers share the exact evaluation, candidate, audit mode, locator, and normalized complete-path identity but imply different fit categories, apply `F-COMPAT-LEGACY-FIT-CONFLICT-TO-SUPPLEMENT-V1` only if the disagreement is confined to that derived fit category. Record `legacy_structured_fit_classification_conflict_requires_adjudication`, preserve each classifier's structured provenance, and request the exact-scope locator-fit supplement. Do not choose by precedence, average the categories, edit history, or use rationale or evidence-summary prose. Identity drift, malformed/unknown fields, incompatible locator/path assignments, contradictions outside fit, and artifact-integrity failures remain invalid and ineligible.

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

A supplemental locator-fit artifact likewise does not make a judgment. A separately authorized process makes the semantic decision; new `subject-index-v7-locator-fit-supplement-v2` artifacts transport the selected existing category, plus public-safe explanatory rationale or a validated rationale-ledger reference, with exact artifact, unresolved-set, evidence, and authorization bindings. Historical V1 artifacts remain compatibility-readable. For a conflict-routed locator, the decision resolves the prospective V7 complete-path-fit axis without identifying a historically “correct” classifier. The score-only migration itself never inspects source pages or prose and cannot alter treatment, judgment, scope, codes, severity, defects, evidence, gates, or another dimension.

## Authored, structured, projected, and restricted fields

- Authored public evidence is the locator-specific `evidence_summary` and, only when required, `fit_rationale` or supplemental rationale.
- Structured scoring inputs are judgment, treatment class, scope/inspectability, approved codes and defects, severity, and the authorized fit category. These alone select categories and credit.
- Explanatory projection fields copy authored evidence and structured category/score/rule IDs into item and web artifacts; routine fit text may be mechanically generated from the structured category and rule.
- Restricted evidence includes source excerpts, raw or verbatim text, page images, coordinates, local paths, private recovery material, and secrets. It remains in authorized private evidence stores and must not be copied into public explanations.
