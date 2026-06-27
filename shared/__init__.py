"""
shared
========

Tier-0 infrastructure layer for the SNP annotation framework. Every
biological annotation module (VEP, AlphaMissense, gnomAD, GERP++, LOEUF,
InterVar, SpliceAI, MutPred, AlphaFold+DynaMut2, GTEx, STRING, GWAS
Catalog) depends on this package and must not duplicate its functionality.

Submodules:
    shared.config      — central configuration (paths, URLs, versions)
    shared.logging      — centralized logging
    shared.http         — HTTP client, retry, rate limiting
    shared.cache        — generic memory/disk caching
    shared.validators   — generic variant-coordinate validation
    shared.exceptions   — unified exception hierarchy
    shared.utils        — small generic helpers (chunking, disk space)

This package contains NO biological annotation logic and downloads NO
biological databases. It is the "operating system" the 12 modules run on.
"""

__version__ = "0.1.0"
