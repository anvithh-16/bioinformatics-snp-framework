PROJECT_CONTEXT.md

Bioinformatics SNP Annotation Framework

Permanent Project Context (Always Attach to Every Conversation)

This document contains the permanent architectural decisions of the project.

Treat every decision in this file as FINAL unless there is a scientifically compelling reason to change it.

If you believe any decision must change, STOP and explain why before proposing any implementation.

⸻

Project Goal

Build a modular bioinformatics framework capable of annotating monogenic SNPs using multiple independent biological evidence sources.

The long-term goal is to create a machine-learning-ready feature dataset for disease progression/longevity prediction.

Machine Learning is NOT the current objective.

The current objective is building robust biological annotation modules.

⸻

Current Project Status

Completed

✅ Architecture

✅ Tier 0 Shared Infrastructure

✅ Tier 0.5 Reference Manager

Next

Conversation 3

VEP

⸻

Architecture

The project is disease-independent.

Current diseases are only used for testing.

No architectural decision should depend on one disease.

Canonical genome assembly

GRCh38 (hg38)

Canonical module interface

annotate(chrom, position, reference, alternate)

Every module will eventually expose this interface.

⸻

Development Environment

Primary

Ubuntu Linux

Secondary

MacBook

Google Colab

Experimental only.

⸻

Storage Budget

Maximum project storage

200 GB

Shared reference resources

Core resources

Optional heavy resources

must remain separate.

MutPred is never allowed to dictate project architecture.

⸻

Module Classification

Tier 1

Essential

VEP

gnomAD

InterVar

SpliceAI

Tier 2

Recommended

AlphaMissense

GERP++

LOEUF

GTEx

STRING

GWAS

Tier 3

Optional

MutPred

AlphaFold

DynaMut2

Removal of a Tier 3 module must never break the pipeline.

⸻

Completed Shared Infrastructure

The following components already exist.

shared/

config/

http/

cache/

validators/

logging/

exceptions/

utils/

reference/

These are frozen.

Future modules must reuse them.

Future modules must never implement their own

HTTP

logging

cache

validators

configuration

resource discovery

exceptions

rate limiting

⸻

Reference Manager

Implemented.

Responsible for

resource discovery

version tracking

disk usage

resource health

resource reporting

It never downloads resources.

It never deletes resources.

⸻

Variant Standard

Canonical input

chromosome

position

reference

alternate

GRCh38 only.

Input normalization happens before annotation.

⸻

Transcript Policy

Primary

MANE Select

Fallback

Ensembl Canonical

Never choose transcript_consequences[0] without explicit transcript selection.

⸻

Output Standardization

Not implemented yet.

Every module may have its own internal schema.

Global standardization will happen only after all modules are completed.

⸻

Missing Values

Missing annotations are represented explicitly.

Use

None

Never silently remove variants.

⸻

Validation

Current validation

=

Biological sanity checking.

Examples

ClinVar

Published variants

Known examples

Machine-learning validation happens later.

⸻

Current Module Order

1

VEP

2

AlphaMissense

3

gnomAD

4

GERP++

5

LOEUF

6

InterVar

7

SpliceAI

8

MutPred

9

AlphaFold + DynaMut2

10

GTEx

11

STRING

12

GWAS Catalog

After all modules

↓

Output Standardization

↓

Pipeline Integration

↓

ML Dataset

↓

Machine Learning

⸻

Development Workflow

Every module follows

Design Conversation

↓

Freeze scientific contract

↓

Freeze engineering contract

↓

Implementation Conversation

↓

Tests

↓

Documentation

↓

Git Commit

↓

Git Tag

↓

Next Module

⸻

Implementation Rules

Every module must

Reuse shared infrastructure

Reuse Reference Manager

Include tests

Include documentation

Include self-review

Never duplicate functionality that belongs to another module.

⸻

General Rules

Prefer official APIs.

Use local CLI only when scientifically justified.

Pin versions whenever possible.

Avoid feature duplication.

Keep modules independent.

No module should force changes to the shared infrastructure.

If an architectural flaw is discovered,

explain it before implementing changes.

⸻

End of Permanent Context