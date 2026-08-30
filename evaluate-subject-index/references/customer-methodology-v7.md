# How the Subject Index Evaluation works — V7

## What the evaluation measures

The method evaluates a finished subject index against the publication it is meant to serve. It first builds and independently reviews a candidate-blind source benchmark, then checks the delivered index in both directions: index to source for legitimacy and source to index for missing access. A final global review considers hierarchy, navigation, density, and mechanics.

The six quality questions and their weights remain unchanged:

| Question | Weight |
| --- | ---: |
| Does the index cover the source’s meaningful subjects? | 20 |
| Does it select useful entries rather than incidental mentions? | 15 |
| Do headings preserve concepts, relationships, and stance? | 15 |
| Do page references reliably take the reader to relevant treatment? | 25 |
| Can readers find subjects through clear headings and access routes? | 20 |
| Is the index mechanically consistent? | 5 |

## Two facts about every page reference

V7 keeps two facts separate:

1. **Page treatment:** how much relevant treatment is present at the destination.
2. **Complete-path fit:** how accurately that treatment supports the full main-heading and subheading path.

The page-treatment values are 1.00 for substantive treatment, 0.70 for mixed treatment, 0.25 for weak presence, and zero for absent treatment or an invalid destination. Complete-path fit is 1.00 for exact fit, 0.70 for material partial fit, 0.35 for a minor mismatch, 0.15 for a major mismatch, and zero for no fit.

The final locator credit is the lower value:

\[
L_j=\min(T_j,F_j).
\]

The minimum treats the axes as independent ceilings. It avoids double-counting one limitation by multiplying, such as turning mixed treatment plus partial fit into 0.49. Substantial relevant discussion can retain some credit even when a heading asserts the wrong relationship or stance, but the fit penalty remains strong. Weak presence always places a 0.25 ceiling on the locator; no relevant treatment or no path fit produces zero.

The displayed locator grade is exactly 100 times the credit. A credit of 0.35 therefore displays as grade 35. These grades are diagnostic, not additive, and are never averaged to reconstruct the dimension score. The calculation uses the complete frozen locator-credit ledger.

Editorial Selectivity remains separate. A weak mention may receive locator credit 0.25 because it takes the reader to a relevant mention, but it still earns no substantive-selectivity credit. Strict substantive precision also remains public: it reports the proportion of assessable locators judged fully supported, treating partial and unsupported judgments as incorrect.

## Page-reference Reliability

V7 averages locator credits to obtain weighted locator precision, then combines that precision with unchanged expected-treatment recall using the harmonic mean. Recall still asks whether all expected principal, supporting, and synthesis treatments were found. Existing consequence caps, uncertainty bounds, rounding rules, defined-zero rules, and publication-readiness gates remain independent and unchanged.

## Displayed locators, ranges, and atomic assignments

> A displayed locator is one delivered page reference or continuous range. A range is audited as multiple atomic page assignments but counts as one displayed locator for scanning and subdivision review.

These quantities serve different purposes:

| Quantity | Meaning | Use |
| --- | --- | --- |
| Displayed locator count | Number of delivered page-reference tokens; a range counts once | Scanning and subdivision review |
| Range span | Inclusive pages represented by one continuous range | Separate long-range review |
| Atomic assignment count | Individual path/page assignments after expanding ranges | Page-support audit, precision, recall, routing, and density |

For example, `5–12, 16–18, 86` contains three displayed locators, twelve atomic assignments, and a longest continuous range of eight pages. It is not a twelve-locator string.

More than six displayed locators triggers a locator-string architecture review. A continuous range longer than ten pages triggers a separate range review. Exactly six locators and exactly ten pages do not trigger.

Neither number proves that subdivision is needed. A long range may represent one sustained discussion, and a long list may represent one coherent subject. A scored architecture issue additionally requires structured evidence of conceptually distinct treatments, a meaningful subdivision or alternative access route, material impairment to scanning or retrieval, and a conceptual rather than merely page-based, trivial, grammatical, or empty chronological division.

This distinction follows professional guidance that treats locator strings and unusually long ranges as separate review questions, including the [American Society for Indexing checklist](https://asindexing.org/about-indexing/index-evaluation-checklist/), [University of Georgia Press indexing guidelines](https://www.ugapress.org/indexing-guidelines/), and [Society of Indexers guidance](https://www.indexers.org.uk/posts/commissioning-an-indexer-part-3/).

## Uncertainty, caps, and publication readiness

An uninspectable destination contributes neutral lower and upper endpoints rather than an invented judgment. Required unmeasured evidence blocks a full score. Caps continue to respond to high-consequence conditions such as a fabricated destination, while publication-readiness gates remain claim restrictions outside score arithmetic. A numerical credit cannot clear a failed gate.

## Score-only migration

A V6-to-V7 migration recalculates from frozen structured evidence. It does not reopen source pages, reinterpret rationale text, alter locator or missing-access judgments, or replace the historical result. It must stop if either locator axis or a delivered range grouping cannot be reconstructed without prose inference.

The migration may remove a historical architecture penalty from the active V7 projection when structured records prove that the penalty rested only on expanded atomic pages being miscounted as displayed locators and neither corrected review trigger applies. It preserves the old defect unchanged as history. Conversely, a newly exposed numerical trigger cannot invent an architecture judgment; it remains `review_required` pending a narrow supplemental review.

V7 was not tuned to reproduce any Oxford score. The Oxford-shaped locator string is a regression example used to test the counting rule, not a target result, and no Oxford evaluation artifact is migrated or modified by the methodology implementation.
