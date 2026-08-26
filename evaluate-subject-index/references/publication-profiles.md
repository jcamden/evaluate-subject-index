# Publication profiles

The frozen evaluation state selects one public-artifact policy at `configuration.publication_profile`.

| Value | Worker pull request contains | Canonical audit visibility |
|---|---|---|
| `aggregate_only` | One aggregate count report | Private |
| `public_evaluation_artifacts` | One exact validated canonical audit | Public |

The default is `aggregate_only`. A v4 state that predates this field is interpreted as `aggregate_only`; do not infer public authorization from a public repository alone. Set the profile at initialization with `state_cli.py init --publication-profile ...`. Changing it after candidate-audit workers have started requires a deliberate migration and revalidation of every affected receipt, recovery bundle, public artifact, and manifest record.

When already-integrated workers have immutable `aggregate_only` pull-request evidence, do not rewrite those receipts or pretend the later canonical-audit publication occurred on the original worker branch. Preserve the legacy receipt, aggregate report, open/merge evidence, and recovery archive. Normalize the canonical audit through the strict public allowlist, publish it at the deterministic `candidate/...` path, and register one `candidate-audit-publication-migration-v1` record per affected chunk. The migration record must bind the legacy receipt/private/report hashes to the new canonical public bytes and publication commit, state that semantic judgment fields were preserved, and confirm that the legacy private bytes remain in recovery. Coordinators accept this mixed historical provenance only for the one-way `aggregate_only` to `public_evaluation_artifacts` transition.

Before rendering locator-worker prompts, hash-verify the referenced checkpoint and require it to contain an explicit profile identical to the prompt pack. Prompt text never overrides an omitted checkpoint field. For a user-authorized legacy checkpoint whose candidate-audit stages have not started, use `bundle_cli.py migrate-publication-profile` with explicit source and target profiles, validate the migrated bundle, and update the prompt pack to its new SHA-256. The helper refuses in-place semantic migration once audit artifacts or downstream judgment-stage progress are present.

## Deterministic worker paths

For `aggregate_only`:

```text
validation/locator-audit-worker.<chunk-id>.json
validation/missing-access-audit-worker.<chunk-id>.json
```

For `public_evaluation_artifacts`:

```text
candidate/locator-audits/locator-audit.<chunk-id>.v1.json
candidate/missing-access-audits/missing-access-audit.<chunk-id>.v1.json
```

Each worker pull request still changes exactly one file. Branch naming, one-commit ancestry, immutable-base binding, GitHub-observed evidence, private recovery, coordinator preflight, and merge evidence are unchanged.

The established receipt and binding fields named `public_report_path`, `public_projection`, and `public_report` are retained across locator receipt v1 and benchmark-first missing-access receipt v2. Under `public_evaluation_artifacts`, they bind the public canonical audit rather than an aggregate report. The path and bytes determine the profile unambiguously, and coordinator validation cross-checks that inferred profile against the frozen state.

## Public canonical locator-audit contract

The published bytes are the exact validated `locator-audit-v1` worker artifact. No separate projection or redacted copy is created. Publication adds a strict allowlist on top of the substantive audit validator:

- top level: `schema_version`, `evaluation_id`, optional `candidate_id`, `candidate_sha256`, `chunk_id`, `provenance`, `expected_locator_ids`, `judgments`, and `completion`;
- each judgment: `locator_id`, `path_id`, `complete_heading_path`, `document_page`, `source_page_label`, `source_scope_status`, `treatment_class`, `judgment`, `evidence_summary`, `evidence_ids`, `confidence`, `error_codes`, and `severity`;
- completion: exactly `expected`, `judged`, `unique`, and `complete`;
- provenance: exactly the source, benchmark, benchmark-lock, policy, page-map, chunk-manifest, normalized-candidate, item-inventory, and locator-packet hashes required by the parallel worker.

This is the per-locator linkage used later by item grading: `locator_id` is the stable join key, `path_id` links it to the complete heading path, and `judgment`, `severity`, `error_codes`, `confidence`, and `evidence_summary` supply the locator-level diagnostic factors.

## Public canonical missing-access contract

The published bytes are the exact validated `missing-access-audit-v1` worker artifact. The strict publication allowlist accepts only:

- frozen identities, exact expected subject/task/treatment IDs, and exact completion records;
- subject judgments and their access, coverage, stance, path, page, recall, missing-route, missed-treatment, uncertainty, confidence, evidence-ID, error-code, and severity fields;
- reader-task results and treatment judgments;
- explicitly structured locator-audit dependency defects.

The artifact remains source-grounded through the frozen benchmark and source SHA-256 lineage, but routine missing-access workers do not receive or inspect source PDF, chunk, or sidecar bytes. The ownership-plan hash binds the benchmark-first evidence mode, the unique subject/page/class treatment identity rule, and exception-only source adjudication.

Unknown fields are rejected. Nested route, treatment-recall, uncertainty, completion, and dependency-defect records also have exact key allowlists.

## Safety boundary

Both public modes continue to exclude source PDFs, PDF chunks, extracted source text, raw quotations, coordinates, absolute paths, Library identifiers, credentials, receipts, recovery archives, worker state, and canonical control files. Public canonical audits additionally reject unknown fields, forbidden raw/verbatim/quote fields, secret-like strings, local paths, and strings longer than 2,000 characters. Evidence summaries must remain concise paraphrases rather than source quotations.

The worker preserves a private recovery copy even when the canonical audit is public. In public mode, the receipt must bind the public artifact hash to the private audit hash exactly; the coordinator recomputes substantive validation from frozen inputs and requires byte identity before integration.

For missing-access audits only, this byte identity also permits a guarded recovery from an agent-side storage-transfer failure. When the original worker receipt or ZIP cannot be materialized, `reconstruct-public-handoff` may treat the exact public canonical audit as the audit source, rerun every frozen-identity, ownership, denominator, schema, safety, Git blob, and proposal gate, and generate a new private coordinator-labeled handoff. The record must explicitly disclose that the original worker bytes were unavailable. This is not permitted in `aggregate_only` and does not relax preflight or integration.

## Downstream public artifacts

Under `public_evaluation_artifacts`, register the canonical locator and missing-access audits as `public`. The item inventory, structure audit, item assessments, final evaluation result, and web-report JSON may also be published after their own schema and safety validation. Keep normalized candidate layout evidence, source evidence stores, receipts, GitHub observation files, recovery data, and restricted documents private or restricted.

The profile does not change scoring. `item_grade_cli.py` still joins canonical audits to stable locator, path, node, cross-reference, and benchmark-subject IDs, then derives the per-item grades and display factors used for semantic color coding and accessible popovers.
