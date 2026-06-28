"""
Basic usage example for the SpliceAI module.

Prerequisites:
  1. config.yaml has spliceai_version pinned (not null).
  2. reference/spliceai/ contains the masked SNV file + .tbi index.

Run from the project root:
    python -m modules.spliceai.examples.basic_usage
"""

from modules.spliceai import annotate


def main():
    # Synthetic BRCA1 splice-region variant (illustrative coordinates).
    result = annotate("17", 41276045, "G", "T")

    print(f"Variant:          {result['variant_id']}")
    print(f"Status:           {result['status']}")
    print(f"Source version:   {result['source_version']}")
    print()

    fields = result["fields"]
    print(f"Gene symbol:      {fields['gene_symbol']}")
    print(f"Max delta score:  {fields['max_delta_score']}")
    print()
    print(f"DS_AG (acceptor gain):  {fields['ds_acceptor_gain']}")
    print(f"DS_AL (acceptor loss):  {fields['ds_acceptor_loss']}")
    print(f"DS_DG (donor gain):     {fields['ds_donor_gain']}")
    print(f"DS_DL (donor loss):     {fields['ds_donor_loss']}")
    print()
    print(f"DP_AG: {fields['dp_acceptor_gain']}")
    print(f"DP_AL: {fields['dp_acceptor_loss']}")
    print(f"DP_DG: {fields['dp_donor_gain']}")
    print(f"DP_DL: {fields['dp_donor_loss']}")


if __name__ == "__main__":
    main()