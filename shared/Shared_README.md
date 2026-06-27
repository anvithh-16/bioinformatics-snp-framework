# `shared/` — Tier-0 / Tier-0.5 Infrastructure Layer

This is the foundation every annotation module (VEP, AlphaMissense, gnomAD,
GERP++, LOEUF, InterVar, SpliceAI, MutPred, AlphaFold+DynaMut2, GTEx,
STRING, GWAS Catalog) is built on top of. **It contains no biological
logic and downloads no biological databases.**

As of Tier-0.5, this includes `shared.reference` — the Shared Reference
Manager, the single source of truth for where every shared biological
resource (GRCh38, ClinVar, Ensembl, dbNSFP, UniProt, gnomAD, SpliceAI,
AlphaFold cache) lives, what version it is, and whether it's installed.
See `shared/reference/README.md` for full documentation. With Tier-0.5
complete, shared infrastructure is now frozen — Conversation 3 (VEP) is
the first biological module.

If you are implementing a new module, read this file fully before writing
any code — every piece of generic infrastructure your module needs
(HTTP, retries, rate limiting, caching, config, logging, validation,
exceptions, reference resource management) already exists here. Do not
reimplement any of it.

Indexed Files Layer

Provides generic random-access readers for BGZF/Tabix-indexed resources.

Used by:

* AlphaMissense
* SpliceAI
* Local gnomAD

This layer performs only indexed lookup.

Biological parsing remains inside each module.

## Directory layout

```
shared/
|---indexed_files/
|   |--- __init__.py
|   |---  tabix.py
|   |--- README.md
├── http/
│   ├── client.py       # HttpClient — the only HTTP client any module should use
│   ├── retry.py        # retry_with_backoff decorator
│   └── rate_limit.py   # RateLimiter / get_rate_limiter
├── cache/
│   └── __init__.py     # MemoryCache, DiskCache, make_key
├── config/
│   ├── __init__.py      # FrameworkConfig, get_config()
│   └── config.example.yaml
├── reference/
│   ├── __init__.py      # ReferenceManager, get_reference_manager()
│   ├── manager.py        # resource discovery/verification/reporting logic
│   ├── models.py         # ResourceStatus, ResourceReport, ResourceHandle
│   └── README.md         # full Tier-0.5 documentation — read before
│                          # touching any reference resource path
├── logging/
│   └── __init__.py      # get_logger(), configure_logging(), timed()
├── validators/
│   └── __init__.py      # validate_variant(), CanonicalVariant
├── exceptions/
│   └── __init__.py      # FrameworkError and all subclasses
├── utils/
│   └── __init__.py      # chunked(), disk space helpers
└── tests/                # unit + mock-HTTP tests for everything above
```

## Quickstart for a new module (e.g. VEP)

```python
from shared.http import HttpClient
from shared.cache import DiskCache, make_key
from shared.config import get_config
from shared.logging import get_logger
from shared.validators import validate_variant
from shared.exceptions import AnnotationUnavailableError
from shared.reference import get_reference_manager

log = get_logger(__name__)

def annotate(chrom, position, reference, alternate):
    variant = validate_variant(chrom, position, reference, alternate)

    cfg = get_config()
    rm = get_reference_manager()
    ensembl = rm.get("ensembl")  # path + version for the resource this module needs

    cache = DiskCache(cfg.cache_dir / "ensembl_vep.sqlite", default_ttl_seconds=86400)
    key = make_key("vep", variant.variant_id)

    cached = cache.get(key)
    if cached is not None:
        return cached

    client = HttpClient.for_service("ensembl_vep")
    response = client.get(f"vep/human/hgvs/{variant.variant_id}")
    response.raise_for_status()

    if not response.json_body:
        raise AnnotationUnavailableError(
            "VEP returned no data for this variant",
            context={"variant": variant.variant_id},
        )

    result = {
        "variant_id": variant.variant_id,
        "module_name": "vep",
        "status": "ok",
        "fields": response.json_body,
        "source_version": ensembl.version,
    }
    cache.set(key, result)
    return result
```

This is the pattern **every** module should follow: validate → check cache
→ call API via `HttpClient.for_service` (or read a local reference
resource via `shared.reference.get_reference_manager()`) → wrap result
in the standard envelope (`variant_id`, `module_name`, `status`,
`fields`, `source_version`) → cache → return.

See `shared/reference/README.md` for the full Reference Manager API,
error-handling contract, and a complete VEP integration example.

## Configuration

Copy `shared/config/config.example.yaml` to `config.yaml` at the project
root and adjust paths/versions. Never hardcode a path or URL in module
code — always go through `get_config()`.

Pin every version field (`ensembl_release`, `clinvar_release`, etc.)
before Module 1 ships. Reproducibility depends on this.

The `reference_resources` block (added in Tier-0.5) declares where each
shared biological resource lives on disk and what counts as
"installed." See `shared/reference/README.md` for the full picture —
module code should never read this block directly; go through
`shared.reference.get_reference_manager()` instead.

## Error handling contract

Every module must raise only exceptions from `shared.exceptions`. The
most important ones for module authors:

- `ValidationError` — bad input; raise before doing any work.
- `AnnotationUnavailableError` — no data available for this variant; the
  caller will record `status="no_data"`, not crash.
- `OptionalModuleUnavailableError` — for Tier 3 modules (MutPred,
  AlphaFold+DynaMut2) when the underlying tool/binary isn't
  installed/configured. The pipeline must keep running.
- `NetworkError` / `RateLimitError` — already handled internally by
  `HttpClient`; you generally won't raise these yourself.
- `UnknownResourceError` / `ResourceCorruptedError` — raised by
  `shared.reference.ReferenceManager.get()` for an undeclared resource
  name or one that's missing/empty/corrupted. See
  `shared/reference/README.md` for the full contract, including why
  `VERSION_MISMATCH` deliberately does *not* raise.

## Module tiers (for context, decided in the architecture phase)

- **Tier 1 (Essential):** VEP, gnomAD, InterVar, SpliceAI, GERP++
- **Tier 2 (Recommended):** AlphaMissense, LOEUF, GTEx, STRING, GWAS Catalog
- **Tier 3 (Optional):** MutPred (v1/v2/none), AlphaFold + DynaMut2

Tier 3 module failures must never propagate as pipeline-breaking errors —
catch `OptionalModuleUnavailableError` at the integration layer and record
`status="unavailable"`.

## AlphaFold cache note

The 20GB-capped, LRU-evicting AlphaFold structure cache is a
**module-specific** concern built on top of `shared.cache`'s primitives
(it needs its own metadata table tracking access counts/dates beyond
simple TTL expiry) — it will be designed in the AlphaFold+DynaMut2 module
conversation, not here. Tier-0.5's Reference Manager only tracks its
disk usage (under the separate "optional" budget line, not the
"reference" one) and whether its directory has anything in it at all —
see `shared/reference/README.md`.

## Testing

```bash
pip install -r shared/requirements.txt
PYTHONPATH=. pytest shared/tests/ -v
```

All HTTP tests use the `responses` library to mock external calls — no
test ever makes a real network request. `shared.reference`'s tests use
`tmp_path` for filesystem isolation and never touch a real `reference/`
directory.

## Known limitations / future improvements

- `RateLimiter` is per-process. If a module ever runs as multiple
  separate processes hitting the same API, each gets its own token
  bucket and the combined real-world rate could exceed the service's
  actual limit. Acceptable for a single-developer-machine pipeline; would
  need a shared external store (e.g. Redis) if parallelized across
  machines later.
- `DiskCache` uses one SQLite file per service. Fine at this scale;
  would need WAL mode tuning if concurrent writes from many threads
  become frequent.
- No circuit-breaker pattern yet (only retry/backoff). If an external API
  goes down for an extended period, every module call will still retry up
  to `max_retries` before failing rather than failing fast. Add if this
  becomes a real cost during the 12-module build-out.
- `shared.reference`'s version detection relies on a manually-written
  `VERSION` file per resource directory — see `shared/reference/README.md`'s
  self-review for why this was chosen and when it might need to become a
  proper manifest format instead.
