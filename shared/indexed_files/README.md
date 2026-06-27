# `shared.indexed_files` — Generic Tabix-Indexed Local File Access

## What this is

A small, generic layer for fast random-access reads into local,
bgzip-compressed, tabix-indexed flat files (TSV, BED, or any other
tab-delimited format that `tabix` can index — not limited to VCF).

It exists because some biological resources — AlphaMissense's
precomputed score table being the first — are distributed as static
downloadable files with **no query API**, and need point lookups by
genomic coordinate without loading the entire file into memory.

## What this is *not*

This is **not** a replacement for, or extension of, `shared.reference`.
The division of labor is intentionally narrow:

| Component | Answers |
|---|---|
| `shared.reference` | *Where* is this resource, and what version is it? (never reads content) |
| `shared.indexed_files` | *Read me the row at this coordinate.* (never knows what a resource "is", never tracks versions) |

A module composes both: ask `shared.reference` for a resolved path,
then hand that path to `shared.indexed_files.get_tabix_lookup()`.

This package also has **zero knowledge of any module's column schema**.
It returns raw tab-split tuples. Parsing `am_pathogenicity`,
`am_class`, etc. out of those tuples is `modules/alphamissense/`'s job,
not this package's. Keeping it generic is what makes it safe to reuse
for SpliceAI's precomputed score file and gnomAD's local VCF fallback
later without modification.

## Quickstart for a new module

```python
from shared.reference import get_reference_manager
from shared.indexed_files import get_tabix_lookup

rm = get_reference_manager()
resource = rm.get("alphamissense")          # path + version, never content

lookup = get_tabix_lookup(resource.path)     # memoized — safe to call every time
rows = lookup.fetch(chrom, position)         # 1-based position; raw tuples back

for row in rows:
    ...  # your module's own column-parsing logic goes here
```

## Coordinate convention

Every other interface in this project is 1-based (`annotate(chrom,
position, reference, alternate)`, `CanonicalVariant`, the source data
files' own `POS` columns). `pysam.TabixFile.fetch()` is 0-based and
half-open. The conversion happens in exactly **one** place —
`tabix._to_pysam_region()` — and callers of `TabixLookup.fetch()`
never need to think about it. Do not re-derive this conversion
elsewhere; import and use this package instead.

## Handle lifecycle

Opening a `TabixFile` loads its index into memory — this is not free,
and must not happen once per `annotate()` call. `get_tabix_lookup()`
memoizes one open handle per resolved absolute file path for the
lifetime of the process. Calling it repeatedly is the *correct* and
expected usage pattern; it is not a cache you need to manage.

## Thread-safety

A single `TabixFile` handle is not guaranteed safe for concurrent
`fetch()` calls from multiple threads. This mirrors the existing
documented limitation of `shared.http.RateLimiter` being per-process —
acceptable for a single-developer-machine pipeline. If the pipeline is
ever parallelized across threads, each thread should call
`get_tabix_lookup()` itself; because handles are memoized per file
path (not per caller), this does not multiply file handles unless you
genuinely run multiple threads needing concurrent access, which is a
problem for that future moment, not for the current architecture.

## Error handling

| Condition | Behaviour |
|---|---|
| Data file missing | `ResourceCorruptedError` |
| `.tbi` index missing | `ResourceCorruptedError` |
| Index present but corrupt / built against a different file | `ResourceCorruptedError` |
| Chromosome not present in the index at all | `ResourceCorruptedError` — almost always a naming mismatch (`"chr1"` vs `"1"`), surfaced rather than treated as "no data" |
| Valid chromosome, no row at this exact position | Returns `[]` — this is a normal, expected biological outcome, not an error |

No new exception type was introduced for this package. It reuses
`shared.exceptions.ResourceCorruptedError`, on the basis that a
tabix-indexed resource missing its index (or having a stale/corrupt
one) is a form of resource corruption — the same conceptual category
`shared.reference` already uses that exception for.

## Why this is its own package and not part of `shared.reference`

`shared.reference`'s documented contract is explicit: it tracks
resource discovery, version tracking, disk usage, and health, and
**never reads resource content**. Folding coordinate lookups into it
would blur a boundary that's already frozen. Keeping this as a sibling
package preserves that boundary and keeps both components doing one
job each.

## Dependency

Uses [`pysam`](https://github.com/pysam-developers/pysam) (a wrapper
around the same `htslib` that produces `tabix`/`bgzip` themselves, so
there is no risk of an independent, divergent reimplementation of the
index format). Pinned in `shared/requirements.txt`. See the
AlphaMissense architecture review (Conversation 4A) for the full
comparison against `pytabix` and other alternatives.

## Testing

```bash
pip install -r shared/requirements.txt
PYTHONPATH=. pytest shared/indexed_files/tests/ -v
```

Tests build their own small bgzip+tabix fixture files under `tmp_path`
at test time (via `pysam.tabix_index()`), matching the project's
existing convention of never committing binary fixtures or touching a
real `reference/` directory in unit tests.