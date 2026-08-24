# Judgment policy

Apply [standard-policy.md](standard-policy.md). This file defines judgment units and evidence handling; the standard policy defines the substantive rules and stage ownership.

Layout extraction and normalization confidence are fidelity metadata, not editorial judgments. Candidate-preparation QA may decide whether a line, boundary, continuation, or transcription reproduces the delivered candidate; it must not decide whether the resulting heading, locator, hierarchy, or reference is good. Those judgments remain owned by the candidate-audit stages after a final benchmark lock.

## Source scope

Inspect only matter frozen as indexable. Treat mixed pages at the region level. Record unavailable notes, missing pages, illegible regions, and role ambiguity as source limitations. Do not put excluded or unavailable matter in coverage denominators. A candidate locator into excluded matter is a scope defect when its mapping is known; a locator into unavailable matter is `uninspectable`, not automatically wrong.

## Substantively treated subjects

A subject is substantively treated when the source does at least one of the following:

- explains, defines, analyzes, narrates, compares, evaluates, or draws a conclusion about it;
- uses it as a material cause, consequence, relationship, controversy, or organizing idea;
- sustains it across a passage or makes it independently useful to the intended reader; or
- relies on it in a synthesis or conclusion.

Mere word occurrence is insufficient. Exclude by default passing mentions, attribution-only names, bibliographic citations, isolated examples, incidental places, and evidence items without independent retrieval value. A short passage may still be major if it contains a decisive distinction or conclusion.

## Source-subject records

Each essential or major record must state:

- stable concept ID and preferred descriptive label;
- priority: `essential`, `major`, `optional`, or `exclude_by_default`;
- plain-language meaning;
- stance or degree of commitment that headings must preserve;
- parent, related, contrast, cause, consequence, and synonym relationships where present;
- acceptable access terminology and structural alternatives;
- evidence pages classified `principal`, `supporting`, `synthesis_or_conclusion`, or `incidental`;
- anticipated reader lookup routes; and
- uncertainty and adjudication status.

Do not make the frozen benchmark a model index. It is a graph of source meaning and acceptable retrieval routes; more than one index structure can satisfy it.

Record indexable source-word counts by approved chapter/unit for later density measurement. Do not use density calibration to cap, pad, or prioritize the benchmark.

## Locator legitimacy

The unit is one expanded locator assignment plus its complete heading path. Judge:

- `supported`: the owned page substantively supports the exact path and required stance;
- `partially_supported`: the topic is materially present, but the path is too broad, too narrow, vague, or only partly sustained;
- `unsupported`: absent, incidental, attribution-only, example-only, wrong sense, wrong relation, or wrong stance;
- `uninspectable`: the page or mapping cannot be evaluated reliably.

Do not mark a child locator supported because only its parent appears. Do not mark an entire page range supported after checking only its first page. Report `uninspectable` outside the precision denominator unless the frozen uncertainty policy says otherwise.

For compound or enumerated paths, require every named component on every assigned page. When components are supported only on different pages, use `unsupported` with `CMP`; do not average the components into partial support. Use `partially_supported` when the page materially supports the asserted subject but the path is genuinely too broad, narrow, vague, or qualified—not as a compromise for an improper union.

For a binary precision measure, count `supported` as correct, `unsupported` as incorrect, and publish `partially_supported` separately. If a project elects fractional credit, freeze the fraction before candidate review and disclose it.

## Missing access and recall

For every essential and major benchmark subject, record:

- whether a plausible direct route exists;
- whether a valid cross-reference route exists;
- whether required distinctions and stance survive;
- which principal, supporting, and synthesis/conclusion pages are included or missed;
- whether a realistic first lookup succeeds; and
- the severity of any missing access.

Concept coverage and page-reference recall have different denominators. A concept may be represented while important treatments are missing.

## Global structure

Use the complete locator ledger as evidence, then judge:

- truth and utility of every parent-child relationship;
- parallelism of sibling subheadings;
- independently searchable concepts buried under unpredictable parents;
- long undivided locator lists;
- arbitrary one-page subdivisions and excessive fragmentation;
- inconsistent preferred terminology and redundant near-synonyms;
- `see` and `see also` semantics, resolvable targets, cycles, and chains;
- alphabetical filing, names, range order, duplication, and formatting; and
- distribution of access across chapters and major subject areas.

Audit every `see` and `see also` record. Verify source semantics, source locator status, target existence and precision, cycles, chains, reciprocity, and whether the reference substitutes for warranted substantive access. Run deterministic graph checks first and editorial utility checks second.

## Severity and error codes

Use: `SCP`, `COV`, `SEL`, `CON`, `STA`, `LOC_POS`, `LOC_NEG`, `CMP`, `HED`, `SUB`, `XRF`, `DEN`, and `MEC`.

- `critical`: fabrication, central reversal, broken scope, or systemic failure preventing reliable use;
- `major`: materially harms retrieval or misrepresents important treatment;
- `minor`: localized, repairable retrieval defect;
- `cosmetic`: no meaningful retrieval impact.

Count one underlying defect once and attach multiple consequences rather than inflating totals.

## Uncertainty and adjudication

Every uncertain item records alternatives, evidence needed, and confidence. Adjudicate all critical, major, and uncertain items plus a frozen quality-control sample. Do not silently force an uncertain judgment to a favorable category. Preserve original and adjudicated values with timestamps and reasons.
