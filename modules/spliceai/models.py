from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from modules.spliceai.constants import (
    ANNOTATION_SOURCE,
    MODULE_NAME,
    SOURCE_DATASET,
    STATUS_NO_DATA,
    STATUS_OK,
)


@dataclass
class SpliceAIAnnotation:
    variant_id: str
    status: str

    ds_acceptor_gain: Optional[float] = None
    ds_acceptor_loss: Optional[float] = None
    ds_donor_gain: Optional[float] = None
    ds_donor_loss: Optional[float] = None
    dp_acceptor_gain: Optional[int] = None
    dp_acceptor_loss: Optional[int] = None
    dp_donor_gain: Optional[int] = None
    dp_donor_loss: Optional[int] = None
    max_delta_score: Optional[float] = None
    gene_symbol: Optional[str] = None

    source_dataset: str = SOURCE_DATASET
    data_release: Optional[str] = None
    annotation_source: str = ANNOTATION_SOURCE

    def to_dict(self) -> dict:
        return {
            "ds_acceptor_gain": self.ds_acceptor_gain,
            "ds_acceptor_loss": self.ds_acceptor_loss,
            "ds_donor_gain": self.ds_donor_gain,
            "ds_donor_loss": self.ds_donor_loss,
            "dp_acceptor_gain": self.dp_acceptor_gain,
            "dp_acceptor_loss": self.dp_acceptor_loss,
            "dp_donor_gain": self.dp_donor_gain,
            "dp_donor_loss": self.dp_donor_loss,
            "max_delta_score": self.max_delta_score,
            "gene_symbol": self.gene_symbol,
            "source_dataset": self.source_dataset,
            "data_release": self.data_release,
            "annotation_source": self.annotation_source,
        }

    def to_envelope(self) -> dict:
        return {
            "variant_id": self.variant_id,
            "module_name": MODULE_NAME,
            "status": self.status,
            "fields": self.to_dict(),
            "source_version": self.data_release,
        }

    @staticmethod
    def no_data(variant_id: str, data_release: Optional[str]) -> "SpliceAIAnnotation":
        return SpliceAIAnnotation(
            variant_id=variant_id,
            status=STATUS_NO_DATA,
            data_release=data_release,
        )

    @staticmethod
    def from_parsed(
        variant_id: str,
        data_release: Optional[str],
        ds_ag: Optional[float],
        ds_al: Optional[float],
        ds_dg: Optional[float],
        ds_dl: Optional[float],
        dp_ag: Optional[int],
        dp_al: Optional[int],
        dp_dg: Optional[int],
        dp_dl: Optional[int],
        gene_symbol: Optional[str],
    ) -> "SpliceAIAnnotation":
        ds_values = [v for v in (ds_ag, ds_al, ds_dg, ds_dl) if v is not None]
        max_ds = max(ds_values) if ds_values else None

        return SpliceAIAnnotation(
            variant_id=variant_id,
            status=STATUS_OK,
            ds_acceptor_gain=ds_ag,
            ds_acceptor_loss=ds_al,
            ds_donor_gain=ds_dg,
            ds_donor_loss=ds_dl,
            dp_acceptor_gain=dp_ag,
            dp_acceptor_loss=dp_al,
            dp_donor_gain=dp_dg,
            dp_donor_loss=dp_dl,
            max_delta_score=max_ds,
            gene_symbol=gene_symbol,
            data_release=data_release,
        )