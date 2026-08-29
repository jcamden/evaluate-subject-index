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

Retain the four judgments as editorial facts; V6 does not create a new favorable judgment. The scored reliability layer deterministically combines judgment, treatment class, source-scope status, error codes, and structured defects:

| Combined state | V6 reliability credit | Strict substantive credit |
| --- | ---: | ---: |
| `supported` with substantive or mixed treatment | 1.00 | 1 |
| `partially_supported` with substantive or mixed treatment | 0.50 | 0 |
| indexable, inspectable `unsupported` plus `passing_mention`, `attribution_only`, `citation_only`, or `incidental_example` | 0.25 | 0 |
| all other `unsupported` | 0.00 | 0 |
| `uninspectable` | neutral bounds | excluded centrally |

The 0.25 tier distinguishes a weakly relevant destination from a wholly false one; it does not make the locator substantively valid. A validated `SCP`, `CMP`, `CON`, or `STA` failure reduces otherwise eligible weak presence to zero. Known out-of-scope, fabricated, nonexistent, or nonindexable assignments also receive zero by precedence. Preserve every applicable defect and gate consequence.

Reject contradictory combined states rather than choosing a favorable credit. A positive judgment requires indexable scope and substantive or mixed treatment. An excluded destination is known adverse evidence, not `uninspectable`. An unavailable or ambiguous destination is `uninspectable`, not a measured failure. An `unsupported` assignment whose page materially treats the subject must carry the structured scope, compound, conceptual, stance, or locator-position reason that makes the asserted path fail.

V6 continues to publish strict substantive precision separately. Historical V5 calculations retain their original strict-only dimension arithmetic and must never be reinterpreted as V6.

For chunked locator work, the frozen locator packet is the complete denominator. Preserve each packet's full heading path and judge every owned expanded assignment exactly once. Reject duplicate, missing, foreign-chunk, or path-altered assignments rather than repairing the packet. An unavailable or genuinely uninspectable owned page may receive `uninspectable`; an unresolved locator excluded during packet preparation is not silently reassigned to a worker. Parallel and sequential audits use the same four statuses and judgment meaning.

## Missing access and recall

For every essential and major benchmark subject, record:

- whether a plausible direct route exists;
- whether a valid cross-reference route exists;
- whether required distinctions and stance survive;
- which principal, supporting, and synthesis/conclusion pages are included or missed;
- whether a realistic first lookup succeeds; and
- the severity of any missing access.

Concept coverage and page-reference recall have different denominators. A concept may be represented while important treatments are missing.

Account separately for principal, supporting, and synthesis/conclusion treatments, and record realistic first-lookup and reader-task success. Every scored subject and every required reader task belongs to exactly one chunk for worker accounting. Use a valid frozen `owner_chunk_id` when supplied. Otherwise assign a subject to the chunk owning its first principal evidence page in document-page then chunk order; if it has no principal evidence, use its first non-incidental scored evidence by the same order. Assign a task to a valid frozen `owner_chunk_id` when supplied; otherwise use the owner of the first subject in its frozen `subject_ids` order. The deterministic helper, not the language model, computes and hashes this ownership plan.

Define one treatment-recall unit by unique subject ID, document page, and locator class. When the benchmark retains multiple evidence records for that unit, coalesce them without losing their evidence IDs. The records remain distinct benchmark evidence, while the page/class treatment is judged once and counted once. Require the treatment judgment to cite every coalesced benchmark evidence ID.

Missing-access review may use the complete canonical locator-audit set to determine whether another route succeeds. It must not silently reinterpret locator legitimacy. When a coverage judgment depends on a suspected locator error, record a formal dependency defect with the affected IDs, confidence, and evidence needed for adjudication while retaining the canonical locator result.

Missing-access review is benchmark-first and does not routinely reopen the source. The benchmark supplies the source-grounded concept, meaning, stance, acceptable-access, reader-task, page, class, and evidence denominator; the canonical locator set supplies already source-grounded candidate-page legitimacy. If these frozen derivatives do not support a defensible judgment, use an explicit uncertain or uninspectable result, retain the relevant evidence IDs, state what evidence is needed, and route that exception to a centralized source adjudication. Do not let source re-entry become an informal second discovery pass or a worker-level benchmark rewrite.

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

- `critical`: frozen `severity_basis` is `fabrication`, `central_reversal`, `broken_scope`, or `systemic_nonuse`, and the realistic lookup consequence is `blocks` or `misleads`;
- `major`: frozen basis is `materially_misleading` or `blocked_retrieval`, and the lookup consequence is `blocks` or `misleads`;
- `minor`: basis is `localized_repairable_friction`, a usable route remains, and the consequence is `slows`; and
- `cosmetic`: basis is `no_retrieval_consequence` and the consequence is `none`.

Count one underlying defect once and attach multiple consequences rather than inflating totals.

For V5 and V6 scoring provenance, a defect is not valid unless structured fields identify its one dimension owner and compatible code, severity and basis, retrieval consequence, defect kind, affected item IDs, affected source and/or structural sections, root-cause family, affected and applicable counts and reconstructable rates, source/structural section denominators and rates, and whether essential/major access was destroyed. All affected IDs in one defect must use one item family, and its applicable count must equal that family's frozen original denominator; a caller-declared denominator is never trusted. Bind major/failed conceptual or mechanics nodes to a same-dimension major/critical defect that names that node. Mechanical invariant defects attach to `NODE-*` IDs or the explicit `GLOBAL-STRUCTURE` item. A free-text summary cannot trigger a cap. V6 also records a locator-bound disqualifying code or structured fabricated/nonexistent/out-of-scope defect whenever it prevents weak-presence credit.

For mechanics, aggregate defects by identical `root_cause_family`. A recurrent major pattern affects at least three nodes and either at least 1% of nodes or at least two structural sections. A systematic major pattern affects at least three nodes and either at least 10% of nodes or at least 50% of relevant structural sections. Store exact counts and denominators, compare the exact integer ratios at every threshold, and retain rounded rate fields only for display/reconstruction; never select recurrence from prose.

## Uncertainty and adjudication

Every uncertain item records alternatives, evidence needed, and confidence. Adjudicate all critical, major, and uncertain items plus a frozen quality-control sample. Do not silently force an uncertain judgment to a favorable category. Preserve original and adjudicated values with timestamps and reasons.

`uninspectable` is neutral, never a zero. `not_applicable` requires a frozen genuine-inapplicability basis; candidate absence does not qualify. Full mode cannot score a required `not_measured` item. V5 and V6 assign minimum and maximum permitted credit to uninspectable evidence, reevaluate every cap at both endpoints, and publish a numeric rating only when the rounded rating and applied-cap identity are stable. V6 uses 0 and 1 as the locator-credit endpoints without placing unknown assignments in the central weighted-precision denominator.
