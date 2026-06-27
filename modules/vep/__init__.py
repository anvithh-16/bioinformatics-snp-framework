"""
modules.vep
=============

Tier 1 (Essential) structural consequence annotation module, built on
Ensembl VEP's REST API.

Public interface — the only things other modules / the pipeline
integration layer should import:

    from modules.vep import annotate, VEPAnnotation

    result = annotate("11", 5227002, "T", "A")

See ``modules/vep/README.md`` for the full module documentation
(scientific role, output schema, transcript policy, caching, testing,
limitations, future integration).
"""

from __future__ import annotations

from modules.vep.annotator import annotate
from modules.vep.models import VEPAnnotation, build_output_envelope

__all__ = ["annotate", "VEPAnnotation", "build_output_envelope"]

__version__ = "1.0.0"

"""Top-level namespace package for all annotation modules (vep, ...)."""