gnomAD Module Design

Status

Frozen Architecture

Conversation: 5A

Implementation Conversation: 5B

⸻

1. Scientific Purpose

gnomAD (Genome Aggregation Database) provides population allele frequency data aggregated across large sequencing cohorts (genomes + exomes).

Its role in the framework is to answer: "How common is this exact variant in human populations?"

This is fundamentally different from VEP (consequence) and AlphaMissense (pathogenicity prediction). gnomAD contributes population-genetics evidence, which is one of the strongest signals for distinguishing benign variation from disease-causing variation — a very rare variant is more likely to be pathogenic than a common one, almost independent of in-silico predictions.

gnomAD is therefore a population-frequency annotation module, not a consequence or pathogenicity module.

⸻

2. Biological Assumptions

* GRCh38 coordinates only (gnomAD v4 is GRCh38-native; v2 liftover data is explicitly out of scope).
* Allele frequencies are cohort-dependent estimates, not ground truth — absence from gnomAD does not mean a variant does not exist in the population, only that it was not observed in the sequenced cohort.
* gnomAD aggregates unrelated individuals after extensive QC; frequencies reflect the general population, not a disease cohort.
* SNVs and indels are both supported by gnomAD; this module's first version supports SNVs only, consistent with the framework's current scope, with indel support deferred.
* Multi-allelic sites are normalized by gnomAD itself (each ALT allele is a separate record); the framework must request frequencies for one specific ALT at a time and never assume a single REF/POS pair maps to a single record.

⸻

3. Strengths and Limitations

Strengths

* Largest publicly available population frequency resource.
* Both overall and population-specific allele frequencies.
* High-quality QC flags (filtering status, genotype quality) available alongside frequencies.
* No cost, no authentication required.

Limitations

* Cohort composition is not a perfectly representative sample of global human diversity (still skewed toward European ancestry, though improving across releases).
* Somatic mosaicism, sequencing artifacts, and segmental duplications can produce spurious frequency signals; gnomAD's own filtering flags must be respected, not ignored.
* Coverage is uneven across the genome (e.g., low coverage in some GC-rich or repetitive regions); a "not found" result must never be silently interpreted as "definitely absent from the population."
* Release cadence is irregular and versions are not drop-in equivalent (allele counts, sample sizes, and even variant calling pipelines change across major versions).
* gnomAD is not a clinical-grade frequency source; rare disease frequency claims still require independent clinical confirmation.

⸻

4. Relationship with VEP

VEP determines variant consequence, transcript, and amino-acid change.

gnomAD performs an independent coordinate-based frequency lookup and does not consume VEP's transcript selection, consistent with the precedent already set by AlphaMissense.

The two modules may be combined downstream (e.g., "rare + predicted damaging"), but neither depends on the other's internals.

⸻

5. Relationship with AlphaMissense

AlphaMissense predicts pathogenicity for missense substitutions using a local Tabix-indexed dataset.

gnomAD predicts population frequency for any SNV (not missense-restricted) and is architecturally the closest sibling module to AlphaMissense — both are coordinate-keyed, both lend themselves to local indexed-file storage, and both should be able to share `shared/indexed_files`.

The key architectural question (addressed in Section 9) is whether gnomAD also reuses this shared layer or requires a remote API path, given that gnomAD's official, fully-maintained query surface is the GraphQL API, whereas AlphaMissense ships only as a static downloadable file.

⸻

6. Relationship with Future Modules (LOEUF, InterVar, SpliceAI, etc.)

* LOEUF (gene-level constraint) is itself a gnomAD-derived metric, but it is a per-gene constant, not a per-variant lookup — it will be implemented as its own small module (likely a static lookup table keyed by gene, not by variant) and must not be folded into the gnomAD module's variant-level interface.
* InterVar consumes population frequency as one of its ACMG criteria (notably PM2 — absent or rare in population databases); the gnomAD module's `status` and frequency fields are designed to be consumed directly by InterVar's rule evaluation without re-querying gnomAD itself.
* SpliceAI is an independent splicing-prediction module and will reuse `shared.indexed_files` exactly as AlphaMissense and gnomAD do, but has no direct dependency on gnomAD output.
* No duplicated functionality: gnomAD module never computes constraint metrics, ACMG classifications, or splicing impact. It exposes raw frequency facts only.

⸻

7. Official Data Sources

Two genuinely official sources exist:

1. gnomAD GraphQL API (`https://gnomad.broadinstitute.org/api`) — the Broad Institute's own public query interface, actively maintained, versioned by dataset parameter (e.g., `gnomad_r4`).
2. gnomAD downloadable VCFs/Hail Tables (joint frequency VCFs, per-chromosome, hosted on Google Cloud / Azure / AWS via the gnomAD downloads page) — the canonical bulk data, identical numbers to the API, but requires local storage and a BGZF/Tabix-style indexed lookup.

Both are "official" in the sense that they originate from the Broad Institute and are kept in sync at each gnomAD release; the GraphQL API is simply a hosted query layer over the same underlying data as the VCFs.

⸻

8. REST/GraphQL vs Downloadable VCFs vs Hybrid Strategy

Frozen decision: Hybrid, with GraphQL as the default path and local Tabix-indexed VCF as an optional, explicitly-enabled fallback for large-scale annotation.

Rationale:

* Development and small/medium batch annotation (the framework's current stage) benefit from the GraphQL API: zero storage cost, always current within a pinned dataset version, no 90 GB-style disk risk of the kind already encountered with MutPred2.
* Large-scale annotation (thousands–millions of variants, the eventual ML feature-dataset stage) will be rate-limited and slow against a remote API. At that scale, a local indexed VCF is the only practical option.
* This mirrors the AlphaMissense precedent (local indexed file) while respecting that gnomAD, unlike AlphaMissense, has a first-class official API — so forcing local-only would discard a freely available, zero-storage-cost path that is ideal for the project's current scale.

This hybrid is implemented as two interchangeable backends behind one `annotate()` interface, selected by configuration (`gnomad_backend: remote | local`), not by call-site branching. The module's public behavior and output schema are identical regardless of backend.

⸻

9. Local Database vs Remote Queries vs Hybrid Architecture

Frozen decision: Hybrid (Section 8), implemented as two backend classes sharing one annotation contract.

Remote backend (`GnomadRemoteClient`)

* Uses `shared.http.HttpClient.for_service("gnomad_graphql")` exclusively — no raw `requests` calls, consistent with the VEP module's Defect C-1 lesson.
* GraphQL queries are parameterized by `dataset` (pinned version) and `variant_id` (gnomAD's own `chrom-pos-ref-alt` notation).

Local backend (`GnomadLocalClient`)

* Reuses `shared.indexed_files.get_tabix_lookup()` exactly as AlphaMissense does — the gnomAD joint-frequency VCF, once Tabix-indexed, fits the same generic "coordinate in, rows out" contract.
* This is the direct answer to the design question: yes, `shared/indexed_files` is reused as-is. No new shared abstraction is required for the indexed-lookup mechanics themselves. The only module-specific addition is a VCF-INFO-field parser (gnomAD-specific), which — consistent with the AlphaMissense precedent that "all biological parsing remains module-specific" — lives in `modules/gnomad/`, not in the shared layer.

One shared infrastructure addition is required: a generic rate-limiting/backoff policy for GraphQL-style POST APIs. `shared.http.HttpClient` was built and proven against simple REST GET endpoints (VEP). gnomAD's GraphQL endpoint is a single POST endpoint with a request body, and the existing rate limiter's per-route token bucket may need a named bucket for `gnomad_graphql` distinct from `ensembl_vep`. This is a configuration-level addition (a new entry in the shared rate-limit config), not a new code abstraction, and should be confirmed as in-scope for Conversation 5B rather than requiring its own design conversation.

⸻

10. Storage Requirements

* Remote backend: negligible (cache only, see Section 18).
* Local backend: the gnomAD v4 joint VCF is large — full genome-wide exomes+genomes frequency files run into the tens of gigabytes per chromosome-set even before any decompression, and unlike AlphaMissense there is no single canonical-transcript-only slim file officially published by the Broad Institute.
* Given the project's 200 GB total storage budget and the explicit project-context rule that "MutPred is never allowed to dictate project architecture," the same principle applies here: gnomAD's local backend must never be assumed as the default, and any local download must be scoped (e.g., specific chromosomes or a frequency-filtered subset) rather than the full joint VCF, to avoid repeating the MutPred2-style disk-pressure problem.
* Frozen rule: local backend downloads are opt-in and chromosome-scoped on request, never an automatic full-genome download triggered by default configuration.

⸻

11. Shared Infrastructure Requirements

Reused as-is (no changes needed):

* `shared.config`, `shared.cache`, `shared.validators`, `shared.logging`, `shared.exceptions`
* `shared.indexed_files` (local backend)
* `shared.http.HttpClient` (remote backend, GET-style usage pattern already proven by VEP)

Requires a small, explicitly-flagged addition:

* A named rate-limit bucket for `gnomad_graphql` in the shared rate-limiter configuration (POST-based GraphQL, distinct quota from `ensembl_vep`).
* This is a configuration extension, not a new abstraction, and should be called out to the user/implementer before Conversation 5B begins, per the project rule that any shared-infrastructure dependency must be identified before implementation.

⸻

12. Input Contract

annotate(
    chrom,
    position,
    reference,
    alternate
)

Identical to VEP and AlphaMissense. GRCh38 only. SNVs only (v1). Validated via `shared.validators.validate_variant()` before any backend is touched.

⸻

13. Output Schema

GnomadAnnotation

Contains:

* variant_id
* af_overall
* ac_overall
* an_overall
* af_popmax
* popmax_population
* population_frequencies (dict: population code → {af, ac, an})
* filter_status
* n_homozygotes
* source_dataset
* data_release
* annotation_source ("remote" or "local", recorded per-call for reproducibility)
* status

Envelope (matches AlphaMissense/VEP precedent):

{
    "variant_id": "...",
    "module_name": "gnomad",
    "status": "...",
    "fields": ...,
    "source_version": ...
}

⸻

14. Allele Frequency Fields (Overall and Population-Specific)

Frozen minimal, non-duplicative field set:

* `af_overall` — overall allele frequency across the full cohort.
* `ac_overall` / `an_overall` — allele count / allele number, retained because raw counts let downstream modules (e.g., InterVar's PM2 threshold logic) judge confidence in a frequency estimate (an AF of 0 from an_overall of 4 is far less informative than from an_overall of 150,000).
* `af_popmax` and `popmax_population` — the single highest population-specific frequency and which population it belongs to. This is the field most relevant for rare-disease triage (a variant common in one population but rare overall is not "rare" in the relevant clinical sense).
* `population_frequencies` — full per-population breakdown, included for completeness and future modules that may want ancestry-aware filtering, but `af_popmax` is the field most downstream modules should consume directly to avoid each module re-deriving the same maximum.
* `n_homozygotes` — count of individuals homozygous for the alternate allele; biologically important because observed homozygosity in a "healthy" population cohort is strong evidence against a variant being a fully penetrant dominant pathogenic allele.

No exome-only vs genome-only field split is exposed in v1; the module returns gnomAD's pre-combined joint frequencies, deferring exome/genome-specific breakdowns to a future version if a concrete downstream need arises (avoiding speculative field bloat).

⸻

15. Filtering Strategy

* Variants present in gnomAD but flagged with a non-PASS filter status (e.g., `AC0`, low-quality-site flags) are still returned, with `filter_status` populated, rather than silently dropped — consistent with the project rule "never silently remove variants."
* The annotation `status` field is used to signal interpretive caveats (e.g., `low_confidence`) without ever omitting the underlying data.
* Multi-allelic sites: each (chrom, position, reference, alternate) tuple is queried as gnomAD's own normalized single-ALT record. The module never aggregates across multiple ALT alleles at the same position; the caller is responsible for passing one fully-specified ALT per call, matching the VEP module's documented multi-allelic decomposition requirement upstream.

⸻

16. Validation Strategy

Shared validation (`shared.validators.validate_variant()`) plus biological sanity checks specific to frequency data:

* A well-known common variant should return a high, non-zero `af_overall` (e.g., a common benign coding SNP).
* A well-known ultra-rare/disease variant (e.g., a known pathogenic Mendelian-disease allele) should return `af_overall` near zero or `status = no_data`.
* A variant known to have high homozygosity in gnomAD despite rarity in disease cohorts is used as a check that the module does not silently misrepresent `n_homozygotes`.

⸻

17. Error Handling

Reuse existing shared exception hierarchy — no new exceptions, matching the precedent set by AlphaMissense and required by Project Context's "future modules must never implement their own exceptions."

* Remote backend network/HTTP failures → `NetworkError` / `RateLimitError` (existing).
* Resource problems (local backend file missing/corrupt) → `ResourceCorruptedError` / `UnknownResourceError` (existing, same as AlphaMissense).
* Bad input → `ValidationError` (existing).
* No silent failures, no error dicts returned — raise only, per the VEP module's Defect C-4 lesson.

⸻

18. Caching Strategy

* Backend: `DiskCache`, consistent with VEP.
* Cache key includes: dataset version, backend used, chrom, position, reference, alternate — backend is included in the key because remote and local sources could theoretically diverge slightly between releases, and conflating them in one cache key would hide that.
* TTL: gnomAD major releases are infrequent and not on a fixed schedule (unlike Ensembl's quarterly cadence); a longer default TTL (90 days) is appropriate, with the same "never cache errors" rule as VEP.
* Cache on error: never, identical to VEP's frozen caching contract.

⸻

19. Rate Limiting (Remote Backend)

* gnomAD does not publish a strict public rate limit in the way Ensembl does, but as a courtesy- and stability-driven default, the module adopts a conservative self-imposed limit (e.g., 5 req/s) via a new named bucket in the shared rate limiter, distinct from `ensembl_vep`.
* This is the one shared-infrastructure configuration addition flagged in Section 11 and must be added before Conversation 5B implementation begins.

⸻

20. Version Pinning Strategy

* Remote backend: GraphQL `dataset` parameter is pinned in `config.yaml` (e.g., `gnomad_dataset: "gnomad_r4"`), never left as a default/latest value, mirroring VEP's `ensembl_release` pinning requirement.
* Local backend: file-based version pinning identical to AlphaMissense — a `VERSION` marker file plus a SHA256 checksum recorded in config.
* Both backends record `data_release` in every output envelope so that any output can be traced to the exact gnomAD version that produced it, regardless of which backend served the request.

⸻

21. Missing-Data Policy

* Missing biological values → Python `None`. Never `"None"`, `""`, or `"Unknown"` — identical to AlphaMissense and VEP.
* A variant absent from gnomAD entirely is not assumed to be ultra-rare in the population; the module returns `status = no_data` with all frequency fields as `None`, explicitly avoiding the interpretive leap "not in gnomAD" → "frequency is zero."

⸻

22. Status Values

* `ok`
* `no_data` (variant not found in the pinned gnomAD release)
* `low_confidence` (found, but flagged with quality concerns, e.g., low coverage region or non-PASS filter)
* `multiple_matches` (reserved for indel/complex-allele edge cases in a future version; should not occur for SNVs but the value is reserved now for schema stability)

⸻

23. Confidence / Quality Fields

* `filter_status` exposes gnomAD's own site-level QC filter (e.g., `PASS`, `AC0`, `InbreedingCoeff`) verbatim, rather than the module collapsing it into a boolean, so downstream modules can apply their own thresholds.
* `an_overall` doubles as an implicit confidence signal (low `an_overall` relative to the cohort's expected sample size indicates a poorly-covered site) and is retained for this reason rather than only as a raw count.

⸻

24. Unit Testing Strategy

* Exact coordinate lookup (both backends, with backend selection mocked/configured).
* Missing coordinate (`no_data`).
* Non-PASS filter status handling.
* Missing fields / partial records.
* Variant ID construction.
* Input validation failures.
* Resource errors (corrupt local index; simulated network failure for remote).
* Rate-limit bucket invocation (remote backend, mocked).

⸻

25. Mock Testing Strategy

* Remote backend: mocked GraphQL responses (small fixture JSON payloads), no network calls, following the same pattern as VEP's `vep_response_hbb.json` fixture.
* Local backend: small local Tabix-indexed fixture VCF, no network, following the same pattern as AlphaMissense's mock fixture strategy.

⸻

26. Integration Testing Strategy

* Remote backend: live GraphQL queries against the pinned dataset version, marked `@pytest.mark.integration`, automatically skipped if network/API is unavailable — consistent with VEP's integration test pattern.
* Local backend: requires the real downloaded gnomAD index file(s); automatically skipped if unavailable, consistent with the AlphaMissense precedent.
* A cross-backend consistency test (where both backends are available) compares remote vs local results for a small fixed variant set, flagging — but not failing the build on — any discrepancy, since cross-backend drift is itself a useful signal worth logging rather than silently ignoring.

⸻

27. Biological Sanity-Check Strategy

Representative known variants, reused/extended from existing precedent where applicable:

* A common benign coding SNP — expect high `af_overall`.
* A known pathogenic Mendelian-disease allele (e.g., a well-characterized HBB or CFTR pathogenic variant) — expect near-zero or `no_data`.
* A variant with documented high gnomAD homozygote count despite clinical rarity claims, used to verify `n_homozygotes` is faithfully surfaced and not dropped.
* A poorly-covered genomic region — used to verify `filter_status`/`status` correctly signals reduced confidence rather than misrepresenting absence as true absence.

⸻

28. Risks and Trade-offs

* Hybrid architecture means two code paths must be kept behaviorally consistent; cross-backend consistency tests are a partial but not complete mitigation.
* gnomAD release versions are not numerically aligned with Ensembl/VEP releases or AlphaMissense's Zenodo pin — reproducibility across the pipeline depends on each module independently recording its own version, with no single "framework-wide version number" possible at this stage (this is explicitly acceptable per Project Context: output standardization is deferred until all modules are complete).
* Local backend storage scoping (Section 10) adds engineering complexity (chromosome-scoped download/index logic) that does not exist for AlphaMessage's single static file.
* GraphQL query construction is a new pattern for the framework (VEP uses simple REST GET); this is a one-time API-shape complexity cost, not an ongoing risk, once the client is built and tested.

⸻

29. Known Limitations

* SNVs only in v1; indels deferred.
* No exome/genome-specific frequency breakdown in v1, only joint frequencies.
* Local backend does not ship with the module; it requires an explicit, separately-managed download step, scoped to specific chromosomes.
* Ancestry/population labels are limited to whatever gnomAD's own population groupings provide; the module does not reinterpret or remap these.
* Research tool; not a clinical-grade frequency source on its own.

⸻

30. Future Extensibility

* Indel support can be added without breaking the interface, since `annotate(chrom, position, reference, alternate)` already accommodates multi-base reference/alternate strings; only the local-backend parsing and validation rules need extension.
* Exome/genome-specific frequency fields can be added as additional optional output fields without a schema-breaking change.
* A future "ancestry-aware filtering" feature (for modules wanting population-matched frequency thresholds) can be layered on top of `population_frequencies` without any architectural change.
* If a future module needs gene-level constraint metrics (LOEUF) or constraint-based filtering, those remain a separate module per Section 6, not a gnomAD module extension.

⸻

Frozen Architecture

Module:

modules/
└── gnomad/

Public interface:

annotate(
    chrom,
    position,
    reference,
    alternate
)

Two backends behind one interface: `GnomadRemoteClient` (GraphQL, default) and `GnomadLocalClient` (Tabix-indexed VCF, opt-in, chromosome-scoped). Backend selected via configuration, never via call-site branching.

⸻

Frozen Output Schema

GnomadAnnotation dataclass (Section 13). Standard framework annotation envelope, consistent with VEP and AlphaMissense.

⸻

Frozen Data Strategy

Hybrid: gnomAD GraphQL API as default path; local Tabix-indexed VCF as explicit, chromosome-scoped opt-in fallback for large-scale annotation. `shared.indexed_files` reused as-is for the local backend; no new shared abstraction required for indexed lookup itself.

⸻

Frozen Validation Strategy

Shared validation (`validate_variant()`) plus frequency-specific biological sanity testing (Section 27).

⸻

Frozen Testing Strategy

* Unit tests (both backends)
* Mock tests (both backends, fixture-based, no network)
* Integration tests (both backends, auto-skipped if unavailable)
* Cross-backend consistency check (non-blocking)
* Biological sanity tests

⸻

Frozen Versioning Strategy

* Remote: `gnomad_dataset` pinned in `config.yaml` (e.g., `"gnomad_r4"`).
* Local: `VERSION` marker file + SHA256 checksum, identical pattern to AlphaMissense.
* `data_release` and `annotation_source` recorded in every output envelope, regardless of backend.

⸻

Risks

* Dual-backend consistency maintenance burden.
* Version misalignment across modules' independent pinning schemes (acceptable per current Project Context; output standardization deferred).
* Local backend storage scoping complexity (no official slim file, unlike AlphaMissense).
* New GraphQL-shaped API client pattern, distinct from VEP's REST GET pattern.

⸻

Final Recommendations

1. Default to the remote GraphQL backend for the current project stage (module development, biological sanity testing, and small-to-medium batch annotation). This avoids any repeat of the MutPred2-style disk-pressure problem and keeps the module's storage footprint at zero until local annotation is actually needed at scale.
2. Defer building the local backend's download/indexing tooling until the project reaches a scale where remote rate limits become the actual bottleneck — the interface should be designed for it now, but the local backend's file-acquisition tooling does not need to be built in Conversation 5B if time is constrained; `GnomadRemoteClient` alone is sufficient for a GO decision.
3. Treat the named `gnomad_graphql` rate-limit bucket as a required, explicitly-flagged shared-infrastructure addition before implementation (Section 11/19) — small in scope, but it must be added intentionally rather than discovered as a bug later.

⸻

GO / NO-GO Decision

GO, with one explicit shared-infrastructure pre-condition.

Implementation may proceed once:

1. `reference_resources.gnomad` (local backend) and `gnomad_dataset` (remote backend) are added to `config.yaml`, mirroring the AlphaMissense and VEP precedents.
2. A named rate-limit bucket for `gnomad_graphql` is added to the shared rate-limiter configuration (the one identified shared-infrastructure addition — see Section 11).
3. `shared.indexed_files` is confirmed reusable without modification for the local backend (expected to require zero changes, since gnomAD's Tabix-indexed VCF fits the same generic coordinate-lookup contract already proven by AlphaMissense).

Architecture is fully frozen. No additional design work is required before implementation. The local backend's download/acquisition tooling may be scoped down or deferred within Conversation 5B without affecting this GO decision, since the remote backend alone satisfies the module's interface and output contract.
