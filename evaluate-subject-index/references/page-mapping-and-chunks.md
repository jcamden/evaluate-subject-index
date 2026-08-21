# Page-label mapping and chunk formats

## Coordinate systems

Keep these coordinates separate:

- `document_page`: a one-based integer ordinal in the supplied PDF. Document page 1 is the first PDF page.
- `source_page_label`: the visible or logical label used by the book and its index. Always store it as a string, such as `"xiv"`, `"1"`, `"A-12"`, or `"Plate 3"`.
- `chunk_pdf_page`: a one-based integer in a derived chunk PDF. A sidecar map must resolve it back to `document_page`.

Never call all three simply `page`. Never infer a global arithmetic offset when the source contains front matter, inserted plates, duplicate labels, or unnumbered pages.

## Preferred user input

JSON is canonical because it preserves strings and exceptional labels. CSV or a Markdown table is acceptable for user entry, but convert it to the same JSON structure and ask the user to approve it before freezing.

### Compact page-map input

Use sequential segments when labels advance predictably:

```json
{
  "schema_version": "page-map-input-v1",
  "source_sha256": "<SHA-256 of the supplied PDF>",
  "document_page_count": 452,
  "segments": [
    {
      "mapping_id": "cover-and-unlabeled",
      "mode": "explicit",
      "document_page_range": [1, 4],
      "label_style": "unlabeled",
      "labels": [null, null, null, null],
      "in_evaluation_scope": false,
      "accepts_index_locators": false
    },
    {
      "mapping_id": "front-matter",
      "mode": "sequence",
      "document_page_range": [5, 18],
      "label_style": "roman_lower",
      "label_start": "i",
      "prefix": "",
      "suffix": "",
      "in_evaluation_scope": false,
      "accepts_index_locators": false
    },
    {
      "mapping_id": "main-text",
      "mode": "sequence",
      "document_page_range": [19, 443],
      "label_style": "arabic",
      "label_start": "1",
      "prefix": "",
      "suffix": "",
      "in_evaluation_scope": true,
      "accepts_index_locators": true
    }
  ]
}
```

Supported sequence styles are `arabic`, `roman_lower`, `roman_upper`, `alpha_lower`, and `alpha_upper`. Prefixes and suffixes support labels such as `"S1"` or `"A-12"`.

Use explicit segments for unnumbered, duplicated, irregular, or arbitrary labels:

```json
{
  "mapping_id": "inserted-plates",
  "mode": "explicit",
  "document_page_range": [444, 447],
  "labels": ["Plate 1", "Plate 2", null, "Plate 3"],
  "in_evaluation_scope": true,
  "accepts_index_locators": true
}
```

`null` means the document page has no source label. An explicit label list must have exactly as many items as its inclusive document range.

### Markdown-table equivalent

| Mapping ID | Document pages | Mode | Style | Start or labels | In scope | Index locators |
| --- | --- | --- | --- | --- | --- | --- |
| cover-and-unlabeled | 1–4 | explicit | unlabeled | null; null; null; null | no | no |
| front-matter | 5–18 | sequence | roman_lower | i | no | no |
| main-text | 19–443 | sequence | arabic | 1 | yes | yes |
| inserted-plates | 444–447 | explicit | literal | Plate 1; Plate 2; null; Plate 3 | yes | yes |

Treat en dashes and hyphens in a human table as range punctuation only after confirming the two endpoints. Preserve punctuation inside page labels.

## Expanded page map

Expand the compact form before processing the candidate:

```json
{
  "schema_version": "page-map-v1",
  "document_page_count": 452,
  "pages": [
    {
      "document_page": 19,
      "source_page_label": "1",
      "normalized_locator_key": "1",
      "label_style": "arabic",
      "mapping_id": "main-text",
      "in_evaluation_scope": true,
      "accepts_index_locators": true
    }
  ]
}
```

An indexable normalized key must resolve to exactly one document page. If two indexable sections both use `"1"`, add a source-specific disambiguation policy or mark the result ambiguous; never choose one silently.

For a displayed range such as `"xii–xiv"`, resolve both labels through the expanded map and walk the intervening document pages in the same `mapping_id`. This also works for alphabetic or prefixed sequences. Do not split a literal label such as `"A-12"` at its hyphen merely because it resembles a range. When endpoint parsing or segment continuity is uncertain, retain the raw display and mark the range unresolved for adjudication.

## Chunk manifest

The user supplies or approves owned document-page ranges:

```json
{
  "schema_version": "chunk-manifest-v1",
  "document_page_basis": "one_based_inclusive",
  "require_full_scope_coverage": true,
  "chunks": [
    {
      "chunk_id": "CHUNK-001",
      "title": "Chapter 1",
      "source_units": ["Chapter 1"],
      "owned_document_page_ranges": [[19, 43]],
      "context_document_page_ranges": [[44, 45]],
      "packet_order": 1
    }
  ]
}
```

Owned ranges may be noncontiguous when necessary, but every in-scope document page must have exactly one owner in a full audit. Context ranges may overlap owned pages in another chunk; they never transfer judgment ownership.

## Candidate locator representation

Normalization expands every displayed locator or range to individual assignments:

```json
{
  "locator_id": "LOC-000123",
  "displayed_locator": "12–14",
  "source_page_label": "13",
  "normalized_locator_key": "13",
  "document_page": 31,
  "range_id": "RANGE-000045"
}
```

The chunk filter routes the assignment by `document_page`. A displayed range spanning chunks is split across packets at the assignment level, while each packet retains the original displayed range for auditability.

## Locator-audit packet

A packet contains only relevant paths and in-chunk assignments:

```json
{
  "schema_version": "candidate-locator-chunk-v1",
  "chunk_id": "CHUNK-001",
  "paths": [
    {
      "path_id": "PATH-000042",
      "heading_path": ["Revolution", "economic causes"],
      "locator_assignments": [
        {
          "locator_id": "LOC-000123",
          "displayed_locator": "12–14",
          "source_page_label": "13",
          "document_page": 31
        }
      ],
      "other_locator_assignment_count": 7
    }
  ]
}
```

This packet is intentionally insufficient for judging overall hierarchy or density. Use the complete normalized index during `audit-index-structure`.
