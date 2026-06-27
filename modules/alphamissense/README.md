# `modules/alphamissense` — AlphaMissense Pathogenicity Annotation

Tier 2 module. Looks up the calibrated AlphaMissense pathogenicity score
and three-tier classification (`likely_benign` / `ambiguous` /
`likely_pathogenic`) for a missense SNV, directly by genomic
coordinate against the locally pinned `AlphaMissense_hg38.tsv.gz`.

## Interface

```python
from modules.alphamissense import annotate

result = annotate(chrom="17", position=7674220, reference="C", alternate="T")
```

GRCh38, SNVs only — identical contract to every other module.

## Independent of VEP's transcript selection

This module queries the AlphaMissense file directly by
`(chrom, position, reference, alternate)`. It does **not** consume
VEP's selected transcript or HGVS notation. AlphaMissense's own
canonical-transcript file (GENCODE V32) is not guaranteed to match
VEP's MANE Select pick for every gene; coupling the two would risk
silent false `no_data` results and a runtime dependency between Tier 1
and Tier 2 modules. See the Conversation 4A architecture review,
section 12, for the full reasoning.

## Output

Standard envelope:
```python
{
    "variant_id": "17:7674220:C:T",
    "module_name": "alphamissense",
    "status": "ok" | "no_data" | "multiple_matches",
    "fields": {
        "am_pathogenicity": 0.9938,
        "am_class": "likely_pathogenic",
        "protein_variant": "R175H",
        "transcript_id": "ENST00000269305.9",
        "uniprot_id": "P04637",
        "match_count": 1,
        "candidate_matches": None,
        "source_dataset": "AlphaMissense_hg38",
        "data_release": "zenodo:10813168",
        "annotation_source": "alphamissense_local_tabix",
    },
    "source_version": "zenodo:10813168",
}
```

`status="multiple_matches"` is a rare, genuine overlapping-transcript
collision at the exact same coordinate+allele. When it occurs, all
candidates are preserved in `candidate_matches`; none is arbitrarily
selected as "the" answer.

## Known limitation: `no_data` is not fully specific

`status="no_data"` covers two distinct biological situations this
module cannot currently distinguish: (a) the variant genuinely is not
missense in a canonical transcript, or (b) it is missense but scored
only in AlphaMissense's separate non-canonical-isoforms file, which
this module deliberately does not load (v1 scope, per the architecture
review). This is a documented limitation, not a defect.

## ClinVar-calibration caveat

AlphaMissense's classification thresholds (0.34 / 0.564) were
calibrated against a ClinVar test set to hit 90% precision. A
"ClinVar concordance" check on this module's output is therefore not
fully independent validation — part of the agreement is already
designed in. Treat high ClinVar concordance as expected, not as proof
of correctness; lean on independent functional/hotspot evidence for
real validation (see `tests/test_sanity.py`).

## Longevity/disease-progression caveat

Common, clinically-relevant risk-modifying variants (e.g. APOE
rs429358 / epsilon-4) are expected to score toward `likely_benign`
here, because AlphaMissense's training signal is frequency-anchored
and the variant isn't a classic monogenic-pathogenic missense change.
A `likely_benign` call from this module must never be read downstream
as "this variant doesn't matter" for this project's eventual
longevity/disease-progression ML goal — see `tests/test_sanity.py::test_apoe_e4_is_not_classed_as_likely_pathogenic`.

## Caching

Cache keys include the pinned `data_release` (e.g. `"zenodo:10813168"`),
not a short TTL — AlphaMissense has no predictable update cadence, so
invalidation happens by version, not time. `no_data` results are cached
too: a zero-match outcome against a static local file is deterministic,
unlike a possibly-transient empty API response.

## Reused shared infrastructure

`shared.validators`, `shared.cache`, `shared.logging`, `shared.config`,
`shared.reference`, `shared.indexed_files`, `shared.exceptions`. No new
infrastructure is introduced by this module.

## Testing

```bash
pip install -r shared/requirements.txt
PYTHONPATH=. pytest modules/alphamissense/tests/ -v
```

- `test_unit.py` — parsing, allele filtering, chromosome normalization, model shapes. No I/O.
- `test_cache.py` — cache-hit avoidance, version-scoped invalidation, `no_data` caching.
- `test_integration.py` — full `annotate()` composition against a registered resource; error propagation for missing/corrupted resources.
- `test_sanity.py` — biological sanity checks (TP53 R175H, APOE e4). **Run against the real pinned `AlphaMissense_hg38.tsv.gz` before treating these as validated** — see the module docstring in that file.