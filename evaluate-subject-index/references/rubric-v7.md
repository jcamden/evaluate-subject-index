# Subject Index Evaluation technical rubric — V7

## Current identities

- rubric: `subject-index-rubric-v7`
- calculation profile: `subject-index-dimension-calculation-v3`
- calculation artifact: `subject-index-dimension-calculations-v4`
- result: `subject-index-evaluation-result-v9`
- item policy: `subject-index-item-grading-v3`
- item artifact: `subject-index-item-assessments-v5`
- web report: `subject-index-web-report-v7`
- locator audit: `locator-audit-v2`

Runtime commands accept these current identities only. Older schemas remain in the repository temporarily while a TypeScript migration is considered; they are not a supported workflow.

## Locator utility

For each assessable locator, derive page treatment and complete-path fit independently:

\[
T_j=\text{page-treatment score},\qquad F_j=\text{complete-path-fit score}
\]

Then use:

\[
L_j=\min(T_j,F_j),\qquad G_j=100L_j
\]

| Treatment | Score |
| --- | ---: |
| substantive | 1.00 |
| mixed | 0.70 |
| passing mention, attribution, citation, or incidental example | 0.25 |
| absent or invalid destination | 0.00 |
| uninspectable | neutral 0–1 bound |

| Complete-path fit | Score |
| --- | ---: |
| exact | 1.00 |
| material partial | 0.70 |
| minor mismatch | 0.35 |
| major mismatch | 0.15 |
| no fit | 0.00 |
| uninspectable | neutral 0–1 bound |

Structured judgments, treatment classes, scope, error codes, and current defects determine these values. Explanation prose is never a scoring input. Incomplete or contradictory structured states fail validation.

## Page-reference Reliability

For assessable locators:

\[
P_W=\frac{\sum_j L_j}{N_{\mathrm{assessable}}}
\]

Expected-treatment recall is:

\[
R_T=\frac{\mathrm{found}}{\mathrm{found}+\mathrm{missed}}
\]

The weighted harmonic mean and base rating are:

\[
F_{1W}=\frac{2P_WR_T}{P_W+R_T},\qquad \text{base rating}=5F_{1W}
\]

Strict substantive precision remains a separately reported diagnostic. Existing caps, uncertainty bounds, rounding, and gates apply after the base calculation.

## Structure quantities

A displayed locator is one delivered page reference or continuous range. A range may expand to several atomic page assignments but counts once for locator-string review.

| Quantity | Use |
| --- | --- |
| `displayed_locator_count` | scanning and subdivision review |
| inclusive range span | long-continuous-range review |
| `atomic_assignment_count` | locator auditing, precision, recall, and routing |

Review is triggered by more than six displayed locators or a continuous range longer than ten pages. A trigger requests semantic review; it does not itself create a defect. A scored architecture defect additionally requires structured evidence of conceptually distinct treatments, a useful alternative organization, and material retrieval harm.

## Provenance

Calculation rows retain the structured inputs, derived categories, rule IDs, scores, disposition, and uncertainty needed to explain the result. Hashes are stable content labels for joining records and detecting accidental mix-ups; they are not tamper proofs or resume gates.
