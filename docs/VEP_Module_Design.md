# VEP Module — Design Review & Production Contract
**Conversation 3A | Status: Design Freeze**

---

## Preamble

This document is the complete deliverable for Conversation 3A. It covers all thirteen discussion points, produces all ten required deliverables, and ends with an explicit go/no-go decision for Conversation 3B (implementation).

The review is based on careful reading of:

- The existing VEP prototype (Python source, attached)
- The shared infrastructure (`shared/http`, `shared/cache`, `shared/validators`, `shared/logging`, `shared/config`, `shared/exceptions`, `shared/reference`)
- The `shared/README.md` quickstart integration pattern
- `PROJECT_CONTEXT.md` and the Conversation 3A brief

---

## Part 1 — Prototype Code Review

### 1.1 What the Prototype Does Well

These are genuine positives that should survive into the production module.

**Correct REST endpoint syntax.** `/vep/human/region/{CHROM}:{POS}-{POS}:1/{ALT}` is the correct VCF-notation region endpoint for GRCh38 SNVs. The trailing `:1` encodes forward-strand orientation and is required.

**Correct server.** `https://rest.ensembl.org` is the correct GRCh38 production server. `https://grch37.rest.ensembl.org` would be the GRCh37 server; using the wrong one would silently return wrong annotations. The prototype gets this right.

**`most_severe_consequence` is the right field.** VEP returns a per-record `most_severe_consequence` field that Ensembl computes across all overlapping transcripts. Using this as the primary consequence field is scientifically correct — it is the single worst consequence seen for the variant regardless of which transcript carries it. This field should be retained.

**`genomic_region` mapping.** The concept of translating VEP SO terms into a coarser structural classification (Coding Exon, Intron, Splicing Junction, UTR, Non-Coding / Intergenic) is sound and scientifically useful. The mapping table is largely correct. This should be retained and completed.

**`transcript_count`.** Recording the total number of transcripts overlapping a variant is genuinely useful metadata for downstream consumers — it signals whether a variant has complex, multi-transcript biology.

**Sensible timeout.** 15 seconds is a reasonable starting value for Ensembl VEP REST; the server occasionally runs slow. This matches the default already in `shared.config`.

---

### 1.2 Critical Defects

These defects make the prototype unsuitable as a production foundation in its current form.

#### Defect C-1 — Raw `requests.get()` instead of `shared.http.HttpClient`

```python
# Prototype — WRONG
import requests
response = requests.get(server + ext, params=params, timeout=15)
```

The prototype bypasses the entire shared HTTP layer. This means:

- No connection pooling (each call opens a new TCP connection to Ensembl).
- No retry with exponential backoff (a transient 500 from Ensembl is returned directly to the caller as an error dict).
- No rate limiting (the framework's 15 req/s token-bucket limiter for `ensembl_vep` is never consulted, risking HTTP 429 responses during batch annotation).
- No structured logging of request duration.
- No `NetworkError` / `RateLimitError` exception raising — errors are silently returned as dicts.

The correct pattern, shown explicitly in `shared/README.md`, is `HttpClient.for_service("ensembl_vep")`.

#### Defect C-2 — Wrong transcript selection: `transcript_consequences[0]`

```python
# Prototype — WRONG
primary_tx = transcript_consequences[0]
gene_symbol = primary_tx.get("gene_symbol", "Unknown")
amino_acids = primary_tx.get("amino_acids", "None")
```

This is the most important biological defect in the prototype.

`transcript_consequences` is an unordered (from a clinical relevance perspective) list of every transcript overlapping the variant. Ensembl's internal ordering does not guarantee that the first entry is the most important transcript. In practice, index 0 may be a non-coding transcript, a pseudogene, or a transcript of lower confidence, while the MANE Select protein-coding transcript is at index 5.

`PROJECT_CONTEXT.md` explicitly states: *"Never choose `transcript_consequences[0]` without explicit transcript selection."*

Production must implement:

```
MANE Select transcript   →  if present in response
     ↓ fallback
Ensembl Canonical transcript  →  if canonical=1 flag present
     ↓ fallback (with warning log)
transcript_consequences[0]    →  last resort only, logged as WARNING
```

This requires adding `mane_select=1&canonical=1` to the API request so the response includes these flags.

#### Defect C-3 — String input interface instead of `annotate(chrom, position, reference, alternate)`

```python
# Prototype — WRONG
def get_vep_consequences_grch38(variant_str):
    parts = variant_str.strip().split()
    chrom, pos, ref, alt = parts
```

The canonical module interface defined in `PROJECT_CONTEXT.md` is:

```python
annotate(chrom: str, position: int, reference: str, alternate: str) -> VEPAnnotation
```

The string-parsing approach is fragile (extra whitespace, tabs, different separators would all break it), inconsistent with every other module in the framework, and bypasses `shared.validators.validate_variant()`.

#### Defect C-4 — Error handling via returned dict instead of framework exceptions

```python
# Prototype — WRONG
if len(parts) != 4:
    return {"error": "Invalid variant format..."}
...
except Exception as e:
    return {"error": f"VEP API f eature extraction failed: {str(e)}"}
```

Problems:

- Returns a dict on error instead of raising — callers cannot distinguish a real annotation from an error without inspecting keys, which breaks any downstream consumer.
- `except Exception as e` is a bare catch-all that swallows `KeyboardInterrupt`, `SystemExit`, and legitimate programming errors alongside genuine API failures.
- There is a typo: `"VEP API f eature extraction failed"` (literal space in "feature"). This will appear in any error log.
- No distinction between `ValidationError`, `NetworkError`, `RateLimitError`, or `AnnotationUnavailableError` — the framework's entire exception taxonomy is unused.

Production must raise, never return on error:

```python
from shared.exceptions import ValidationError, AnnotationUnavailableError, NetworkError
```

#### Defect C-5 — No `shared.validators.validate_variant()` call

Input validation is completely absent. The prototype does not verify that the chromosome is a valid GRCh38 chromosome name, that the position is a positive integer, or that the alleles contain only valid IUPAC bases. Malformed input passes silently to the API, which may return an ambiguous error or (worse) a spurious annotation.

#### Defect C-6 — No `shared.cache` integration

Every call to `annotate()` hits the Ensembl REST API. For a pipeline annotating thousands of variants, this wastes API quota, increases latency, and makes results non-reproducible across runs if Ensembl releases a new annotation update mid-batch. `shared.cache.DiskCache` already exists and is purpose-built for this use case.

#### Defect C-7 — No `shared.logging` integration

There are zero log calls in the prototype. No variant being annotated is logged, no API latency is recorded, no cache hit/miss is recorded, no transcript selection decision is recorded. All of this is needed for debugging and performance profiling across a 12-module pipeline.

#### Defect C-8 — Hardcoded URL and timeout (not from `shared.config`)

```python
# Prototype — WRONG
server = "https://rest.ensembl.org"
...
response = requests.get(..., timeout=15)
```

Both the base URL and timeout are already defined in `shared.config` under the `ensembl_vep` service key (`base_url`, `timeout_seconds`). Hardcoding them here means: (a) changing the config doesn't affect the VEP module, and (b) the module cannot be tested against a mock server by overriding config.

---

### 1.3 Important Defects

These defects do not make the prototype wrong in principle but must be corrected before production.

#### Defect I-1 — Missing mandatory output fields

The prototype returns 6 fields. The production contract (see Part 6) specifies 22. Critical missing fields:

- `hgvs_c` — HGVS coding DNA notation (e.g. `NM_000546.6:c.817C>T`). Required by all downstream modules that report or cross-reference variants in clinical notation. VEP returns this when `hgvs=1` is added to the request.
- `hgvs_p` — HGVS protein notation (e.g. `NP_000537.3:p.Arg273Cys`). Required by AlphaMissense and InterVar.
- `gene_id` — Ensembl ENSG ID. Stable across releases; required by GTEx, STRING, and GWAS modules which use gene IDs rather than gene symbols.
- `transcript_id` — the ENST ID of the selected transcript. Required for provenance and downstream interpretation.
- `transcript_source` — which rule produced the selected transcript (`"mane_select"`, `"ensembl_canonical"`, or `"fallback"`). Required for downstream quality assessment.
- `impact` — VEP's severity tier: `HIGH`, `MODERATE`, `LOW`, or `MODIFIER`. Required by InterVar.
- `biotype` — transcript biotype (`protein_coding`, `lncRNA`, etc.). Required for filtering by downstream consumers.
- `exon_number` / `intron_number` — position within the gene structure. VEP returns these when `numbers=1` is added to the request.
- `codon_change` — the DNA codon change (e.g. `Cgt/Tgt`). Useful for InterVar and clinical reporting.
- `ensembl_release` — the Ensembl release used. Required for reproducibility. Must come from `shared.config`.

#### Defect I-2 — `content-type` sent as a query parameter, not a header

```python
# Prototype — WRONG
params = {"content-type": "application/json"}
response = requests.get(server + ext, params=params, ...)
```

This sends `?content-type=application%2Fjson` as a URL query parameter. It is not a header. The Ensembl REST API happens to be lenient enough to accept this on some endpoints, but it is incorrect HTTP. `shared.http.HttpClient` sets `Accept: application/json` as a default header automatically — this line should simply be deleted and the shared client used instead.

#### Defect I-3 — Missing API parameters for production features

The prototype sends no parameters beyond the `content-type` quirk. The production request must include:

- `hgvs=1` — to receive HGVS notation.
- `mane_select=1` — to receive MANE Select flags on transcript entries.
- `canonical=1` — to receive Ensembl Canonical flags for the fallback policy.
- `numbers=1` — to receive exon/intron position numbers.

#### Defect I-4 — String `"None"` stored as the amino acid value

```python
amino_acids = primary_tx.get("amino_acids", "None")
```

The default is the string `"None"`, not Python `None`. This breaks any downstream check for missing data (`if result["amino_acid_change"] is None` would fail). Per `PROJECT_CONTEXT.md`: *"Missing annotations are represented explicitly. Use `None`. Never silently remove variants."*

#### Defect I-5 — Empty API response assumed to be intergenic

```python
# Prototype — WRONG
return {
    "variant_id": ...,
    "most_severe_consequence": "intergenic_variant",
    "genomic_region": "Non-Coding / Intergenic"
}
```

When `data` is empty or not a list, the prototype silently returns `"intergenic_variant"`. An empty VEP response could mean the variant is truly intergenic, or it could mean a malformed query, a coordinate outside any scaffold, or an API glitch. These cases must be distinguished. The production module must raise `AnnotationUnavailableError` on empty responses rather than asserting a biological conclusion.

#### Defect I-6 — Incomplete `genomic_region` SO term coverage

The region map is missing several VEP SO terms that appear in real annotations:

- `stop_retained_variant` (synonymous variant at stop codon)
- `start_retained_variant`
- `protein_altering_variant`
- `incomplete_terminal_codon_variant`
- `NMD_transcript_variant` (Nonsense-Mediated Decay target)
- `mature_miRNA_variant`
- `TFBS_ablation`, `TFBS_amplification`
- `regulatory_region_ablation`, `regulatory_region_amplification`

Any SO term not in the map falls back to `"Other / Unclassified"`, which is an acceptable fallback but should not happen for well-known terms.

---

### 1.4 Optional Improvements

#### Defect O-1 — Missing `strand` field
VEP returns strand (`1` or `-1`). Useful context, especially for intronic and UTR variants where upstream/downstream meaning flips.

#### Defect O-2 — Missing positional fields
`cdna_position`, `cds_position`, `protein_position` are returned by VEP and are occasionally needed by downstream modules.

#### Defect O-3 — `variant_id` uses hyphens (`CHROM-POS-REF-ALT`)
The framework's canonical variant ID format (per `shared.validators.CanonicalVariant.variant_id`) uses colons (`CHROM:POS:REF:ALT`). The prototype uses hyphens. All modules should use the same separator.

#### Defect O-4 — No Ensembl release pinning in `shared.config`
`versions.ensembl_release` and `versions.vep_version` are `null` in the example config. These must be pinned before the module ships.

---

## Part 2 — Frozen Scientific Contract

### 2.1 VEP's Role in the Framework

VEP is the primary **consequence annotation module**. Its responsibility is to answer, for any GRCh38 SNV:

- What gene does this variant affect?
- What type of molecular consequence does it produce?
- How severely does it disrupt the affected transcript?
- At what position within the gene structure (exon, intron, codon, protein) is the change?
- What is the canonical molecular notation (HGVS.c, HGVS.p)?

VEP is the structural foundation. Every downstream module that needs to know "is this coding? is this in a splice site? what gene?" depends on VEP output. It must be correct, comprehensive, and stable.

### 2.2 Biological Scope: What VEP Owns

| Field | Rationale |
|---|---|
| Gene symbol (HGNC) | Identity of the affected gene |
| Gene ID (ENSG) | Stable gene identifier for cross-module joins |
| Most severe consequence (SO term) | Primary functional consequence |
| Impact tier (HIGH/MODERATE/LOW/MODIFIER) | Severity classification |
| Genomic region (simplified) | Structural context for ML feature generation |
| Selected transcript (ENST) | Canonical transcript identity |
| Transcript source | Which policy produced the selection |
| Biotype | Whether the selected transcript is protein-coding |
| HGVS.c | Coding DNA change in standard notation |
| HGVS.p | Protein change in standard notation |
| Amino acid change | In / out notation (e.g. `R/C`) |
| Codon change | DNA-level codon substitution |
| Exon / intron number | Position within gene structure |
| Strand | Genomic orientation |
| Transcript count | Breadth of the variant's transcriptomic impact |
| Provenance metadata | Ensembl release, VEP version |

### 2.3 Biological Scope: What VEP Does NOT Own

VEP must **never** return or re-expose the following. These belong to dedicated modules. The production code must explicitly suppress them even when the Ensembl REST API returns them inside the response body.

| Information | Owner module | Why not VEP |
|---|---|---|
| PolyPhen-2 score | (not in scope — superseded by AlphaMissense) | VEP REST returns it by default for missense; must be ignored |
| SIFT score | (not in scope — superseded by AlphaMissense) | Same as above |
| AlphaMissense pathogenicity | AlphaMissense (Module 2) | Dedicated module with richer context |
| CADD score | Not in current module set | Would belong to a future module |
| REVEL score | Not in current module set | Would belong to a future module |
| dbNSFP fields | Not in current module set | Would belong to a future module |
| SpliceAI scores | SpliceAI (Module 4) | Dedicated module |
| GERP++ scores | GERP++ (Module 4) | Dedicated module |
| LOEUF / pLI | LOEUF (Module 5) | Dedicated module |
| LOFTEE LoF classification | (overlaps with LOEUF module) | Dedicated module |
| Population allele frequencies | gnomAD (Module 3) | Dedicated module |
| Clinical pathogenicity | InterVar (Module 6) | Dedicated module |
| Protein structure | AlphaFold (Module 9) | Dedicated module |
| Gene–gene interactions | STRING (Module 11) | Dedicated module |
| GWAS associations | GWAS Catalog (Module 12) | Dedicated module |

The practical implication: the production VEP module will receive a JSON response from Ensembl that may contain PolyPhen, SIFT, and regulatory-consequence fields. These must be read but not re-exposed in the output schema. They must not be cached in a way that masquerades them as VEP's own output.

---

## Part 3 — Frozen Engineering Contract

### 3.1 Module Identity

```
Module name:        vep
Module tier:        Tier 1 (Essential)
Directory:          modules/vep/
Public entrypoint:  annotate(chrom, position, reference, alternate)
Return type:        VEPAnnotation (dataclass)
```

### 3.2 Mandatory Infrastructure Usage

| Component | Usage |
|---|---|
| `shared.validators.validate_variant()` | First call inside `annotate()`, before any other work |
| `shared.http.HttpClient.for_service("ensembl_vep")` | Only HTTP client; no bare `requests` calls anywhere |
| `shared.cache.DiskCache` | Persistent cross-run cache keyed on validated variant coordinates |
| `shared.cache.MemoryCache` | Optional L1 cache for within-run repeated lookups |
| `shared.logging.get_logger(__name__)` | Module-level logger; log at DEBUG for cache operations, INFO for annotations, WARNING for transcript fallbacks |
| `shared.config.get_config()` | Source of base URL, timeout, max_retries, rate_limit, cache_dir, ensembl_release |
| `shared.exceptions` | Only exception types the module may raise |
| `shared.reference` | Query for Ensembl resource status/version at module init |

### 3.3 What Must Never Be Implemented Independently

The VEP module must never contain its own:

- HTTP session, connection pool, or `requests` import at module level
- Retry loop
- Rate limiter or sleep/throttle logic
- Cache store (dict, file, database)
- File logger or formatter
- Config parser or YAML reader
- Chromosome normalization logic (use `shared.validators.normalize_chrom()`)

---

## Part 4 — Frozen API Contract

### 4.1 Endpoint

```
GET https://rest.ensembl.org/vep/human/region/{CHROM}:{POS}-{POS}:1/{ALT}
```

This is the correct VCF-notation region endpoint for GRCh38 SNVs. The `1` encodes forward-strand orientation; VEP correctly handles reverse-strand genes regardless of this parameter. For indels (future consideration), the position range `{POS}-{END}` and alt notation must be adjusted.

### 4.2 Required Query Parameters

```
hgvs=1          HGVS.c and HGVS.p notation on transcript entries
mane_select=1   MANE Select flag on relevant transcripts
canonical=1     Ensembl Canonical flag for the fallback policy
numbers=1       Exon and intron position numbers
```

### 4.3 Required Headers

```
Accept: application/json
```

This is already set as `default_headers` by `HttpClient`. No additional `content-type` parameter should be sent. The prototype's `params={"content-type": "application/json"}` query parameter must be removed.

### 4.4 Configuration (from `shared.config`)

```yaml
services:
  ensembl_vep:
    base_url: "https://rest.ensembl.org"
    timeout_seconds: 15
    max_retries: 4
    rate_limit_per_second: 15
```

`timeout_seconds` of 15 is appropriate. The Ensembl REST API for VEP occasionally takes 5–10 seconds for complex loci. `max_retries` of 4 with exponential backoff (already implemented in `shared.http.retry`) is appropriate for transient 5xx responses.

The rate limit of 15 requests/second matches Ensembl's documented public API limit. Burst exceeding this triggers HTTP 429, which `HttpClient` already classifies as `RateLimitError`.

### 4.5 Release Pinning

Before Conversation 3B begins, the following must be set in `config.yaml`:

```yaml
versions:
  ensembl_release: "113"   # or current release at implementation time
  vep_version: "113.0"     # confirm via /info/software endpoint at startup
```

Ensembl releases quarterly. An annotation produced against release 110 may differ from one produced against release 113 for the same variant (e.g. new MANE Select designations, updated transcript models). The module must record which release produced the annotation.

### 4.6 Error Response Handling

| HTTP Status | Interpretation | Framework Action |
|---|---|---|
| 200 | Success | Parse and return |
| 400 | Malformed request (bad coordinates, unsupported allele) | Raise `ValidationError` with the Ensembl error message |
| 404 | Variant coordinate not found in GRCh38 | Raise `AnnotationUnavailableError` |
| 429 | Rate limit exceeded | `HttpClient` raises `RateLimitError`; handled by retry layer |
| 500–503 | Transient server error | `HttpClient` raises `NetworkError`; handled by retry layer |
| Empty body (200 with `[]`) | No annotation at locus | Raise `AnnotationUnavailableError` |

A 400 from Ensembl VEP typically means the position does not exist on GRCh38 or the allele is malformed. This is a biological "no data" condition, not a network failure. It must raise `AnnotationUnavailableError`, not `NetworkError`.

### 4.7 Future Compatibility

Ensembl periodically updates the VEP REST API. To reduce breakage risk:

- Never parse the response by integer index. Always access fields by name (`.get("key")`).
- Never assume a field is present. Every field access uses `.get()` with a `None` default.
- Record the Ensembl release in every cached result. If the pinned release is updated, the cache TTL should be configured to expire (or the cache should be explicitly invalidated).
- The module should log the Ensembl REST software version (`/info/software` endpoint) at startup and emit a WARNING if it differs from the pinned version in config.

---

## Part 5 — Frozen Transcript Policy

### 5.1 The Problem with `transcript_consequences[0]`

The Ensembl VEP REST API returns a list of `transcript_consequences` — one entry per overlapping transcript. For a typical coding gene, this list may contain 5–20 entries: protein-coding isoforms, non-coding splice variants, retained intron transcripts, and so on. The ordering is determined by Ensembl's internal transcript model ordering, which has no documented clinical priority.

Using `transcript_consequences[0]` is equivalent to picking a random transcript. The gene symbol and amino acid change returned could come from a non-coding transcript, a low-confidence isoform, or a pseudogene overlay, while the clinically relevant MANE Select transcript is elsewhere in the list.

### 5.2 Frozen Transcript Selection Policy

```
Step 1: Search transcript_consequences for entries where
        "mane_select" key is present (requires mane_select=1 in request)
        → Use first match.

Step 2: If no MANE Select transcript found, search for entries where
        "canonical" == 1 (requires canonical=1 in request)
        → Use first match.
        → Log at INFO: "No MANE Select transcript; using Ensembl Canonical"

Step 3: If no canonical transcript found, use transcript_consequences[0]
        → Log at WARNING: "No MANE Select or Canonical transcript;
          falling back to transcript_consequences[0]. Variant: {id}"

Record the selection rule in transcript_source field:
    "mane_select" | "ensembl_canonical" | "fallback"
```

### 5.3 Biological Importance of MANE Select

MANE (Matched Annotation from NCBI and EMBL-EBI) is the joint NCBI/Ensembl-EBI designation of the single most clinically important transcript per human gene. It was introduced precisely because the multiplicity of transcript models from RefSeq and Ensembl caused inconsistency in clinical reporting and database cross-referencing.

Why MANE Select matters for this framework:

- Clinical databases (ClinVar, HGMD, GnomAD) report variants in MANE Select coordinates. If VEP reports a different transcript, downstream cross-referencing with InterVar and gnomAD becomes ambiguous.
- AlphaMissense pathogenicity scores are tied to specific protein sequences. Using a non-MANE transcript for HGVS.p notation, then querying AlphaMissense with that notation, may return a score for the wrong isoform.
- SpliceAI scores are per-gene and per-position; using a non-canonical transcript changes the exon-intron structure and thus the position interpretation.
- ML feature consistency across variants: if some variants use MANE Select and others use arbitrary transcripts, the `exon_number`, `hgvs_p`, and `amino_acid_change` fields become incomparable, undermining ML training.

### 5.4 MANE Select Availability

MANE Select coverage as of Ensembl 110+: approximately 98% of protein-coding genes with a RefSeq counterpart have a MANE Select designation. The fallback to Ensembl Canonical covers the remaining ~2% (novel genes, very small genes, genes under active annotation dispute). The final fallback to `[0]` is a safety net that should essentially never fire for protein-coding genes; it is retained only for pathological edge cases and must always generate a WARNING log.

---

## Part 6 — Frozen Output Schema

### 6.1 `VEPAnnotation` Dataclass

The production module returns a `VEPAnnotation` dataclass (not a plain dict). All fields with `Optional[str]` default to `None` when absent from the API response.

```python
@dataclass(frozen=True)
class VEPAnnotation:

    # --- Variant identity (from input, validated) ---
    variant_id: str          # "CHROM:POS:REF:ALT" (colon-separated, canonical)
    chrom: str
    position: int
    reference: str
    alternate: str
    genome_build: str        # always "GRCh38"

    # --- Gene context ---
    gene_symbol: Optional[str]       # HGNC symbol, e.g. "TP53"
    gene_id: Optional[str]           # Ensembl gene ID, e.g. "ENSG00000141510"
    biotype: Optional[str]           # "protein_coding", "lncRNA", etc.
    strand: Optional[int]            # 1 (forward) or -1 (reverse)

    # --- Primary consequence ---
    most_severe_consequence: Optional[str]   # SO term, e.g. "missense_variant"
    impact: Optional[str]                    # "HIGH" | "MODERATE" | "LOW" | "MODIFIER"
    genomic_region: Optional[str]            # simplified region classification (see §6.2)

    # --- Selected transcript ---
    transcript_id: Optional[str]       # ENST ID of selected transcript
    transcript_source: Optional[str]   # "mane_select" | "ensembl_canonical" | "fallback"
    transcript_count: int              # total transcripts overlapping this variant

    # --- HGVS notation ---
    hgvs_c: Optional[str]    # e.g. "NM_000546.6:c.817C>T"
    hgvs_p: Optional[str]    # e.g. "NP_000537.3:p.Arg273Cys"

    # --- Amino acid / codon level ---
    amino_acid_change: Optional[str]   # e.g. "R/C"
    codon_change: Optional[str]        # e.g. "Cgt/Tgt"

    # --- Positional ---
    exon_number: Optional[str]    # e.g. "6/11" (exon 6 of 11)
    intron_number: Optional[str]  # e.g. "4/10"

    # --- Provenance ---
    ensembl_release: Optional[str]          # e.g. "113"
    annotation_source: str = "ensembl_vep_rest"

    # --- Status ---
    status: str    # "ok" | "no_data" | "cache_hit"
```

### 6.2 Frozen `genomic_region` Mapping

```python
GENOMIC_REGION_MAP: dict[str, str] = {
    # Coding exon
    "missense_variant":                     "Coding Exon",
    "synonymous_variant":                   "Coding Exon",
    "stop_gained":                          "Coding Exon",
    "stop_lost":                            "Coding Exon",
    "stop_retained_variant":                "Coding Exon",
    "start_lost":                           "Coding Exon",
    "start_retained_variant":               "Coding Exon",
    "frameshift_variant":                   "Coding Exon",
    "inframe_insertion":                    "Coding Exon",
    "inframe_deletion":                     "Coding Exon",
    "coding_sequence_variant":              "Coding Exon",
    "protein_altering_variant":             "Coding Exon",
    "incomplete_terminal_codon_variant":    "Coding Exon",

    # Splicing
    "splice_acceptor_variant":  "Splicing Junction",
    "splice_donor_variant":     "Splicing Junction",
    "splice_donor_5th_base_variant": "Splicing Junction",
    "splice_donor_region_variant":   "Splicing Junction",
    "splice_polypyrimidine_tract_variant": "Splicing Junction",
    "splice_region_variant":    "Splicing Junction",

    # Intronic
    "intron_variant":           "Intron",
    "NMD_transcript_variant":   "Intron",

    # UTR
    "5_prime_utr_variant":      "Untranslated Region (5' UTR)",
    "3_prime_utr_variant":      "Untranslated Region (3' UTR)",

    # Non-coding RNA
    "non_coding_transcript_exon_variant":   "Non-Coding RNA",
    "non_coding_transcript_variant":        "Non-Coding RNA",
    "mature_miRNA_variant":                 "Non-Coding RNA",

    # Regulatory
    "regulatory_region_variant":        "Regulatory",
    "regulatory_region_ablation":       "Regulatory",
    "regulatory_region_amplification":  "Regulatory",
    "TF_binding_site_variant":          "Regulatory",
    "TFBS_ablation":                    "Regulatory",
    "TFBS_amplification":               "Regulatory",

    # Intergenic / flanking
    "upstream_gene_variant":    "Non-Coding / Intergenic",
    "downstream_gene_variant":  "Non-Coding / Intergenic",
    "intergenic_variant":       "Non-Coding / Intergenic",
}

GENOMIC_REGION_DEFAULT = "Other / Unclassified"
```

The prototype's grouping of 5' UTR and 3' UTR into a single `"Untranslated Region (UTR)"` category is split in the production schema because these have different biological significance: 5' UTR variants can affect translation initiation; 3' UTR variants affect mRNA stability, polyadenylation, and miRNA binding. They should be distinguishable in the ML feature set.

### 6.3 Missing Value Representation

Per `PROJECT_CONTEXT.md`: all missing values are `None` (Python). Never use string `"None"`, `"Unknown"`, `"N/A"`, or `""` to represent absence. The dataclass uses `Optional[str]` / `Optional[int]` defaults of `None` everywhere.

The exception: `transcript_count` defaults to `0` (int) when `transcript_consequences` is absent or empty, because 0 is the correct semantic value (no transcripts overlapped).

### 6.4 Standard Output Envelope

The module wraps its `VEPAnnotation` in the standard framework envelope before caching and returning:

```python
{
    "variant_id":     variant.variant_id,
    "module_name":    "vep",
    "status":         "ok" | "no_data" | "cache_hit",
    "fields":         annotation.to_dict(),   # VEPAnnotation serialized
    "source_version": ensembl_release,
}
```

This matches the pattern shown in `shared/README.md`.

---

## Part 7 — Frozen Validation Strategy

Biological validation (sanity checking with known variants) must be performed as a named test in the test suite. The following variants are frozen as the biological validation set.

### 7.1 Positive Controls — Well-Characterised Missense

| Variant | Coordinates (GRCh38) | Expected consequence | Expected gene | Expected impact | Notes |
|---|---|---|---|---|---|
| HBB E6V (Sickle cell) | `11:5227002:T:A` | missense_variant | HBB | MODERATE | Prototype test case; strong positive control |
| TP53 R175H | `17:7674220:C:T` | missense_variant | TP53 | MODERATE | Most common TP53 hotspot mutation |
| APOE rs429358 | `19:44908684:T:C` | missense_variant | APOE | MODERATE | Major longevity/AD variant |
| LDLR W515G | `19:11089875:T:G` | missense_variant | LDLR | MODERATE | FH-associated missense |

### 7.2 Positive Controls — High Impact

| Variant | Coordinates (GRCh38) | Expected consequence | Expected gene | Expected impact |
|---|---|---|---|---|
| BRCA1 c.5266dupC | `17:43057051:C:CA` | frameshift_variant | BRCA1 | HIGH |
| CFTR F508del | `7:117548628:CTT:-` | inframe_deletion | CFTR | MODERATE |
| LDLR splice donor | `19:11089208:G:A` | splice_donor_variant | LDLR | HIGH |

### 7.3 Negative Controls

| Variant | Expected consequence | Purpose |
|---|---|---|
| Known intergenic SNP (deep desert: chr8:144 500 000) | intergenic_variant | Verify intergenic handling |
| Synonymous SNV in well-characterised gene | synonymous_variant | Verify LOW impact assignment |

### 7.4 Edge Cases

| Case | Test input | Expected behaviour |
|---|---|---|
| MT chromosome | `MT:1555:A:G` | Must annotate correctly (MT is supported by Ensembl VEP) |
| X chromosome | `X:154000000:A:G` | Must annotate correctly |
| Invalid chromosome | `chr99:1000:A:G` | Must raise `ValidationError` before any API call |
| Non-ACGT allele | `1:1000000:A:<DEL>` | Must raise `ValidationError` before any API call |
| Position zero | `1:0:A:G` | Must raise `ValidationError` (1-based coordinates required) |
| Multi-allelic | `1:1000000:A:G,T` | Must raise `ValidationError` (multi-allelic must be split upstream) |

### 7.5 MANE Select Validation

A separate test must confirm that the transcript selection policy fires correctly. Recommend:

- BRCA2 (many transcripts; MANE Select is well-established): confirm `transcript_source == "mane_select"`.
- A rare gene with no MANE Select: confirm fallback to `transcript_source == "ensembl_canonical"`.
- Mock a response with neither flag: confirm fallback to `"fallback"` and that a WARNING is logged.

---

## Part 8 — Frozen Testing Strategy

### 8.1 Unit Tests

These tests run offline. They mock the `HttpClient` and never make real network calls.

| Test | What it validates |
|---|---|
| `test_validate_variant_invalid_chrom` | `ValidationError` raised for chr99, chrZ, empty string |
| `test_validate_variant_invalid_position` | `ValidationError` for 0, negative, non-integer |
| `test_validate_variant_invalid_allele` | `ValidationError` for symbolic alleles, empty string, non-ACGT |
| `test_genomic_region_map_completeness` | Every entry in `GENOMIC_REGION_MAP` maps to a known region string |
| `test_genomic_region_fallback` | Unknown SO term maps to `"Other / Unclassified"` |
| `test_transcript_selection_mane_select` | MANE Select transcript chosen when present in mock response |
| `test_transcript_selection_canonical_fallback` | Canonical chosen when MANE Select absent |
| `test_transcript_selection_index0_fallback` | `[0]` chosen when neither flag present; WARNING is logged |
| `test_missing_fields_are_none` | Fields absent from API response become `None`, not string `"None"` |
| `test_variant_id_format` | `variant_id` uses colon separator, not hyphen |
| `test_empty_response_raises` | Empty `[]` response raises `AnnotationUnavailableError` |
| `test_400_raises_annotation_unavailable` | HTTP 400 raises `AnnotationUnavailableError` |
| `test_404_raises_annotation_unavailable` | HTTP 404 raises `AnnotationUnavailableError` |
| `test_5xx_raises_network_error` | HTTP 500 raises `NetworkError` (already handled by `HttpClient`) |
| `test_output_envelope_keys` | Return dict contains `variant_id`, `module_name`, `status`, `fields`, `source_version` |
| `test_utr_split` | 5' UTR and 3' UTR map to distinct `genomic_region` strings |

### 8.2 Integration Tests (require live API; skipped by default)

Mark with `@pytest.mark.integration`. Run only with `pytest -m integration`.

| Test | What it validates |
|---|---|
| `test_hbb_sickle_cell_live` | HBB E6V returns missense_variant, gene=HBB, MANE Select transcript |
| `test_tp53_r175h_live` | TP53 R175H returns expected consequence, HGVS.p, amino acid change |
| `test_brca1_frameshift_live` | BRCA1 frameshift returns frameshift_variant, HIGH impact |
| `test_intergenic_live` | Deep intergenic variant returns intergenic_variant, gene=None |
| `test_mt_chromosome_live` | MT:1555:A:G annotates without error |
| `test_hgvs_fields_present` | At least one coding variant returns non-None `hgvs_c` and `hgvs_p` |
| `test_mane_select_present_on_brca2` | BRCA2 variant returns `transcript_source == "mane_select"` |

### 8.3 Cache Behaviour Tests

| Test | What it validates |
|---|---|
| `test_cache_hit_skips_api` | Second call returns cache result; HTTP client is not called |
| `test_cache_key_determinism` | Same variant always produces the same cache key |
| `test_cache_miss_calls_api` | Cache miss calls HTTP client exactly once |
| `test_cache_miss_then_set` | After a cache miss, result is stored; next call is a hit |
| `test_cache_error_does_not_crash` | `CacheError` on read is logged as WARNING and falls through to API |

### 8.4 Mock REST Tests

Using `responses` library (already used in `shared/tests/`):

| Test | Mock scenario |
|---|---|
| `test_retry_on_500` | Mock 500 twice then 200; confirm result returned after retries |
| `test_rate_limit_429` | Mock 429; confirm `RateLimitError` eventually raised |
| `test_timeout_handling` | Mock timeout; confirm `NetworkError` raised |
| `test_full_response_parsing` | Provide a realistic full VEP JSON response; confirm all output fields populated correctly |
| `test_partial_response_parsing` | Response missing `hgvs_c`; confirm `hgvs_c=None`, no crash |

---

## Part 9 — Future Integration Guide

### 9.1 Fields Other Modules Will Consume From VEP

This table describes the dependency relationship. VEP must produce these fields correctly or downstream modules will silently use wrong data.

| Downstream Module | Fields consumed from VEP | Why |
|---|---|---|
| **AlphaMissense (2)** | `hgvs_p`, `gene_symbol`, `gene_id`, `biotype`, `most_severe_consequence` | AlphaMissense queries by gene + protein change; needs to confirm the variant is a missense in a protein-coding gene |
| **gnomAD (3)** | `variant_id`, `chrom`, `position`, `reference`, `alternate` | gnomAD is queried by variant coordinates; these come from VEP's validated/canonical input |
| **GERP++ (4)** | `chrom`, `position`, `genomic_region`, `biotype` | GERP++ conservation is position-based; biotype helps contextualise conservation scores |
| **LOEUF (5)** | `gene_id`, `gene_symbol`, `biotype` | LOEUF/pLI are per-gene metrics; queried by ENSG ID |
| **InterVar (6)** | `most_severe_consequence`, `impact`, `hgvs_c`, `hgvs_p`, `exon_number`, `genomic_region`, `transcript_id` | InterVar implements ACMG criteria. PVS1 (null variant) requires `impact == "HIGH"` and `most_severe_consequence` in {`stop_gained`, `frameshift_variant`, `splice_acceptor_variant`, `splice_donor_variant`}. PS1/PM5 require `hgvs_p`. PM4 requires `inframe_insertion` / `inframe_deletion`. |
| **SpliceAI (7)** | `chrom`, `position`, `reference`, `alternate`, `gene_symbol`, `genomic_region` | SpliceAI needs coordinates and optionally a gene context hint; genomic_region signals whether to prioritise splice prediction |
| **MutPred (8)** | `hgvs_p`, `gene_symbol`, `amino_acid_change`, `biotype` | MutPred operates on protein sequences; only meaningful for `biotype == "protein_coding"` and `impact in {"HIGH", "MODERATE"}` |
| **AlphaFold + DynaMut2 (9)** | `gene_id`, `protein_position`, `amino_acid_change`, `biotype` | Structural analysis is meaningful only for protein-coding missense; protein position maps to structure |
| **GTEx (10)** | `gene_id`, `chrom`, `position`, `genomic_region` | GTEx eQTL queries are by gene + position; genomic_region distinguishes coding from regulatory context |
| **STRING (11)** | `gene_id`, `gene_symbol` | STRING queries by gene ID for PPI network context |
| **GWAS Catalog (12)** | `chrom`, `position`, `reference`, `alternate` | GWAS associations are queried by variant coordinates |

### 9.2 Mandatory Fields for Downstream Safety

The following fields, if `None` in VEP output, will silently produce empty/null annotations in downstream modules. They are mandatory for the pipeline to be useful. If VEP cannot populate them for a given variant (e.g., intergenic variant has no `gene_id`), this is expected and must not be treated as a VEP module failure — but it must be reflected as `None` in the output (not omitted, not `"Unknown"`).

`gene_id`, `gene_symbol`, `most_severe_consequence`, `impact`, `biotype`, `hgvs_p` (for missense), `transcript_id`

### 9.3 Conditional Consumption Logic

Downstream modules must check these VEP fields before proceeding:

```python
# AlphaMissense — only meaningful for protein-coding missense
if (
    vep.biotype == "protein_coding"
    and vep.most_severe_consequence == "missense_variant"
    and vep.hgvs_p is not None
):
    run_alphamissense(vep.hgvs_p)

# MutPred / AlphaFold — only meaningful for protein-coding, moderate+ impact
if (
    vep.biotype == "protein_coding"
    and vep.impact in {"HIGH", "MODERATE"}
    and vep.protein_position is not None
):
    run_mutpred(vep.gene_symbol, vep.amino_acid_change)

# InterVar PVS1 — loss-of-function gating
if vep.impact == "HIGH":
    intervar_set_pvs1_candidate()
```

These conditional patterns are downstream responsibilities, but VEP must produce the fields they depend on reliably.

---

## Part 10 — Plugin Policy

### 10.1 Plugins That Must Never Appear in VEP Output

The Ensembl VEP REST API may return PolyPhen and SIFT scores for human missense variants even without explicit plugin activation, because they are built into the public server configuration. The production VEP module must:

1. **Not expose** these fields in `VEPAnnotation`.
2. **Not cache** them in the `fields` block of the output envelope with names suggesting they are VEP's own output.
3. **Document** in the module README that these fields exist in the raw API response but are intentionally suppressed.

| Plugin / field | Why excluded |
|---|---|
| PolyPhen-2 (polyphen_score, polyphen_prediction) | Superseded by AlphaMissense for this framework; would duplicate Module 2 |
| SIFT (sift_score, sift_prediction) | Same rationale |
| CADD (cadd_phred, cadd_raw) | No CADD module in current roadmap; including it without a dedicated module creates orphan data |
| REVEL | Same rationale as CADD |
| dbNSFP (all fields) | No dedicated module; would create orphan data |
| LOFTEE (lof, lof_flags, lof_filter) | Overlaps with LOEUF module (Module 5); LOEUF module will own LoF assessment |
| SpliceAI (if returned as a plugin) | Module 7 owns this |

### 10.2 Storing Raw Response for Future Access

The production cache should store the **raw API JSON** (the full `data[0]` object), not only the parsed `VEPAnnotation` fields. This ensures that if a future module needs a field VEP suppressed (e.g., a future CADD module that wants the CADD score that was already returned in VEP's response), it can be accessed by reading the raw cache without re-querying the API.

The raw response is stored at a separate key, not in the public output envelope:

```python
# Cache the raw API response separately for future access
cache.set(make_key("vep_raw", variant.variant_id), raw_api_response)

# Cache the parsed, framework-conforming output for normal consumption
cache.set(make_key("vep", variant.variant_id), output_envelope)
```

---

## Part 11 — Frozen Caching Contract

### 11.1 Cache Design

| Property | Decision |
|---|---|
| Backend | `DiskCache` (SQLite) for cross-run persistence; `MemoryCache` as optional L1 |
| Location | `{cache_dir}/ensembl_vep.sqlite` (from `shared.config`) |
| Key format | `make_key("vep", "GRCh38", chrom, pos, ref, alt)` |
| TTL | 30 days (2 592 000 seconds). Ensembl releases quarterly (~90 days); 30-day TTL ensures fresh data while avoiding daily re-queries |
| What is cached | Raw API JSON (`data[0]`) at `vep_raw:{variant_id}` + parsed output envelope at `vep:{variant_id}` |
| Cache on error | **Never.** Error responses (`AnnotationUnavailableError`, `NetworkError`) must not be cached. |
| Cache key on release upgrade | When `ensembl_release` in config changes, old cache entries will eventually expire via TTL. Forced invalidation can be done by changing the key prefix (e.g., `make_key("vep", "GRCh38", "r113", chrom, pos, ref, alt)`). |

### 11.2 Cache Error Handling

A `CacheError` on read must not crash the module. The correct behaviour:

```
CacheError on read → log WARNING → fall through to API call
CacheError on write → log WARNING → return result anyway (annotation succeeded)
```

The annotation pipeline must never fail because caching fails.

---

## Part 12 — Documentation Specification

### 12.1 Required Files

```
modules/vep/
├── __init__.py          # annotate() public interface + VEPAnnotation dataclass
├── client.py            # API communication, response parsing, transcript selection
├── region_map.py        # GENOMIC_REGION_MAP constant
├── tests/
│   ├── __init__.py
│   ├── test_unit.py         # all unit tests
│   ├── test_integration.py  # live API tests (marked @pytest.mark.integration)
│   ├── test_cache.py        # cache behaviour tests
│   ├── fixtures/
│   │   └── vep_response_hbb.json   # realistic mock VEP response
└── README.md
```

### 12.2 README Specification

The `modules/vep/README.md` must contain:

- **Scientific role:** what VEP provides and why it is the framework's first module.
- **Input contract:** `annotate(chrom, position, reference, alternate)` — GRCh38 only, ACGT alleles only, 1-based coordinates.
- **Output contract:** table of all 22 fields in `VEPAnnotation` with type, example value, and "may be None" annotation.
- **Transcript policy:** the three-step MANE Select → Canonical → fallback logic, with explanation of why `[0]` is insufficient.
- **API usage:** endpoint, required parameters, rate limit, error codes.
- **Caching:** TTL, key format, how to force cache invalidation.
- **Plugin suppression:** explicit statement that PolyPhen/SIFT/LOFTEE appear in raw responses but are suppressed.
- **Limitations:**
  - Multi-allelic variants must be decomposed upstream (VEP accepts one alternate allele per call).
  - Structural variants (deletions > ~50bp, CNVs, inversions) are not supported.
  - MT chromosome uses a different coordinate system in some tools; document expected behaviour.
  - Ensembl REST API has a 15 req/s public limit; batch annotation of >100 000 variants will take time.
- **Reproducibility note:** Ensembl releases new annotation every quarter. Cache entries and output records must include the Ensembl release used.
- **Future developer notes:** downstream module dependency table (from Part 9).

---

## Part 13 — Critical Review

### 13.1 Would I approve this prototype as the production foundation?

**No.** The prototype cannot be used as-is for production. It violates every shared infrastructure contract and has a biologically incorrect transcript selection policy. However, it is a valid and useful proof-of-concept that confirms the correct API endpoint, the `most_severe_consequence` strategy, the `genomic_region` mapping concept, and the basic response structure. None of those decisions need to be reversed.

The prototype should be understood as: **"the API works and these are the right fields to request"**, not as: **"this code structure is the foundation."**

### 13.2 Prioritised Improvement List

#### Critical (must be resolved before implementation begins)

| # | Change | Why |
|---|---|---|
| C-1 | Replace `requests.get()` with `HttpClient.for_service("ensembl_vep")` | Framework contract; no bare HTTP anywhere |
| C-2 | Implement MANE Select → Canonical → fallback transcript selection | Biological correctness; `[0]` is wrong |
| C-3 | Change signature to `annotate(chrom, position, reference, alternate)` | Framework contract |
| C-4 | Replace error dicts with `raise ValidationError / AnnotationUnavailableError` | Framework contract; callers cannot handle dict errors |
| C-5 | Add `validate_variant()` as first call in `annotate()` | Framework contract |
| C-6 | Add `DiskCache` integration | Reproducibility; performance; API quota |
| C-7 | Add `get_logger(__name__)` and log calls | Framework contract; debuggability |
| C-8 | Remove hardcoded URL/timeout; use `get_config()` | Framework contract |

#### Important (must be implemented in Conversation 3B)

| # | Change | Why |
|---|---|---|
| I-1 | Add `hgvs=1`, `mane_select=1`, `canonical=1`, `numbers=1` to API params | Required for mandatory output fields |
| I-2 | Add `hgvs_c`, `hgvs_p`, `gene_id`, `transcript_id`, `transcript_source`, `impact`, `biotype`, `exon_number`, `intron_number`, `codon_change` to output | Required by downstream modules |
| I-3 | Remove `params={"content-type": "application/json"}` | Wrong HTTP usage |
| I-4 | Change all `"None"` string defaults to Python `None` | Framework contract |
| I-5 | Replace empty-response intergenic assumption with `AnnotationUnavailableError` | Biological correctness |
| I-6 | Complete `GENOMIC_REGION_MAP` with missing SO terms | Completeness |
| I-7 | Change `variant_id` separator from `-` to `:` | Consistency with `CanonicalVariant.variant_id` |
| I-8 | Store raw API JSON alongside parsed output in cache | Future compatibility |
| I-9 | Pin `ensembl_release` in `config.yaml` before ship | Reproducibility |

#### Optional (implement if time allows; not blocking)

| # | Change | Why |
|---|---|---|
| O-1 | Add `strand`, `cdna_position`, `cds_position`, `protein_position` | Additional positional context |
| O-2 | Log Ensembl REST software version at startup via `/info/software` | Release drift detection |
| O-3 | Add `MemoryCache` as L1 in front of `DiskCache` | Performance for same-run repeated lookups |

---

## Final Decision

### Is the VEP module ready to move to Conversation 3B (implementation)?

**Yes — with conditions.**

The design review is complete. The scientific contract, engineering contract, API contract, transcript policy, output schema, validation strategy, testing strategy, and integration guide are all frozen above. No further design work is required.

Before Conversation 3B begins, the following two pre-conditions must be met:

**Pre-condition 1:** Pin `ensembl_release` and `vep_version` in `config.yaml`. These must be concrete values (e.g., `ensembl_release: "113"`), not `null`. Reproducibility of all annotations depends on this.

**Pre-condition 2:** Confirm explicitly that the `annotate()` function signature (`chrom`, `position`, `reference`, `alternate`) is the correct interface for all Tier 1 modules. This is stated in `PROJECT_CONTEXT.md` but should be re-confirmed before writing module code so that gnomAD, GERP++, InterVar, and SpliceAI follow the identical interface when their conversations begin.

Once those two conditions are satisfied, implementation can proceed directly from this document. The implementer should work through the Critical defects first (C-1 through C-8), then Important defects (I-1 through I-9), treating this document as the specification.

---

*Document version: 3A-FINAL | Produced for Conversation 3A | Architecture frozen*
