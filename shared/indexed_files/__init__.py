"""
shared.indexed_files
=====================

Generic random-access reading of local, bgzip-compressed, tabix-indexed
flat files. This is the shared infrastructure component that lets a
module look up a row by genomic coordinate in a large local file
without re-implementing tabix handling itself.

Public interface (this is the entire surface module authors should use):

    from shared.indexed_files import get_tabix_lookup

    lookup = get_tabix_lookup(file_path)      # memoized per file path
    rows = lookup.fetch(chrom, position)      # 1-based position in; raw tuples out

See README.md in this directory for the full design rationale, and
Part "Frozen Architecture" of the AlphaMissense design review
(Conversation 4A) for why this exists as its own package rather than
living inside shared.reference.

This package contains no biological logic and no knowledge of any
specific module's column layout. It must stay that way for it to be
safely reusable by SpliceAI and gnomAD's local-file path later.
"""

from shared.indexed_files.tabix import TabixLookup, get_tabix_lookup

__all__ = ["TabixLookup", "get_tabix_lookup"]