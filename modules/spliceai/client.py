from __future__ import annotations

from shared.indexed_files import get_tabix_lookup
from shared.logging import get_logger
from shared.reference import get_reference_manager

from modules.spliceai.constants import RESOURCE_NAME
from modules.spliceai.parser import normalize_chrom_for_file

log = get_logger(__name__)


class SpliceAILocalClient:
    """
    Thin wrapper around shared.indexed_files.get_tabix_lookup for the
    SpliceAI masked SNV resource. The single data-access boundary for
    this module: the only place that knows the resource is a local tabix
    file. Named 'client' for consistency with the project's module layout
    pattern even though no network call ever occurs here.
    """

    def __init__(self, resource=None):
        self._resource = resource

    @property
    def resource(self):
        if self._resource is None:
            rm = get_reference_manager()
            self._resource = rm.get(RESOURCE_NAME)
        return self._resource

    def fetch_variant_rows(self, chrom: str, position: int) -> list[tuple[str, ...]]:
        file_chrom = normalize_chrom_for_file(chrom)
        lookup = get_tabix_lookup(self.resource.path)
        rows = lookup.fetch(file_chrom, position)
        log.debug(
            "Fetched raw SpliceAI rows",
            extra={"chrom": file_chrom, "position": position, "row_count": len(rows)},
        )
        return rows

    @property
    def version(self) -> str | None:
        return self.resource.version