from pathlib import Path

import pytest

from shared.config import FrameworkConfig, ReferenceResourceConfig
from shared.exceptions import ConfigurationError


def test_default_reference_resources_declared():
    cfg = FrameworkConfig.load()
    names = cfg.reference_resource_names()
    # The eight resources named explicitly in the Tier-0.5 spec.
    for expected in (
        "grch38", "clinvar", "ensembl", "dbnsfp",
        "uniprot", "gnomad", "spliceai", "alphafold_cache",
    ):
        assert expected in names


def test_reference_resource_returns_resolved_config(tmp_path: Path):
    cfg = FrameworkConfig.load(project_root=str(tmp_path), reference_dir="reference")
    r = cfg.reference_resource("clinvar")
    assert isinstance(r, ReferenceResourceConfig)
    assert r.name == "clinvar"
    assert r.path == tmp_path / "reference" / "clinvar"
    assert r.marker_paths == ["clinvar.vcf.gz"]
    assert r.version_key == "clinvar_release"
    assert r.budget == "reference"


def test_reference_resource_path_is_under_reference_dir(tmp_path: Path):
    cfg = FrameworkConfig.load(project_root=str(tmp_path), reference_dir="custom_ref")
    r = cfg.reference_resource("grch38")
    assert r.path == tmp_path / "custom_ref" / "grch38"


def test_unknown_reference_resource_raises_configuration_error():
    cfg = FrameworkConfig.load()
    with pytest.raises(ConfigurationError):
        cfg.reference_resource("not_a_real_resource")


def test_optional_budget_resource_is_alphafold_cache():
    cfg = FrameworkConfig.load()
    r = cfg.reference_resource("alphafold_cache")
    assert r.budget == "optional"
    assert r.marker_paths == []


def test_reference_resources_override_via_config_overrides(tmp_path: Path):
    # Confirms a future developer can override/extend reference_resources
    # the same way every other config block is overridden — via
    # FrameworkConfig.load(**overrides) or config.yaml — without touching
    # shared.config source code.
    cfg = FrameworkConfig.load(
        project_root=str(tmp_path),
        reference_resources={
            "grch38": {
                "subdir": "genome_v2",
                "marker_paths": ["genome.fa"],
                "version_key": None,
                "budget": "reference",
            },
        },
    )
    r = cfg.reference_resource("grch38")
    assert r.path == tmp_path / "reference" / "genome_v2"
    assert r.marker_paths == ["genome.fa"]
    # Other defaults must remain intact (deep merge, not full overwrite).
    assert "clinvar" in cfg.reference_resource_names()


def test_existing_config_fields_unaffected():
    # Guards against the Tier-0.5 addition accidentally breaking any
    # field finalized in Conversation 2.
    cfg = FrameworkConfig.load()
    assert cfg.genome_build == "GRCh38"
    assert cfg.project_storage_budget_gb == 200
    assert cfg.alphafold_cache_max_gb == 20
    assert cfg.service("ensembl_vep").base_url == "https://rest.ensembl.org"
