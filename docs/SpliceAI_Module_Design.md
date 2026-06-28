SpliceAI Module Design

Status

Frozen Architecture

Conversation: 5A

Implementation Conversation: 5B

⸻

1. Scientific Purpose

SpliceAI is a deep convolutional neural network, developed by Illumina, that predicts how a variant affects nearby splice sites. For a given variant, it outputs four delta scores — acceptor gain (DS_AG), acceptor loss (DS_AL), donor gain (DS_DG), donor loss (DS_DL) — each in [0, 1], representing the predicted probability that the variant creates or disrupts an acceptor or donor splice site at a nearby position, plus four matching delta positions (DP_*) giving the offset (in bp) from the variant to the affected splice site.

SpliceAI therefore answers a question neither VEP, AlphaMissense, nor gnomAD answers: "does this variant disrupt splicing, independent of whether it changes an amino acid?" This is scientifically distinct from:

* VEP — consequence/transcript annotation (can flag a variant as "splice_region_variant" by proximity to an annotated boundary, but does not predict whether splicing is actually disrupted).
* AlphaMissense — missense pathogenicity only; explicitly out of scope for intronic/splice-region variants.
* gnomAD — population frequency, orthogonal to functional effect entirely.

A variant deep in an intron, or a synonymous exonic variant, can be the single most damaging SNV at a locus if it creates a cryptic splice site — this is exactly the class of variant the other three modules are structurally unable to flag, which is SpliceAI's reason for being a Tier 1 (Essential) module per Project_Context.md.

⸻

2. Biological Scope

Applicable to:

* GRCh38
* SNVs (this project's current scope)

Out of scope for Version 1 (consistent with the project's SNV-first scope, not a SpliceAI limitation per se):

* Indels — Illumina ships indel predictions as a *separate* precomputed file (`spliceai_scores.raw.indel.hg38.vcf.gz` / masked equivalent); excluded from v1 exactly as VEP/AlphaMissense exclude indels today.

Applicable regardless of consequence class — this is the key scope difference from AlphaMissense:

* Exonic missense, synonymous, and nonsense variants
* Intronic variants (including deep intronic, as long as within ~5kb of an annotated gene — see Known Limitations)
* Splice region / splice donor / splice acceptor variants
* UTR variants within gene boundaries

Out of scope regardless of version:

* Variants >5kb from any annotated gene boundary (Illumina's own tool does not score these — see Known Limitations)
* Indels longer than the tool's internal window (not applicable to v1 since indels are excluded entirely)

⸻

3. Relationship with VEP and Other Annotation Modules

VEP

VEP determines consequence, transcript, and (for proximal variants) a `splice_region_variant`-type consequence label based on fixed distance rules from annotated exon/intron boundaries. SpliceAI is a learned model that scores actual predicted disruption, independent of those fixed distance rules — a variant 8bp into an intron might be unflagged by VEP's distance heuristic yet score highly on SpliceAI, and vice versa.

Per the project's established multi-module philosophy, SpliceAI does NOT depend on VEP's transcript selection (MANE Select / Ensembl Canonical). SpliceAI performs coordinate-based lookup against Illumina's own precomputed, gene-symbol-annotated file and returns its own `SYMBOL` field (whatever gene Illumina's pipeline associated with the variant) — this may occasionally differ from VEP's selected transcript's gene, and that is acceptable and expected, exactly as AlphaMissense's canonical-transcript dataset is permitted to differ from VEP's transcript selection (AlphaMissense_Module_Design.md, Risks section).

AlphaMissense

Independent and complementary. AlphaMissense scores missense substitution pathogenicity; SpliceAI scores splicing disruption regardless of substitution type. A variant can score high on one, the other, both, or neither — no duplicated functionality, no shared computation.

gnomAD

Independent. gnomAD's population frequency and SpliceAI's splice-disruption score are orthogonal axes of evidence; a future InterVar module would consume both as separate ACMG criteria inputs without either depending on the other internally.

Future Modules (GERP++, LOEUF, InterVar, MutPred, etc.)

InterVar is the most direct downstream consumer — SpliceAI's delta scores map onto ACMG splicing-impact criteria (e.g. PVS1 considerations for predicted null variants via splicing). This module exposes raw delta scores/positions only; it performs no ACMG classification itself, identical in spirit to gnomAD's "raw frequency facts only, no InterVar logic" boundary (gnomAD_Module_Design.md Section 6).

⸻

4. Relationship with the Shared Framework

This module is intentionally one of the smallest and most "shared-infrastructure-heavy" modules in the project. Confirmed by direct inspection of the real `shared/indexed_files` source (not assumed):

* `shared.indexed_files.get_tabix_lookup(file_path)` — reused as-is. No changes required.
* `shared.validators.validate_variant()` — reused as-is for input validation.
* `shared.cache` (`DiskCache`, `make_key`) — reused as-is, following the AlphaMissense caching pattern (local file, effectively unlimited TTL).
* `shared.logging.get_logger()` — reused as-is.
* `shared.exceptions` — reused as-is; specifically `ResourceCorruptedError` (already raised by `TabixLookup` itself for missing/corrupt index or file, and for a chromosome-naming mismatch — see Section 8) and `ValidationError`.
* `shared.reference.get_reference_manager()` — reused as-is for resource discovery/version reporting, exactly as AlphaMissense uses it.
* `shared.config.get_config()` — reused as-is; `reference_resources.spliceai` and `versions.spliceai_version` already exist as placeholder entries in `config.yaml` (currently `marker_paths: ["spliceai_scores.vcf.gz"]`, `version_key: "spliceai_version"`, value `null`) — Section 18 below finalizes the exact marker filename and pins the version.

No new shared infrastructure is required. This is a direct, intentional consequence of AlphaMissense's design having generalized `shared.indexed_files` rather than building an AlphaMissense-specific reader — the real `tabix.py` source explicitly documents "Intended to also be reused by the future SpliceAI ... modules without modification."

⸻

5. Data Source

Primary source: Illumina's official precomputed SpliceAI annotation files, distributed via Illumina BaseSpace (the same distribution channel referenced in AlphaMissense's Zenodo-style "official static download" pattern — no live API exists for SpliceAI, exactly as none exists for AlphaMissense).

Two independent, currently-published sources confirm the same file format (Illumina's own GitHub README and the actively-maintained Ensembl VEP_plugins SpliceAI.pm, both independently consistent): each row is a standard VCF line —

```
CHROM  POS  ID  REF  ALT  QUAL  FILTER  INFO
```

— where `INFO` contains a single `SpliceAI=` key whose value is one or more comma-separated, pipe-delimited entries, one per ALT allele at that row:

```
ALLELE|SYMBOL|DS_AG|DS_AL|DS_DG|DS_DL|DP_AG|DP_AL|DP_DG|DP_DL
```

Distributed as two **separate** files split by variant class:

* `spliceai_scores.raw.snv.hg38.vcf.gz` (+ `.tbi`) — SNVs
* `spliceai_scores.raw.indel.hg38.vcf.gz` (+ `.tbi`) — indels (out of scope, Section 2)

And by masking mode:

* **raw** (`-M 0`): includes all predicted splicing changes, including weaker/less-pathogenic categories (strengthening an already-annotated site, weakening an unannotated site).
* **masked** (`-M 1`): zeroes out those less-pathogenic categories, leaving only the two changes most associated with true pathogenic splicing disruption (weakening an annotated site, strengthening an unannotated site).

**Frozen decision: use the masked SNV file** (`spliceai_scores.masked.snv.hg38.vcf.gz`). Rationale: this project's validation strategy (Section 16) is built around biological sanity-checking against known pathogenic variants, and the masked file is the variant set Illumina and the Ensembl VEP plugin both default to recommending for clinical/pathogenicity-oriented interpretation — using the noisier raw file would require this module to reimplement masking logic itself, which is exactly the kind of "recompute what the source already computed" mistake flagged during the gnomAD review (gnomAD module, parser.py correction history). Use the authoritative masked file Illumina ships, not a locally-recomputed approximation of it.

⸻

6. Version Pinning Strategy

Identical pattern to AlphaMissense (Zenodo+SHA256) adapted to SpliceAI's actual distribution mechanism (BaseSpace, not Zenodo):

* Pin a specific SpliceAI release/tool version string (e.g. `"spliceai:1.3.1"`, matching the version embedded in the VCF header's `##INFO=<ID=SpliceAI,...,Description="SpliceAIv1.3.1...">` line) in `config.yaml` under `versions.spliceai_version`.
* Record a SHA256 checksum of the downloaded `spliceai_scores.masked.snv.hg38.vcf.gz` file at `reference/spliceai/VERSION`, identical in spirit to AlphaMissense's `VERSION` marker file.
* `annotate()` refuses to proceed if `spliceai_version` is unpinned (`null`), mirroring gnomAD's frozen rule (gnomAD_Module_Design.md Section 20) and VEP's reproducibility requirement.
* Every output envelope records `data_release` / `source_version` = the pinned version string, so any result is traceable to the exact file version that produced it.

⸻

7. Storage Strategy

* Reference directory: `reference/spliceai/` (already declared in `config.yaml`'s `reference_resources.spliceai`, currently pointing at a single placeholder marker filename that needs correction — see Section 18).
* Files:

```
reference/
└── spliceai/
    ├── spliceai_scores.masked.snv.hg38.vcf.gz
    ├── spliceai_scores.masked.snv.hg38.vcf.gz.tbi
    └── VERSION
```

* The genome-wide masked SNV file (within-gene positions only) is large but bounded — materially smaller than gnomAD's full joint VCF and broadly comparable in scale to AlphaMissense's dataset. No chromosome-scoping or partial-download strategy is needed (unlike gnomAD's deferred local backend, which had no official slim file); SpliceAI ships exactly one appropriately-sized official file for this project's scope.
* No live API exists, so there is no "remote vs local" hybrid question here — this module is local-file-only from the start, more directly comparable to AlphaMissense's architecture than to gnomAD's.

⸻

8. Can `shared/indexed_files` Be Reused? — Yes, As-Is

Confirmed directly from the real `tabix.py` source (not assumed):

* `get_tabix_lookup(file_path).fetch(chrom, position)` takes a 1-based position — matching this project's canonical `annotate(chrom, position, reference, alternate)` convention exactly. No coordinate-conversion responsibility falls on this module; `TabixLookup` already owns the 1-based→pysam 0-based half-open conversion in one frozen location.
* `fetch()` returns raw tab-split rows as tuples of strings, with **no knowledge of VCF semantics** — it does not parse `INFO`, does not split multi-allelic `ALT`, and does not know what a `SpliceAI=` key is. All of that is correctly left to this module's parser, consistent with the layer's frozen "no biological interpretation" boundary (tabix.py module docstring) and the AlphaMissense precedent.
* `ResourceCorruptedError` is already raised by `TabixLookup` itself for: file missing, index missing, corrupted/mismatched index, or chromosome-naming mismatch (e.g. "chr1" vs "1") between query and indexed file. This module does not need to add its own resource-state error handling — it only needs to catch and pass through, exactly as AlphaMissense does.
* Multiple matching rows at one position (the tabix layer's existing "multiple matches" condition) is a real, expected case here for a different reason than AlphaMissense: a single VCF row's `SpliceAI=` INFO value can itself contain multiple comma-separated per-ALT-allele entries (one row, multiple alleles — see the real example in Section 5, position 152389953 with ALT `A,C,G`). This is **not** the same "multiple_matches" condition as multiple distinct rows; it is multiple entries *within* one row's INFO field, and the parser is responsible for selecting the entry whose `ALLELE` matches the queried `alternate`. See Section 11 for the exact precedence rule.

No new abstraction is needed in `shared.indexed_files`. This module's parser is solely responsible for: splitting `INFO` on `SpliceAI=`, splitting on `,` for multiple ALT-allele entries, splitting each entry on `|`, and matching `ALLELE` against the queried `alternate`.

⸻

9. Input Contract

```
annotate(
    chrom,
    position,
    reference,
    alternate
)
```

Identical to VEP, AlphaMissense, and gnomAD. GRCh38 only. SNVs only (v1). Validated via `shared.validators.validate_variant()` before any file access.

⸻

10. Output Schema

`SpliceAIAnnotation`

Contains:

* `variant_id`
* `ds_acceptor_gain` (DS_AG)
* `ds_acceptor_loss` (DS_AL)
* `ds_donor_gain` (DS_DG)
* `ds_donor_loss` (DS_DL)
* `dp_acceptor_gain` (DP_AG)
* `dp_acceptor_loss` (DP_AL)
* `dp_donor_gain` (DP_DG)
* `dp_donor_loss` (DP_DL)
* `max_delta_score` — derived field, `max(DS_AG, DS_AL, DS_DG, DS_DL)`, exposed because Illumina's own documentation defines this exact quantity as "the probability of the variant being splice-altering," i.e. it is an authoritative derived definition, not an invented one (distinct from the gnomAD `joint`-vs-manual-summation issue, because here Illumina's own docs define the combination rule, not this module reinterpreting it)
* `gene_symbol` (SYMBOL — Illumina's own gene association for this entry, independent of VEP's transcript selection per Section 3)
* `source_dataset` (e.g. `"spliceai_masked_snv"`)
* `data_release` (pinned version string)
* `annotation_source` (`"local"` — only backend that will ever exist for this module, see Section 12)
* `status`

Envelope (standard framework pattern):

```
{
    "variant_id": "...",
    "module_name": "spliceai",
    "status": "...",
    "fields": ...,
    "source_version": ...
}
```

⸻

11. Parser Architecture

Pure functions, no I/O, mirroring the AlphaMissense/gnomAD precedent of keeping all biological/format parsing strictly module-local:

1. `TabixLookup.fetch(chrom, position)` returns zero or more raw row-tuples (whole VCF lines, tab-split).
2. For each row, extract the `ALT` column (comma-separated list of alleles at this position) and the `INFO` column's `SpliceAI=...` value (comma-separated list of pipe-delimited per-allele entries).
3. **Matching rule (frozen):** select the entry whose leading `ALLELE` field equals the queried `alternate` exactly (case-sensitive, uppercase-normalized via `validate_variant()`'s existing normalization). This is the correct match key — not row/ALT-column position — because a multi-ALT row's `SpliceAI=` entries are explicitly ALLELE-tagged by Illumina's own format, precisely so that consumers don't have to rely on positional correspondence between the VCF `ALT` column and the INFO entries.
4. If zero rows are returned by `fetch()` → `status = "no_data"`, all score fields `None` (never `0.0` — a variant simply outside Illumina's scored window is not equivalent to "zero splicing impact," exactly as gnomAD's "not observed ≠ frequency zero" principle, gnomAD_Module_Design.md Section 21).
5. If one or more rows are returned but none contains a matching `ALLELE` → `status = "no_data"` (the position is scored for other alleles, but not this exact substitution).
6. If a matching entry is found but Illumina recorded `"."` for any field (seen in the real example output for a complex multi-allelic indel row) → that specific field is `None`; this is distinct from "no matching entry" and is reported as `status = "ok"` with partial `None` fields, not `"no_data"` wholesale — a partial result is still real information and must not be discarded (Project_Context.md: "Never silently remove variants").
7. `max_delta_score` is computed only from non-None DS_* values; if all four are `None`, `max_delta_score` is also `None` (never `0.0`).

⸻

12. Client / Backend Architecture

There is no remote client in this module — unlike gnomAD, SpliceAI has no live API at all (Section 5), so there is no "remote vs local" decision to defer. The single backend is a thin wrapper, structurally parallel to gnomAD's `GnomadRemoteClient` / future `GnomadLocalClient` seam, so the module-author-facing pattern stays consistent across the project even though SpliceAI never needs a second backend:

```python
class SpliceAILocalClient:
    def fetch_variant_rows(self, chrom: str, position: int) -> list[tuple[str, ...]]:
        lookup = get_tabix_lookup(self._file_path)
        return lookup.fetch(chrom, position)
```

`annotate()` calls this client, then the parser (Section 11), exactly mirroring the gnomAD module's `client → parser → envelope` flow and the AlphaMissense `annotate()` flow.

⸻

13. Annotator Flow

```
annotate(chrom, position, reference, alternate)
    -> shared.validators.validate_variant()           [raises ValidationError]
    -> shared.config.get_config().version("spliceai_version")
       -> raise ValidationError if unpinned (Section 6)
    -> check shared.cache.DiskCache                    [cache hit -> return]
    -> shared.reference.get_reference_manager().get("spliceai")
       -> resolves the on-disk file path; raises UnknownResourceError /
          ResourceCorruptedError per the existing Reference Manager contract
          (no new error path introduced)
    -> SpliceAILocalClient.fetch_variant_rows(chrom, position)
       -> shared.indexed_files.get_tabix_lookup(path).fetch(chrom, position)
       -> ResourceCorruptedError propagates untouched on index/contig problems
    -> parser.parse_variant_rows(rows, alternate)       [Section 11]
    -> wrap in standard envelope
    -> cache.set()                                      [never on error]
    -> return
```

⸻

14. Error Handling

Reuse existing shared exceptions only — no new exception hierarchy, identical to every prior module:

* `ValidationError` — bad input, or `spliceai_version` unpinned.
* `ResourceCorruptedError` — raised by `TabixLookup` itself (missing file/index, corrupted index, chromosome-naming mismatch) or by `shared.reference.ReferenceManager.get()` for a resource present-but-unusable. This module never wraps or reinterprets it — let it propagate, exactly as AlphaMissense does.
* `UnknownResourceError` — raised by `ReferenceManager.get("spliceai")` if the resource isn't declared in `config.yaml` at all (defensive; should not occur once Section 18's config addition lands).
* No silent failures: a parser that finds no matching `ALLELE` entry returns `status="no_data"`, it does not raise and does not fabricate a score.

⸻

15. Caching Strategy

Identical to AlphaMissense's frozen caching contract (local file, no remote staleness possible):

* Backend: `DiskCache` at `{cache_dir}/spliceai.sqlite`.
* Cache key: `make_key("spliceai", "local", spliceai_version, chrom, position, reference, alternate)` — includes `"local"` as an explicit backend tag for the same forward-compatibility reason established in the gnomAD module (so a hypothetical future second data source, e.g. an indel file, can never collide with this key even though none is planned for v1).
* TTL: unlimited (local static file; no time-based expiry, matching AlphaMissense exactly — gnomAD's 90-day TTL does not apply here since there is no live release cadence to go stale against).
* Cache on error: never.
* `no_data` results are cached (a confirmed absence against a pinned file version is a stable, reproducible fact, matching gnomAD's frozen rule).

⸻

16. Validation Strategy

Shared validation (`validate_variant()`) plus biological sanity checks specific to splicing:

Representative known variants (analogous to AlphaMissense's TP53/HBB/APOE4 set, chosen for splicing relevance specifically):

* A well-characterized canonical splice-site variant with documented high SpliceAI scores in the literature (e.g. a published canonical donor-site disruption in a Mendelian disease gene) — expect a high `max_delta_score` (>0.5) at the correct delta position.
* A synonymous exonic variant with no known splicing effect — expect a low `max_delta_score`, demonstrating the module correctly returns low scores for the "VEP would call this benign-by-consequence-class" case rather than only ever returning high scores near gene structure.
* A deep intronic variant known to create a cryptic splice site in the literature (a classic SpliceAI use case precisely because VEP's consequence-class would not flag it) — expect a high `DS_AG` or `DS_DG` score and a `DP_*` value pointing toward the real cryptic site, demonstrating the scientific value proposition from Section 1 concretely.
* A variant >5kb from any gene — expect `status="no_data"`, confirming the "outside scored window ≠ zero impact" rule from Section 11 is honored.

⸻

17. Testing Strategy

Unit Tests

* `ALLELE` matching against a multi-allele INFO entry (the Section 11 matching rule).
* No matching row at all (`no_data`).
* Matching row but no matching `ALLELE` (`no_data`).
* `"."` field handling (partial `None` fields, `status="ok"`, not discarded).
* `max_delta_score` computed correctly, and `None` only when all four DS_* are `None`.
* Variant ID construction, consistent with VEP/AlphaMissense/gnomAD.

Parser Tests

* Pure-function tests against small synthetic INFO-string fixtures (no file I/O), exactly mirroring gnomAD's `parser.py` unit-test separation from its client-mock tests.

Mock Tests

* Small local indexed fixture VCF + `.tbi` (a handful of real-format rows), no network — identical pattern to AlphaMissense's mock-fixture strategy. `shared.indexed_files`'s own test suite (already proven for AlphaMissense) is reused unmodified; this module's tests only need a tiny fixture file of its own.

Cache Tests

* Hit/miss/never-cache-errors, with the same `tmp_path`-isolated `DiskCache` pattern adopted during the gnomAD review (a real, previously-discovered bug class — sharing one persistent on-disk SQLite cache across tests caused cross-test pollution; this module's test suite is designed to avoid that mistake from the start rather than rediscover it).

Integration Tests

* Require the real downloaded SpliceAI masked SNV file; `@pytest.mark.integration`, automatically skipped if unavailable — identical pattern to AlphaMissense and gnomAD.

Biological Sanity Tests

* Implements the representative-variant checks from Section 16, fixture-driven for speed (consistent with how the gnomAD module's biological sanity tests were structured) but documented as needing live-file confirmation before being trusted as a true biological claim, exactly as the gnomAD review flagged the unconfirmed `filters` field rather than silently asserting it.

⸻

18. Configuration Additions

`config.yaml` already declares a placeholder for this resource (visible in the uploaded `config.yaml`), but it needs correcting, not just pinning — flagged explicitly rather than silently changed:

Current (placeholder, incorrect marker filename and unpinned version):

```yaml
reference_resources:
  spliceai:
    subdir: "spliceai"
    marker_paths: ["spliceai_scores.vcf.gz"]
    version_key: "spliceai_version"
    budget: "reference"

versions:
  spliceai_version: null
```

Required change — marker filename must match the actual frozen file decision from Section 5/7 (masked SNV file, not a generic placeholder name), and the version must be pinned:

```yaml
reference_resources:
  spliceai:
    subdir: "spliceai"
    marker_paths:
      - "spliceai_scores.masked.snv.hg38.vcf.gz"
      - "spliceai_scores.masked.snv.hg38.vcf.gz.tbi"
    version_key: "spliceai_version"
    budget: "reference"

versions:
  spliceai_version: "spliceai:1.3.1"   # match the actual downloaded file's header version
```

This is the one and only config change required. No new service block (no API), no new shared rate-limit bucket (no network calls at all).

⸻

19. Directory Structure

```
modules/
└── spliceai/
    ├── __init__.py           # annotate() + SpliceAIAnnotation
    ├── client.py              # SpliceAILocalClient (thin get_tabix_lookup wrapper)
    ├── parser.py              # INFO-string parsing, ALLELE matching, max_delta_score
    ├── constants.py           # status values, module name, masking/file-naming constants
    ├── README.md
    ├── examples/
    │   └── basic_usage.py
    └── tests/
        ├── __init__.py
        ├── test_unit.py
        ├── test_parser.py
        ├── test_mocked_lookup.py      # small fixture .vcf.gz/.tbi, no network
        ├── test_cache.py
        ├── test_integration.py
        └── test_biological_sanity.py

reference/
└── spliceai/
    ├── spliceai_scores.masked.snv.hg38.vcf.gz
    ├── spliceai_scores.masked.snv.hg38.vcf.gz.tbi
    └── VERSION
```

Existing files modified: only `config.yaml` (Section 18). No `shared/` changes.

⸻

20. Known Limitations

* SNVs only in v1; indels deferred (separate official file, same pattern as gnomAD's deferred local backend — a future module extension, not a redesign).
* Does not score variants more than ~5kb from any gene boundary — this is Illumina's own tool limitation, not an artifact of this module's implementation; such variants correctly return `status="no_data"`.
* Gene symbol association (`gene_symbol`) comes from Illumina's own annotation pipeline and may occasionally differ from VEP's selected transcript's gene (Section 3) — expected, not a bug.
* Masked-file choice (Section 5) means certain lower-pathogenicity-category splicing changes are intentionally zeroed by Illumina's own masking, not recoverable from this file; a future version could add the raw file as a second, explicitly-labeled data source if a concrete downstream need arises (mirroring gnomAD's "defer until a real need exists" extensibility philosophy).
* Static, infrequently-updated precomputed dataset — no predictable release cadence (same limitation already documented for AlphaMissense).
* Research tool; not a substitute for clinical splicing-assay confirmation.

⸻

21. Risks

* No live API exists at all for SpliceAI — if Illumina ever discontinues or relocates the BaseSpace distribution, there is no fallback remote source to switch to (unlike gnomAD's hybrid design). This is a real single-point-of-distribution risk, not mitigated by this architecture; noting it rather than solving it, since solving it is outside this module's scope.
* Masked vs. raw file choice is a one-way scientific decision baked into the pinned file; switching later means re-downloading and re-pinning a different file, not a config toggle (no module code change required, but a real operational step).
* Multi-allele INFO-entry parsing (Section 11) is the one piece of this module's logic with no precedent elsewhere in the codebase (AlphaMissense and gnomAD's `population_frequencies` parsing don't have this exact "multiple tagged entries within one field" shape) — flagged as the most implementation-risk-bearing piece of Conversation 5B, worth extra unit-test attention precisely because it's novel.
* The exact marker filename in Section 18 assumes Illumina's current naming convention (`spliceai_scores.masked.snv.hg38.vcf.gz`) remains stable; this should be confirmed against the actual downloaded file name before implementation, the same kind of "confirm before trusting" caveat raised for the gnomAD `filters` field.

⸻

22. GO / NO-GO Implementation Checklist

GO, with the following pre-conditions, mirroring the AlphaMissense and gnomAD GO decisions:

1. `reference_resources.spliceai.marker_paths` in `config.yaml` is corrected to the actual masked-SNV filename(s) actually downloaded (Section 18) — confirm the real filename against the downloaded file before finalizing, do not assume the name in this document is exact.
2. `versions.spliceai_version` is pinned to the real tool/file version (Section 6).
3. The masked SNV file + `.tbi` are placed at `reference/spliceai/` and a `VERSION` marker file with a SHA256 checksum is recorded (Section 6/7).
4. No `shared/` changes are required — confirmed by direct inspection of the real `shared/indexed_files/tabix.py` source, which already anticipates and is designed for this exact reuse.

Architecture is fully frozen. No additional design work is required before implementation begins in Conversation 5B.
