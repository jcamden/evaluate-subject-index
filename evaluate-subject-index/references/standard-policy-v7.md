# Built-in standard policy — V7

V7 retains every V6 scope, content, benchmark, locator, cross-reference, density, uncertainty, cap, and publication-readiness rule. The only policy changes are the two-axis locator-utility mapping and the corrected architecture-review counting unit.

## Locator utility

Page treatment and complete-path fit are separate facts. Derive both exclusively from frozen structured fields, then use the lower score:

\[
L_j=\min(T_j,F_j),\qquad G_j=100L_j.
\]

The treatment ceilings are 1.00 substantive, 0.70 mixed, 0.25 weak presence, and zero for absent or invalid destinations. Fit ceilings are 1.00 exact, 0.70 material partial, 0.35 minor mismatch, 0.15 major mismatch, and zero for no fit. Uninspectable locators enter neutral bounds. Required `not_measured` blocks full scoring.

Weak presence never exceeds 0.25, even with exact or partial fit. No treatment or no path fit produces zero. Do not multiply the axes. Do not inspect rationale, evidence summaries, headings as prose, or other free text to obtain a more favorable mapping.

`LOC_POS` records a reliability consequence, not a semantic fit cause. Historical missing-`defect_kind` compatibility is limited to valid `structure-audit-v3` code/severity evidence and never invents a modern defect kind. Convergent classifiers remain deterministic. If individually valid classifiers sharing one exact identity imply different categories and disagree only on derived fit, route the locator under `F-COMPAT-LEGACY-FIT-CONFLICT-TO-SUPPLEMENT-V1` with reason `legacy_structured_fit_classification_conflict_requires_adjudication`. Give no classifier precedence and preserve all history. Ambiguous, cosmetic, neutral, identity-invalid, malformed, prose-dependent, or more broadly contradictory evidence fails closed under the existing invalid/unresolved boundary.

Editorial Selectivity is separate: its existing substantive/mixed/weak-presence credits do not change. Strict substantive precision remains public. Caps and gates remain independent.

## Locator strings, ranges, and assignments

> A displayed locator is one delivered page reference or continuous range. A range is audited as multiple atomic page assignments but counts as one displayed locator for scanning and subdivision review.

For every locator-bearing complete path preserve:

- delivered `DISPLAY-*` identities and `displayed_locator_count`;
- each displayed locator’s singleton/range/other kind;
- each `RANGE-*` identity, endpoints, expanded `LOC-*` ownership, and inclusive span;
- `maximum_range_span`; and
- all expanded locator identities and `atomic_assignment_count`.

Use displayed locators—not atomic assignments—for locator-string review. Use atomic assignments for support auditing, precision, recall, chapter routing, and the unchanged density calculations.

## Frozen review triggers

> More than six displayed locators or a continuous range longer than ten pages triggers architecture review; neither condition alone proves that subdivision is warranted.

- `displayed_locator_count > 6`: long displayed-locator-string review.
- `inclusive_range_span > 10`: separate long-continuous-range review.

Exactly six and exactly ten do not trigger. Integer comparisons are exact.

The professional basis is documented in the [ASI Index Evaluation Checklist](https://asindexing.org/about-indexing/index-evaluation-checklist/), [University of Georgia Press indexing guidelines](https://www.ugapress.org/indexing-guidelines/), and [Society of Indexers evaluation guidance](https://www.indexers.org.uk/posts/commissioning-an-indexer-part-3/). These sources distinguish locator strings from extensive spans; V7 freezes the operational boundaries above for reproducibility.

## Architecture judgment

A numeric trigger is review-only. A scored `minor_issues` or worse architecture judgment additionally requires structured evidence that:

1. destinations cover conceptually distinguishable treatments;
2. meaningful subheadings or alternative access routes can represent those distinctions;
3. the undifferentiated presentation materially impairs scanning or retrieval; and
4. the proposal is conceptual rather than merely page-based, chronological without conceptual value, grammatical, or trivial.

The structure audit must record these booleans, evidence IDs, and defect IDs. Prose may explain an already structured decision but cannot create it.

## Migration policy

V6-to-V7 migration never reopens or reinterprets evidence. Exact frozen normalized-candidate and inventory grouping is required. If range ownership or span cannot be reconstructed from structured fields, migration stops.

A false-positive historical penalty may be removed only when its exact structured root-cause family states that atomic assignments were used as the displayed-locator threshold, the atomic count exceeded six, both corrected triggers are false, and no independent architecture basis remains. History is not edited.

A newly exposed trigger without a frozen structured semantic determination is `review_required`. Full scoring stops or suppresses the affected active score pending a narrowly scoped supplemental architecture review. No new defect is created from a threshold alone.

An unresolved complete-path-fit set similarly blocks full migration. A hash-bound `subject-index-v7-locator-fit-supplement-v1` may carry separately authorized decisions for every and only that set. It supplies category names only; the calculator derives frozen `F`, `L=min(T,F)`, and grade values. Conflict adjudication resolves the prospective V7 fit axis without declaring a historical classifier correct. Supplemental decisions are per-view, applied in memory, and cannot modify historical evidence or non-fit state. Invalid states are excluded from the set and remain ineligible.
