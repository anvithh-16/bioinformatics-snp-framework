from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from modules.alphamissense.constants import (
    ANNOTATION_SOURCE,
    SOURCE_DATASET,
    STATUS_MULTIPLE_MATCHES,
    STATUS_NO_DATA,
    STATUS_OK,
)


@dataclass(frozen=True)
class AlphaMissenseCandidate:
    transcript_id: Optional[str]
    uniprot_id: Optional[str]
    protein_variant: Optional[str]
    am_pathogenicity: Optional[float]
    am_class: Optional[str]

    def to_dict(self) -> dict:
        return {
            "transcript_id": self.transcript_id,
            "uniprot_id": self.uniprot_id,
            "protein_variant": self.protein_variant,
            "am_pathogenicity": self.am_pathogenicity,
            "am_class": self.am_class,
        }


@dataclass
class AlphaMissenseAnnotation:
    variant_id: str
    status: str

    am_pathogenicity: Optional[float] = None
    am_class: Optional[str] = None
    protein_variant: Optional[str] = None
    transcript_id: Optional[str] = None
    uniprot_id: Optional[str] = None

    match_count: int = 0
    candidate_matches: Optional[list] = None

    source_dataset: str = SOURCE_DATASET
    data_release: Optional[str] = None
    annotation_source: str = ANNOTATION_SOURCE

    def to_dict(self) -> dict:
        return {
            "am_pathogenicity": self.am_pathogenicity,
            "am_class": self.am_class,
            "protein_variant": self.protein_variant,
            "transcript_id": self.transcript_id,
            "uniprot_id": self.uniprot_id,
            "match_count": self.match_count,
            "candidate_matches": self.candidate_matches,
            "source_dataset": self.source_dataset,
            "data_release": self.data_release,
            "annotation_source": self.annotation_source,
        }

    @staticmethod
    def no_data(variant_id: str, data_release: Optional[str]) -> "AlphaMissenseAnnotation":
        return AlphaMissenseAnnotation(
            variant_id=variant_id,
            status=STATUS_NO_DATA,
            match_count=0,
            candidate_matches=None,
            data_release=data_release,
        )

    @staticmethod
    def single_match(
        variant_id: str,
        candidate: AlphaMissenseCandidate,
        data_release: Optional[str],
    ) -> "AlphaMissenseAnnotation":
        return AlphaMissenseAnnotation(
            variant_id=variant_id,
            status=STATUS_OK,
            am_pathogenicity=candidate.am_pathogenicity,
            am_class=candidate.am_class,
            protein_variant=candidate.protein_variant,
            transcript_id=candidate.transcript_id,
            uniprot_id=candidate.uniprot_id,
            match_count=1,
            candidate_matches=None,
            data_release=data_release,
        )

    @staticmethod
    def multiple_matches(
        variant_id: str,
        candidates: list,
        data_release: Optional[str],
    ) -> "AlphaMissenseAnnotation":
        return AlphaMissenseAnnotation(
            variant_id=variant_id,
            status=STATUS_MULTIPLE_MATCHES,
            am_pathogenicity=None,
            am_class=None,
            protein_variant=None,
            transcript_id=None,
            uniprot_id=None,
            match_count=len(candidates),
            candidate_matches=[c.to_dict() for c in candidates],
            data_release=data_release,
        )

    def to_envelope(self) -> dict:
        return {
            "variant_id": self.variant_id,
            "module_name": "alphamissense",
            "status": self.status,
            "fields": self.to_dict(),
            "source_version": self.data_release,
        }