from shared.config import get_config


def test_ensembl_release_is_pinned():
    cfg = get_config()
    assert cfg.version("ensembl_release") == "113"
    assert cfg.version("ensembl_release") is not None


def test_vep_version_is_pinned():
    cfg = get_config()
    assert cfg.version("vep_version") == "113.0"


def test_ensembl_vep_service_config_matches_frozen_contract():
    cfg = get_config()
    service = cfg.service("ensembl_vep")
    assert service.base_url == "https://rest.ensembl.org"
    assert service.timeout_seconds == 15
    assert service.max_retries == 4
    assert service.rate_limit_per_second == 15