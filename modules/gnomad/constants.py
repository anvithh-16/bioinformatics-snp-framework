"""
modules/gnomad/constants.py

Static, non-biological constants for the gnomAD remote (GraphQL) backend.

This module intentionally contains NO logic — only the query template and
fixed string values. Keeping it logic-free means the query shape can be
reviewed/audited independently of the HTTP/parsing code, and it gives
`client.py` and `parser.py` a single shared source of truth.

The GraphQL query shape itself (`variant(variantId, dataset) { exome { af }
genome { af } }`) was confirmed against the proof-of-concept script provided
for Conversation 5B. The production query below extends it with the
additional fields required by the frozen output schema (ac, an, popmax,
homozygote count, filter status) that the POC did not request.
"""

MODULE_NAME = "gnomad"

# Frozen per gnomAD_Module_Design.md Section 20: the GraphQL `dataset`
# parameter is pinned in config.yaml (versions.gnomad_version), never left
# as a floating "latest" value. This constant is the *expected* value used
# in documentation/examples only; the actual value used at runtime always
# comes from shared.config.get_config(), never from this constant.
DEFAULT_DATASET_DOCS_EXAMPLE = "gnomad_r4"

# Status values, frozen in gnomAD_Module_Design.md Section 22.
STATUS_OK = "ok"
STATUS_NO_DATA = "no_data"
STATUS_LOW_CONFIDENCE = "low_confidence"
STATUS_MULTIPLE_MATCHES = "multiple_matches"  # reserved; not reachable for SNVs in v1

# annotation_source values (Section 13 / 20) — only "remote" exists in this
# conversation; "local" is reserved for the future GnomadLocalClient and is
# referenced only in documentation/comments, never produced by this code.
ANNOTATION_SOURCE_REMOTE = "remote"

# The GraphQL endpoint is a single POST route relative to the service's
# base_url (config.yaml: services.gnomad.base_url). HttpClient.for_service
# always issues requests relative to that base_url, so this is deliberately
# just the path component, not a full URL.
GRAPHQL_PATH = ""  # base_url already points at https://gnomad.broadinstitute.org/api

# Production GraphQL query.
#
# CORRECTED in post-implementation review (see parser.py module docstring
# for full rationale). The original version of this query requested only
# `exome { af ac an ... }` and `genome { af ac an ... }` and relied on
# parser.py to manually sum ac/an across both subsets to derive an
# "overall" frequency. That was a mistake: gnomAD's GraphQL API exposes a
# THIRD, server-computed `joint` block that already represents the
# correct combined exome+genome statistics. Confirmed against two
# independently-written, currently-working scripts that query the live
# gnomAD v4 API (one from the gnomad-browser GitHub org's own fork
# ecosystem). Neither script requests `af` directly on any block --
# both compute af = ac/an client-side -- so this query does the same,
# rather than assuming an unconfirmed `af` field exists.
#
#   - `exome` / `genome`: kept for transparency/debugging and for
#     filter_status derivation (Section 15/23) -- NOT used to derive
#     af_overall/ac_overall/an_overall anymore.
#   - `joint`: the authoritative, server-computed combined statistics.
#     This is what af_overall / ac_overall / an_overall / n_homozygotes /
#     population_frequencies are now derived from.
#
# NOTE: the `filters` field below (on exome/genome) could not be
# independently confirmed against a live schema introspection from this
# environment (network policy blocks gnomad.broadinstitute.org). Treat
# it as a flagged assumption, not a verified fact, until confirmed
# against a real response or schema introspection.
VARIANT_QUERY = """
query GnomadVariant($variantId: String!, $dataset: DatasetId!) {
  variant(variantId: $variantId, dataset: $dataset) {
    variant_id
    chrom
    pos
    ref
    alt
    exome {
      ac
      an
      homozygote_count
      filters
    }
    genome {
      ac
      an
      homozygote_count
      filters
    }
    joint {
      ac
      an
      homozygote_count
      populations {
        id
        ac
        an
        homozygote_count
      }
    }
  }
}
""".strip()