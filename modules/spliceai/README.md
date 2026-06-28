# SpliceAI Module

Annotates SNVs with SpliceAI splicing-disruption delta scores from
Illumina's precomputed masked SNV file (`spliceai_scores.masked.snv.hg38.vcf.gz`).

## Output fields

| Field | Description |
|---|---|
| `ds_acceptor_gain` | DS_AG — probability of acceptor gain |
| `ds_acceptor_loss` | DS_AL — probability of acceptor loss |
| `ds_donor_gain` | DS_DG — probability of donor gain |
| `ds_donor_loss` | DS_DL — probability of donor loss |
| `dp_acceptor_gain` | DP_AG — position offset of acceptor gain |
| `dp_acceptor_loss` | DP_AL — position offset of acceptor loss |
| `dp_donor_gain` | DP_DG — position offset of donor gain |
| `dp_donor_loss` | DP_DL — position offset of donor loss |
| `max_delta_score` | `max(DS_AG, DS_AL, DS_DG, DS_DL)` — overall splice-altering probability |
| `gene_symbol` | Illumina's gene association (independent of VEP transcript selection) |

## Quick start

```python
from modules.spliceai import annotate

result = annotate("17", 41276045, "G", "T")
print(result["fields"]["max_delta_score"])
```

## Resource setup

See the integration guide at the bottom of this README or `SpliceAI_Module_Design.md` Section 7/18.

Place the masked SNV file and its index at:

```
reference/spliceai/spliceai_scores.masked.snv.hg38.vcf.gz
reference/spliceai/spliceai_scores.masked.snv.hg38.vcf.gz.tbi
reference/spliceai/VERSION
```

Pin the version in `config.yaml`:

```yaml
versions:
  spliceai_version: "spliceai:1.3.1"
```