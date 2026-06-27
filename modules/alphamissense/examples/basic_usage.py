"""
Basic usage example for the AlphaMissense module.

Run from the project root (after the AlphaMissense resource has been
downloaded, indexed, and registered per shared/reference/README.md):

    PYTHONPATH=. python3 modules/alphamissense/examples/basic_usage.py
"""

from modules.alphamissense import annotate


def main():
    # TP53 R175H -- well-known oncogenic hotspot, expect likely_pathogenic.
    result = annotate(chrom="17", position=7674220, reference="C", alternate="T")
    print("TP53 R175H:", result["status"], "->", result["fields"]["am_class"])

    # A coordinate with no missense AlphaMissense entry.
    result = annotate(chrom="1", position=1, reference="A", alternate="T")
    print("Off-target coordinate:", result["status"])


if __name__ == "__main__":
    main()