from __future__ import annotations

MODULE_NAME = "spliceai"
RESOURCE_NAME = "spliceai"

SOURCE_DATASET = "spliceai_masked_snv"
ANNOTATION_SOURCE = "local"

STATUS_OK = "ok"
STATUS_NO_DATA = "no_data"

VALID_STATUSES = frozenset({STATUS_OK, STATUS_NO_DATA})

# The Illumina SpliceAI masked SNV file uses bare Ensembl-style contig
# names ("1", "17", "X") — identical to this project's canonical
# variant convention. No prefix translation is needed in either direction;
# FILE_CHROM_PREFIX is kept here as the single documented location for
# this fact so that parser.normalize_chrom_for_file() has a named
# constant to reference, and so any future format change is a one-line
# edit here rather than a grep.
FILE_CHROM_PREFIX = "chr"

# VCF INFO field key whose value holds all per-allele SpliceAI entries.
SPLICEAI_INFO_KEY = "SpliceAI"

# Pipe-delimited field order within each SpliceAI entry:
# ALLELE|SYMBOL|DS_AG|DS_AL|DS_DG|DS_DL|DP_AG|DP_AL|DP_DG|DP_DL
ENTRY_FIELD_COUNT = 10
ENTRY_IDX_ALLELE  = 0
ENTRY_IDX_SYMBOL  = 1
ENTRY_IDX_DS_AG   = 2
ENTRY_IDX_DS_AL   = 3
ENTRY_IDX_DS_DG   = 4
ENTRY_IDX_DS_DL   = 5
ENTRY_IDX_DP_AG   = 6
ENTRY_IDX_DP_AL   = 7
ENTRY_IDX_DP_DG   = 8
ENTRY_IDX_DP_DL   = 9

# VCF column indices (0-based) in the tab-split row tuples returned by TabixLookup.
VCF_COL_CHROM  = 0
VCF_COL_POS    = 1
VCF_COL_ID     = 2
VCF_COL_REF    = 3
VCF_COL_ALT    = 4
VCF_COL_QUAL   = 5
VCF_COL_FILTER = 6
VCF_COL_INFO   = 7

VCF_EXPECTED_MIN_COLUMNS = 8

# Caching: no predictable update cadence — invalidation is driven by the
# pinned version string in the cache key, not by TTL. 10-year TTL used
# rather than literally infinite, matching the AlphaMissense precedent.
# The primary data file within the resource directory.
# This is the first (and only scored-data) entry in config.yaml's
# marker_paths list. Defined here so client.py has one symbolic name
# to reference rather than an inline string literal, and so the
# conftest fixture can use the same constant when writing the fixture file.
PRIMARY_VCF_FILENAME = "spliceai_scores.masked.snv.hg38.vcf.gz"

CACHE_TTL_SECONDS = 315_360_000
CACHE_FILENAME = "spliceai.sqlite"