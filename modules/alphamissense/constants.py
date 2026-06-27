from __future__ import annotations

MODULE_NAME = "alphamissense"
RESOURCE_NAME = "alphamissense"

SOURCE_DATASET = "AlphaMissense_hg38"
ANNOTATION_SOURCE = "alphamissense_local_tabix"

STATUS_OK = "ok"
STATUS_NO_DATA = "no_data"
STATUS_MULTIPLE_MATCHES = "multiple_matches"

VALID_STATUSES = frozenset({STATUS_OK, STATUS_NO_DATA, STATUS_MULTIPLE_MATCHES})

AM_CLASS_LIKELY_BENIGN = "likely_benign"
AM_CLASS_AMBIGUOUS = "ambiguous"
AM_CLASS_LIKELY_PATHOGENIC = "likely_pathogenic"

KNOWN_AM_CLASSES = frozenset(
    {AM_CLASS_LIKELY_BENIGN, AM_CLASS_AMBIGUOUS, AM_CLASS_LIKELY_PATHOGENIC}
)

# AlphaMissense_hg38.tsv.gz column layout (0-based indices into the
# tab-split row). This is the only place this layout is encoded.
COL_CHROM = 0
COL_POS = 1
COL_REF = 2
COL_ALT = 3
COL_GENOME = 4
COL_UNIPROT_ID = 5
COL_TRANSCRIPT_ID = 6
COL_PROTEIN_VARIANT = 7
COL_AM_PATHOGENICITY = 8
COL_AM_CLASS = 9

EXPECTED_COLUMN_COUNT = 10

# AlphaMissense_hg38.tsv.gz uses UCSC-style "chr"-prefixed contig names
# ("chr1", "chrX"), while this project's canonical variant model uses
# bare Ensembl-style names ("1", "X"). This prefix is added/stripped in
# exactly one place: parser.normalize_chrom_for_file() /
# parser.normalize_chrom_from_file().
FILE_CHROM_PREFIX = "chr"

# Caching: there is no predictable update cadence for AlphaMissense
# (unlike Ensembl's quarterly cycle), so cache invalidation is driven
# by the pinned resource version inside the cache key, not by a short
# TTL. This TTL is intentionally long (10 years) rather than literally
# infinite, since shared.cache.DiskCache requires a concrete value.
CACHE_TTL_SECONDS = 315_360_000

CACHE_FILENAME = "alphamissense.sqlite"