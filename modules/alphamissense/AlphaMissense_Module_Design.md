AlphaMissense Module Design

Status

Frozen Architecture

Conversation: 4A

Implementation Conversation: 4B

⸻

Scientific Purpose

AlphaMissense predicts the pathogenicity likelihood of missense single nucleotide variants (SNVs) using a deep-learning model developed by Google DeepMind.

Unlike VEP, which classifies the functional consequence of a variant (e.g., missense, synonymous, splice), AlphaMissense estimates how damaging a specific amino-acid substitution is.

It is therefore a pathogenicity prediction module, not a consequence annotation module.

⸻

Biological Scope

Applicable only to:

* GRCh38
* SNVs
* Protein-coding missense variants

Out of scope:

* Indels
* Frameshifts
* Stop gain/loss
* Synonymous variants
* Intronic variants
* Regulatory variants
* Intergenic variants

⸻

Relationship with Previous Modules

VEP

VEP determines:

* variant consequence
* affected transcript
* HGVS
* amino-acid substitution

AlphaMissense predicts pathogenicity for the substitution.

The modules remain independent.

AlphaMissense performs coordinate-based lookup and does not depend on VEP transcript selection.

⸻

Relationship with Future Modules

Designed to complement:

* gnomAD
* LOEUF
* InterVar
* SpliceAI
* MutPred
* AlphaFold/DynaMut2

No duplicated functionality.

⸻

Data Source

Primary source:

* AlphaMissense canonical GRCh38 dataset

Version pinned using:

* Zenodo record
* SHA256 checksum

No live REST API is used.

⸻

Data Strategy

Frozen decision:

Downloaded local BGZF-compressed file with Tabix index

Files:

reference/
└── alphamissense/
    ├── AlphaMissense_hg38.tsv.gz
    ├── AlphaMissense_hg38.tsv.gz.tbi
    └── VERSION

Only canonical transcript dataset is supported.

Isoform dataset intentionally excluded from Version 1.

⸻

Shared Infrastructure

Introduces a reusable shared package:

shared/
└── indexed_files/

Purpose:

Generic random-access lookup for BGZF/Tabix-indexed files.

Reusable by:

* AlphaMissense
* SpliceAI
* local gnomAD

The shared layer performs only indexed lookup.

All biological parsing remains module-specific.

⸻

Indexed File API

Public interface:

lookup = get_tabix_lookup(file_path)
rows = lookup.fetch(
    chrom,
    position
)

Responsibilities:

* memoized handles
* generic lookup
* coordinate conversion
* no biological interpretation

⸻

Library Choice

Frozen:

pysam

Reasons:

* actively maintained
* wraps htslib
* supports generic Tabix files
* reusable across multiple modules

⸻

Input Contract

annotate(
    chrom,
    position,
    reference,
    alternate
)

Shared validation:

shared.validators.validate_variant()

GRCh38 only.

SNVs only.

⸻

Output Schema

AlphaMissenseAnnotation

Contains:

* variant_id
* am_pathogenicity
* am_class
* protein_variant
* transcript_id
* uniprot_id
* match_count
* candidate_matches
* source_dataset
* data_release
* annotation_source
* status

Envelope:

{
    "variant_id": "...",
    "module_name": "alphamissense",
    "status": "...",
    "fields": ...,
    "source_version": ...
}

⸻

Missing Data Policy

Missing biological values:

Python None

Never:

* “None”
* “”
* “Unknown”

Status:

* ok
* no_data
* multiple_matches

⸻

Version Pinning

Pinned using:

* Zenodo identifier
* SHA256 checksum

Example:

alphamissense_version:
    "zenodo:10813168"

⸻

Error Handling

Reuse existing shared exceptions.

No new exception hierarchy.

Resource problems:

* ResourceCorruptedError
* UnknownResourceError

Validation:

* ValidationError

No silent failures.

⸻

Caching

Local file.

Unlimited cache lifetime.

Cache key includes:

* version
* chromosome
* position
* reference
* alternate

No time-based expiry.

⸻

Validation Strategy

Biological sanity checks.

Representative known variants:

* TP53 R175H
* HBB E6V
* APOE4
* known intergenic variant

⸻

Testing Strategy

Unit Tests

* exact coordinate lookup
* missing coordinate
* multiple matches
* missing fields
* variant ID
* validation
* resource errors

⸻

Mock Tests

Small local indexed fixture.

No network.

⸻

Integration Tests

Require the real AlphaMissense dataset.

Automatically skipped if unavailable.

⸻

Storage

Reference directory:

reference/
└── alphamissense/

Marker files:

* AlphaMissense_hg38.tsv.gz
* AlphaMissense_hg38.tsv.gz.tbi
* VERSION

⸻

Config Changes

reference_resources:
  alphamissense:
    subdir: alphamissense
    marker_paths:
      - AlphaMissense_hg38.tsv.gz
      - AlphaMissense_hg38.tsv.gz.tbi
    version_key: alphamissense_version
    budget: reference

Version:

versions:
    alphamissense_version:
        "zenodo:10813168"

⸻

Shared Architecture Addition

New package:

shared/
└── indexed_files/

Contains:

* init.py
* tabix.py
* README.md

Responsibilities:

* generic indexed lookup
* memoized Tabix handles
* coordinate conversion

No biological parsing.

⸻

Known Limitations

* Missense SNVs only
* Canonical transcript dataset only
* No isoform dataset
* No model inference
* Uses precomputed scores only
* Research tool, not clinical diagnosis

⸻

Risks

* Canonical transcript differences from VEP
* No predictable release cadence
* Static precomputed dataset
* Common disease-risk variants (e.g. APOE4) may appear benign because the model predicts pathogenicity, not disease risk

⸻

Frozen Architecture

Module:

modules/
└── alphamissense/

Public interface:

annotate(
    chrom,
    position,
    reference,
    alternate
)

Data source:

Local indexed AlphaMissense dataset.

Shared infrastructure:

shared.indexed_files

No dependency on VEP transcript selection.

⸻

Frozen Output Schema

AlphaMissenseAnnotation dataclass.

Standard framework annotation envelope.

⸻

Frozen Data Strategy

Local BGZF + Tabix indexed dataset.

No REST API.

No SQL database.

⸻

Frozen Validation Strategy

Shared validation plus biological sanity testing.

⸻

Frozen Testing Strategy

* Unit tests
* Mock tests
* Integration tests
* Biological sanity tests

⸻

GO / NO-GO Decision

GO

Implementation may proceed once:

1. reference_resources.alphamissense is added to config.yaml.
2. alphamissense_version is pinned.
3. shared/indexed_files is implemented and tested.

Architecture is fully frozen.

No additional design work is required before implementation.