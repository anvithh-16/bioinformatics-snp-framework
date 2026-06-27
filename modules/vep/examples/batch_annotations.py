"""
Batch annotation example — shows the pattern an integration layer should
use: catch AnnotationUnavailableError/ValidationError per-variant so one
bad/no-data variant never aborts a whole batch.

Run from the project root with:

    FRAMEWORK_CONFIG_PATH=config.yaml PYTHONPATH=. python modules/vep/examples/batch_annotation.py
"""

from __future__ import annotations

from shared.exceptions import AnnotationUnavailableError, FrameworkError, ValidationError

from modules.vep import annotate

VARIANTS = [
    ("11", 5227002, "T", "A"),    # HBB E6V — sickle cell
    ("17", 7674220, "C", "T"),    # TP53 R175H
    ("19", 44908684, "T", "C"),   # APOE rs429358
    ("8", 144500000, "A", "G"),   # deep intergenic — expect no_data
    ("chr99", 1000, "A", "G"),    # malformed input — expect ValidationError
]


def main() -> None:
    results = []
    for chrom, position, reference, alternate in VARIANTS:
        try:
            record = annotate(chrom, position, reference, alternate)
            results.append(record)
        except AnnotationUnavailableError as exc:
            results.append(
                {
                    "variant_id": f"{chrom}:{position}:{reference}:{alternate}",
                    "module_name": "vep",
                    "status": "no_data",
                    "error": str(exc),
                }
            )
        except ValidationError as exc:
            results.append(
                {
                    "variant_id": f"{chrom}:{position}:{reference}:{alternate}",
                    "module_name": "vep",
                    "status": "invalid_input",
                    "error": str(exc),
                }
            )
        except FrameworkError as exc:
            # NetworkError / RateLimitError after retries exhausted.
            results.append(
                {
                    "variant_id": f"{chrom}:{position}:{reference}:{alternate}",
                    "module_name": "vep",
                    "status": "error",
                    "error": str(exc),
                }
            )

    for r in results:
        print(r.get("variant_id"), "->", r.get("status"))


if __name__ == "__main__":
    main()