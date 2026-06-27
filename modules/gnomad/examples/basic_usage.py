"""
modules/gnomad/examples/basic_usage.py

Minimal runnable example of the gnomAD module's public interface.
Requires network access and a pinned `versions.gnomad_version` in
config.yaml (see modules/gnomad/README.md).

Run with:
    PYTHONPATH=. python modules/gnomad/examples/basic_usage.py
"""

from modules.gnomad import annotate
from shared.exceptions import AnnotationUnavailableError, NetworkError, ValidationError


def main() -> None:
    # A real, well-characterized GRCh38 SNV coordinate.
    chrom, position, reference, alternate = "1", 55_051_215, "G", "A"

    try:
        result = annotate(chrom, position, reference, alternate)
    except ValidationError as exc:
        print(f"Invalid input: {exc}")
        return
    except AnnotationUnavailableError as exc:
        print(f"gnomAD explicitly rejected the query: {exc}")
        return
    except NetworkError as exc:
        print(f"Could not reach gnomAD: {exc}")
        return

    print(f"variant_id:       {result['variant_id']}")
    print(f"status:           {result['status']}")
    print(f"source_version:   {result['source_version']}")

    fields = result["fields"]
    print(f"af_overall:       {fields['af_overall']}")
    print(f"ac_overall/an_overall: {fields['ac_overall']}/{fields['an_overall']}")
    print(f"af_popmax:        {fields['af_popmax']} ({fields['popmax_population']})")
    print(f"filter_status:    {fields['filter_status']}")
    print(f"n_homozygotes:    {fields['n_homozygotes']}")

    if result["status"] == "no_data":
        print(
            "\nNote: status=no_data means this variant was not observed in "
            "the pinned gnomAD release -- this does NOT imply af_overall=0."
        )


if __name__ == "__main__":
    main()