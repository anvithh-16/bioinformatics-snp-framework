"""
Basic usage example for modules.vep.

Run from the project root with:

    FRAMEWORK_CONFIG_PATH=config.yaml PYTHONPATH=. python modules/vep/examples/basic_usage.py
"""

from __future__ import annotations

import json

from modules.vep import annotate


def main() -> None:
    # HBB E6V — sickle cell anemia missense variant (GRCh38).
    result = annotate(chrom="11", position=5227002, reference="T", alternate="A")
    print(json.dumps(result, indent=2, default=str))

    print()
    print("gene:", result["fields"]["gene_symbol"])
    print("consequence:", result["fields"]["most_severe_consequence"])
    print("transcript (selected via):", result["fields"]["transcript_source"])
    print("HGVS.p:", result["fields"]["hgvs_p"])


if __name__ == "__main__":
    main()