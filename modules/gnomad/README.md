# `modules/gnomad/` — gnomAD Population Allele Frequency Module

## Status

Implemented: **GraphQL remote backend only** (Conversation 5B).
Deferred: local Tabix/VCF backend (`GnomadLocalClient`) — see "Future Local Backend Plan" below.

Design freeze: `gnomAD_Module_Design.md` (Conversation 5A).

## Scientific Role

gnomAD answers "how common is this exact variant in human populations?" —
population-genetics evidence that is independent of, and complementary
to, VEP's consequence annotation and AlphaMissense's pathogenicity
prediction. A very rare variant is more likely to be pathogenic than a
common one, almost independent of any in-silico predictor; rarity itself
is the signal this module provides.

This module never computes pathogenicity, consequence, or constraint
metrics. It exposes raw population frequency facts only.

## Input Contract

```python
from modules.gnomad import annotate

result = annotate(chrom, position, reference, alternate)
```

Identical to VEP and AlphaMissense: GRCh38 only, SNVs only (v1),
validated via `shared.validators.validate_variant()` before any network
call is made.

## Output Contract

```python
{
    "variant_id": "1:55051215:G:A",      # framework canonical notation
    "module_name": "gnomad",
    "status": "ok",                       # ok | no_data | low_confidence | multiple_matches
    "fields": {
        "variant_id": "1-55051215-G-A",   # gnomAD's own notation
        "af_overall": 0.0000523,
        "ac_overall": 16,
        "an_overall": 367728,
        "af_popmax": 0.00012,
        "popmax_population": "afr",
        "population_frequencies": {
            "afr": {"af": 0.00012, "ac": 4, "an": 29240},
            "nfe": {"af": 0.00003, "ac": 12, "an": 333480},
            ...
        },
        "filter_status": "PASS",
        "n_homozygotes": 0,
        "source_dataset": "gnomad_r4",
        "data_release": "gnomad_r4",
        "annotation_source": "remote",
        "status": "ok",
    },
    "source_version": "gnomad_r4",
}
```

All fields with no biological value are Python `None` — never the string
`"None"`, `""`, or `"Unknown"`.

## GraphQL Query Flow

```
annotate(chrom, position, reference, alternate)
    -> shared.validators.validate_variant()      [raises ValidationError]
    -> check shared.cache.DiskCache               [cache hit -> return]
    -> convert to gnomAD notation (chrom-pos-ref-alt)
    -> GnomadRemoteClient.fetch_variant_data()
         -> shared.http.HttpClient.for_service("gnomad").post(...)
         -> POST the pinned VARIANT_QUERY (constants.py) with
            {variantId, dataset} variables
         -> raise AnnotationUnavailableError if response has `errors`
         -> return None if `data.variant` is null (NOT an error)
    -> parser.parse_variant_response()
         -> combine exome + genome subsets into "overall" stats
         -> derive af_popmax / popmax_population
         -> derive filter_status / status
    -> wrap in standard envelope
    -> cache.set() (only ever reached on success -- errors never cached)
    -> return
```

### Post-implementation review correction

The first implementation derived `af_overall`/`ac_overall`/`an_overall`/
`n_homozygotes`/`population_frequencies` by manually summing gnomAD's
separate `exome` and `genome` blocks client-side. **This was a real bug,
fixed during review.** gnomAD's GraphQL API exposes a third block,
**`joint`**, which is the Broad Institute's own server-computed
combination of exome+genome and is the authoritative source for
"overall" statistics. This was confirmed against two independently
written, currently-working scripts that query the live gnomAD v4 API.

This module now reads `af_overall`/`ac_overall`/`an_overall`/
`n_homozygotes`/`population_frequencies` directly from `joint`. `exome`
and `genome` are still requested and parsed, but only to derive
`filter_status` — they are never used to compute a frequency statistic.
The output field *names* are unchanged from the frozen schema; only how
they're computed changed. See the detailed rationale at the top of
`parser.py`.

One field's exact placement remains an explicitly flagged assumption,
not a verified fact: `filters` (requested on `exome`/`genome` for
`filter_status`) could not be confirmed against a live schema
introspection from this environment, since outbound network access to
`gnomad.broadinstitute.org` is blocked by this sandbox's network policy.
Confirm this against a real response (or schema introspection) before
relying on `filter_status` in production.

## Caching

| Property | Decision |
|---|---|
| Backend | `DiskCache` at `{cache_dir}/gnomad.sqlite` |
| Key | `make_key("gnomad", "remote", dataset, chrom, position, reference, alternate)` |
| TTL | 90 days (gnomAD releases are infrequent and not on a fixed cadence, unlike Ensembl's quarterly releases) |
| Cache on error | Never — `AnnotationUnavailableError` / `NetworkError` are raised before any `cache.set()` call is reached |
| `no_data` results | Cached (a confirmed "not found" against a pinned dataset version is a stable, reproducible fact) |

The cache key includes `"remote"` as the backend tag specifically so
that a future local-backend result can never collide with (or be
silently returned in place of) a remote-backend result for the same
variant, even if both are added to the same cache file later.

## Version Pinning

`versions.gnomad_version` in `config.yaml` is the GraphQL `dataset`
parameter (e.g. `"gnomad_r4"`), pinned exactly like `ensembl_release` for
VEP. `annotate()` raises `ValidationError` immediately if this is unset —
it never falls back to "latest" silently. Every output envelope records
`source_version` / `data_release` so any result can be traced to the
exact pinned release that produced it.

## Testing

```bash
PYTHONPATH=. pytest modules/gnomad/tests/ -v
```

- `test_unit.py` — pure parsing/combination logic, no I/O, no mocking needed.
- `test_client_mocked.py` — `GnomadRemoteClient` against mocked HTTP via the `responses` library. No real network call is ever made in this file or in any non-integration test.
- `test_cache.py` — cache hit/miss/never-cache-errors behavior, backend mocked.
- `test_biological_sanity.py` — fixture-driven checks of scientifically meaningful properties (e.g. "not observed" must never collapse to `af=0.0`).
- `test_integration.py` — live API calls, marked `@pytest.mark.integration`, deselected by default per `pytest.ini` (`addopts = -m "not integration"`). Individual tests additionally self-skip if `gnomad_version` isn't pinned or the API is unreachable.

## Known Limitations

- SNVs only in v1; indels deferred.
- No exome-only / genome-only fields exposed; only the combined "overall" view and the per-population breakdown.
- Ancestry/population labels are exactly whatever gnomAD's own `populations[].id` values are — never remapped or reinterpreted.
- `af_popmax` reflects whichever populations gnomAD reports for the pinned release; it is not a clinical-grade rarity claim on its own.
- Research tool; not a substitute for clinical-grade frequency review.

## Future Local Backend Plan

`GnomadLocalClient` (Tabix/VCF-indexed, reusing `shared.indexed_files`
exactly as AlphaMissense does) is intentionally out of scope for this
conversation. The architecture already accommodates it without any
change to `annotate()`'s signature, validation, caching, or output
envelope:

- `_get_backend()` in `__init__.py` is the single seam where backend
  selection happens. Adding the local backend means adding a branch
  there (e.g. on a future `cfg.gnomad_backend` setting), not touching
  `annotate()` itself.
- `GnomadRemoteClient.fetch_variant_data(variant_id, dataset)` is the
  exact method signature a `GnomadLocalClient` would also implement —
  same inputs, same `Optional[Dict]` return contract (`None` = not
  found), just reading a local Tabix index instead of calling the API.
- `parser.parse_variant_response()` already accepts a plain dict shaped
  like `{"exome": {...}, "genome": {...}}` (or `None`); a local VCF
  parser would only need to produce that same intermediate shape from
  VCF INFO fields, and the rest of the pipeline (combination, popmax
  derivation, status logic) is reused unchanged.
- The cache key already includes a backend tag (`"remote"`), so adding
  `"local"` cache entries later cannot collide with existing ones.

No part of `shared/` needs to change to add the local backend later —
`shared.indexed_files` is the same generic Tabix layer AlphaMissense
already proved out.