from __future__ import annotations

from shared.indexed_files import get_tabix_lookup
from shared.logging import get_logger
from shared.reference import get_reference_manager

from modules.alphamissense.constants import RESOURCE_NAME
from modules.alphamissense.parser import normalize_chrom_for_file

log = get_logger(__name__)


class AlphaMissenseClient:
    """
    Resolves the pinned AlphaMissense local resource via
    shared.reference and reads matching rows for a given coordinate via
    shared.indexed_files. Named `client` for consistency with the other
    modules' file layout (e.g. VEP's client.py), even though there is
    no network call here — this is the module's sole data-access
    boundary, and the only place that knows the resource is a local
    tabix file rather than an API.
    """

    def __init__(self, resource=None):
        self._resource = resource

    @property
    def resource(self):
        if self._resource is None:
            rm = get_reference_manager()
            self._resource = rm.get(RESOURCE_NAME)
        return self._resource

    def fetch_raw_rows(self, chrom: str, position: int) -> list:
        file_chrom = normalize_chrom_for_file(chrom)
        lookup = get_tabix_lookup(self.resource.path)
        rows = lookup.fetch(file_chrom, position)
        log.debug(
            "Fetched raw AlphaMissense rows",
            extra={"chrom": file_chrom, "position": position, "row_count": len(rows)},
        )
        return rows

    @property
    def version(self):
        return self.resource.version