# Standard subject-index evaluation policy v1

Apply this policy by default. Freeze a run-specific `evaluation-policy.json` before opening a candidate. Do not ask the user to design policy. Ask only about a material source ambiguity, an explicit publisher specification, or a requested deviation; record every deviation with its rationale and provenance.

## Policy application by stage

| Policy area | Source discovery and benchmark | Locator audit | Missing-access audit | Global structure audit | Deterministic validation |
| --- | --- | --- | --- | --- | --- |
| Scope compliance | Freeze indexable matter and exclusions | Flag out-of-scope support | Exclude unavailable/nonindexable matter from recall | Detect systemic scope leakage | Validate page span and mapping |
| Substantive coverage | Discover and prioritize source subjects | — | Test concepts, treatment pages, and reader tasks | Test proportional distribution | Validate denominators |
| Editorial selectivity | Record exclusions and borderline cases | Judge substantive support for every path/page pair | — | Detect clutter patterns and density mismatch | — |
| Concept and stance fidelity | Freeze meaning, distinctions, and stance | Test the complete path against the page | Test whether retrieved access preserves distinctions | Detect conflation and terminology drift | — |
| Heading/access architecture | Record acceptable access routes, not a model index | Flag false path semantics | Test plausible direct and cross-referenced access | Judge hierarchy, terminology, and direct access | Validate depth and uniqueness |
| Locator quality | Classify substantive evidence pages | Test proposed-locator precision | Test treatment-page recall | Detect systemic locator patterns | Validate atomicity, validity, order, uniqueness |
| Compound-heading scope | Record distinct concepts and common umbrellas | Require every component at every locator | Test access after necessary splits | Detect systematic improper unions | — |
| Cross-references | Record synonyms and related concepts | — | Test references used as access routes | Audit every reference and target | Resolve targets and cycles |
| Whole-index coherence | Record cross-chapter relationships | — | Identify fragmented access to benchmark concepts | Judge the complete navigation system | — |
| Mechanical validity | — | — | — | Review presentation-dependent mechanics | Validate schema and invariant rules |

The benchmark must describe source meaning and acceptable retrieval routes, not prescribe one index structure. Do not use density targets to limit source-subject discovery or benchmark size.

## Readership

Infer likely readership from the source’s title, publisher, series, paratext, genre, terminology, explanatory assumptions, and presentation. Record:

- `label`, allowing a combined value such as `scholars_and_students`;
- `basis`: `inferred` or `user_supplied`;
- `confidence`: `high`, `medium`, or `low`; and
- a concise evidence-based rationale.

Do not ask the user when the inference is reasonably clear. Ask only when confidence is low or the intended index readership materially differs from the publication’s apparent readership. Readership may affect preferred access language, alternative routes, reader tasks, and the interpretation of density. It never changes whether a locator is true or whether a heading preserves the source’s meaning and stance.

## 1. Scope compliance

Include by default:

- preparation-approved indexable content;
- substantive body, chapter, and part text;
- substantive block quotations;
- substantive notes, footnotes, and endnotes when present and inspectable;
- substantive captions and table text; and
- otherwise eligible text whose role remains unknown.

Exclude by default:

- front or back matter designated nonindexable;
- bibliographies and source lists;
- the publisher’s or another candidate index;
- contents pages, navigation lists, running furniture, and page numbers;
- proof or production material;
- graph internals and explicitly ignored regions; and
- material unavailable in the supplied source.

Handle mixed pages at the region level: index eligible content and ignore excluded portions. Do not derive entries from excluded material merely because it appears elsewhere in the PDF. Record missing or unavailable matter as a source limitation; do not treat it as an index omission unless the candidate claims access to it and the claim can be tested.

## 2. Substantive coverage

Discover and test access to:

- principal subjects and important subsidiary or localized subjects;
- significant arguments, explanations, findings, relationships, comparisons, distinctions, methods, causes, consequences, and applications;
- important definitions, classifications, variants, chronological distinctions, competing interpretations, and evidentiary findings;
- synthesis and conclusion-level treatment; and
- concepts expressed through varying terminology, including important one-off treatments.

Assign priority from intellectual significance, explanatory role, authorial emphasis, and realistic reader need—not frequency, chapter equality, or word count. Preserve cross-chapter concepts during whole-source synthesis.

Classify an independently useful significant subsidiary or localized subject as `major` even when confined to one passage or chapter. Reserve `optional` for defensible supplemental access whose absence would not materially reduce the index's usefulness; do not use `optional` merely as a synonym for localized.

## 3. Editorial selectivity

Require each locator-bearing path to represent substantive treatment. Exclude by default:

- passing mentions;
- attribution-only scholars and citation-only names;
- incidental people, organizations, places, works, corpora, or documents;
- isolated examples, quotations, cases, experiments, forms, or evidence items without sustained analytical or independent retrieval value; and
- redundant access points and trivial subdivisions.

Recurrence alone does not make material indexable. Prefer indexing evidence through the argument, finding, pattern, or interpretation it establishes. Record legitimate exceptions when an entity or example is sustained, analytically important, or independently useful.

## 4. Conceptual and stance fidelity

Require every heading to describe the source accurately. Preserve distinctions among supported, proposed, possible, questioned, qualified, rejected, inconclusive, and unattested claims. Do not present a reported position as the author’s conclusion.

Keep materially different subjects, senses, scopes, periods, corpora, explanations, and findings distinguishable. Do not combine subjects merely because they share words or locators. Do not let a broad heading conceal materially different treatments. Preserve accurate specialist notation, transliteration, diacritics, capitalization, and proper names.

## 5. Heading and access architecture

Require concise, specific, reader-oriented, independently searchable headings. Use preferred terminology consistently; consolidate true synonyms and redundant near-duplicates; distinguish homonyms and materially different senses.

Allow one main heading and at most one subheading. Require subheadings to express meaningful aspects, findings, distinctions, or reader questions. Subdivide a major subject when it is conceptually heterogeneous or unwieldy, but not merely because treatment spans pages. Reject arbitrary, page-based, section-based, grammatical, and trivial subdivisions.

Do not bury important concepts beneath vague or unpredictable umbrellas. Do not use the publication’s central subject as a catch-all. Permit a locator-bearing parent only for substantive general treatment not assignable more precisely; do not let it merely aggregate or duplicate subheadings. Give plausible alternative terminology useful direct or cross-referenced access.

## 6. Locator quality

Treat one complete-heading-path and one atomic source page as the judgment unit. Require the page to substantively support the complete path. Support for a parent does not support its child; support for one component does not support an enumerated or compound path.

Exclude incidental mentions, citations, examples, and nominally encompassing statements. Include all principal substantive treatment plus relevant continuation, comparison, synthesis, and conclusion pages within the path’s exact semantic scope. Do not omit supported pages to shorten a list or retain unsupported pages to increase apparent completeness. Evaluate every page in a displayed span independently.

Require positive atomic page labels or page numbers after normalization, never unexpanded ranges. Locators must resolve to indexable source pages, be unique, and follow publication order. Never fabricate a locator. Give every final locator exact source evidence or mark it explicitly unresolved.

## 7. Compound-heading scope

Require every locator to support every component asserted by a compound or enumerated heading. Do not union component-specific locators under a compound formulation. If all pages support a common concept but not every named component, use the narrowest useful common umbrella. Split materially distinct treatments when doing so improves access, while preserving stance, chronology, corpus, finding, and explanation distinctions. Do not generalize into vagueness merely to retain weak locators.

## 8. Cross-references

For `see`:

- require a genuine synonym, variant, alternative name, formulation, or useful inversion that is a plausible lookup term;
- require the source to have no locators or locator-bearing descendants;
- do not replace a warranted substantive entry; and
- target access at least as precise and useful as the source.

For `see also`:

- require the source and target to be distinct, independently indexed subjects; and
- require the relationship to materially improve navigation.

For every reference, require an exact resolvable target. Reject self-references, unresolved targets, circular references, chained `see` references, trivial or misleading relationships, gratuitous reciprocity, and excessive reference webs. Do not use references to conceal fragmented organization.

## 9. Whole-index coherence

Do not fragment one substantive reader concept among competing headings or organizational schemes. Use coherent, reasonably parallel structures for parallel treatment and consistent terminology, capitalization, hierarchy, and sibling wording. Keep independently useful concepts findable without duplicating substantially identical locator sets.

Balance useful specificity with coherent grouping. Do not overrepresent thematic areas merely because they contain repeated terminology, names, or examples. Require the index to work as one publication-level navigation system rather than concatenated chapter indexes.

## 10. Mechanical validity

Require every page-bearing entry to have a unique one- or two-level path and at least one valid locator. Merge duplicate paths. Require locator lists to contain no duplicates and follow publication order. Permit only `see` and `see also`; deduplicate reference records and targets. Reject empty entries and invalid references. Require all records to conform to the output schema.

This is an evaluation standard, not a normalization instruction. Candidate preparation must preserve duplicate, empty, malformed, third-level, or deeper delivered structures and mixed locator/reference records in candidate-index-v2. The structure audit then records the applicable defects and gates. Never make a candidate appear compliant by flattening, merging, repairing, or discarding delivered content during normalization.

## Density calibration

Measure indexable source words for each chapter or approved intellectual unit. For each unit, calculate:

| Metric | Calibration target | Target band | Broad tolerance band | Weight |
| --- | ---: | ---: | ---: | ---: |
| Locator-bearing complete heading paths per 1,000 source words | 8 | 6–10 | 4–12 | 50% |
| Expanded locator occurrences per 1,000 source words | 20 | 15–25 | 10–30 | 50% |

A path with locators in more than one chapter counts once in each chapter where it has at least one locator. An occurrence is one normalized atomic path/page assignment. Use only indexable source words in the denominator.

Base chapter rates on assignments that resolve to an in-scope chapter owner. Report unresolved, ambiguous, unavailable, and out-of-scope assignments separately; never silently drop them. Judge those assignments under mapping, scope, grounding, and shipping-gate rules rather than forcing them into a chapter density value.

Treat the exact targets and target bands as calibration points, not quotas, minimums, hard ceilings, or generation instructions. For a 10,000-word unit, report:

> At this unit’s length, a normally dense result would contain approximately 80 locator-bearing heading paths and 200 locator occurrences. Treat these figures as calibration points, not quotas, minimums, or hard ceilings. Deviate when the significance and distribution of the material warrant it. Do not retain weak access merely to meet the scale, and do not remove supported locators from a retained heading merely to stay within it.

Assign metric fit ratings as follows:

- within target band: 5;
- within broad tolerance band but outside target band: 4;
- outside broad tolerance by up to 25% of the nearest boundary: 3;
- outside by more than 25% and up to 50%: 2;
- outside by more than 50% and up to 100%: 1;
- outside by more than 100%: 0.

Average the two metric ratings per chapter, then compute the source-word-weighted mean across chapters and round only the final result to the nearest 0.5. Record every chapter measurement and outlier. Treat extremely short units as diagnostic or aggregate them with a declared neighboring unit when their rates are unstable.

Density contributes no more than five of 100 points through Editorial Selectivity. Do not also penalize coverage or navigation solely because an index is shorter or longer than calibration. Score independently demonstrated omissions, clutter, fragmentation, or underdivision in their proper dimensions.

Every public report must disclose the two targets, both bands, chapter-level measurement basis, observed distribution, fit rating, and five-point maximum contribution. Do not market the targets as universal professional requirements; identify them as this evaluation framework’s standardized calibration.

## Shipping gates

Do not describe a finished index as publication-ready when any applicable gate fails:

- a fabricated, nonexistent, or out-of-scope locator;
- a systematic pattern of incidental or unsupported locators;
- a central subject or conclusion materially omitted;
- a heading that reverses or seriously misrepresents source stance;
- a compound heading whose locators support only separate components;
- a `see` source that replaces a warranted substantive entry;
- an unresolved, self-referential, circular, or chained cross-reference;
- any third-level heading;
- systematic named-entity, example, or citation clutter;
- critical or major unresolved grounding; or
- more than 1% of in-scope locator assignments left uninspectable, unless a frozen source limitation establishes a different disclosed tolerance.

A failed gate limits the publication-readiness claim; it does not silently rewrite the arithmetic score. Record the gate ID, status, evidence IDs, applicability, and rationale.

## Defect ownership

Record one underlying defect once. Attach its consequences to every affected metric without duplicating the defect count. Use `SCP` for scope, `COV` for coverage, `SEL` for selectivity, `CON` for conceptual fidelity, `STA` for stance, `LOC_POS` and `LOC_NEG` for locator precision and recall, `CMP` for compound scope, `HED` and `SUB` for heading architecture, `XRF` for references, `DEN` for density, and `MEC` for mechanics.
