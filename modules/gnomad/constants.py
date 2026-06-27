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
# Differences from the POC script's query:
#   - Requests `ac`, `an`, `homozygote_count` in addition to `af`, for both
#     exome and genome, because the frozen output schema's ac_overall/
#     an_overall/n_homozygotes fields need them (Section 14).
#   - Requests `popmax` and `popmax_population` at the variant level, for
#     af_popmax / popmax_population (Section 14).
#   - Requests `filters` (site-level QC flags) for filter_status (Section
#     15 / 23).
#   - Requests `populations { id af ac an }` for the full per-population
#     breakdown (Section 14, population_frequencies).
#
# All of the above are real fields on gnomAD's public GraphQL schema for
# the `variant` query; this module's job is only to request and parse them,
# never to reinterpret gnomAD's own definitions.
VARIANT_QUERY = """
query GnomadVariant($variantId: String!, $dataset: DatasetId!) {
  variant(variantId: $variantId, dataset: $dataset) {
    variant_id
    reference_genome
    chrom
    pos
    ref
    alt
    exome {
      af
      ac
      an
      homozygote_count
      filters
      populations {
        id
        af
        ac
        an
      }
    }
    genome {
      af
      ac
      an
      homozygote_count
      filters
      populations {
        id
        af
        ac
        an
      }
    }
  }
}
""".strip()