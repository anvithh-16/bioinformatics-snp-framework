from pathlib import Path

import pytest

from shared.config import FrameworkConfig
from shared.exceptions import ResourceCorruptedError, UnknownResourceError
from shared.reference import ReferenceManager
from shared.reference.models import ResourceStatus


def _cfg(tmp_path: Path, **overrides) -> FrameworkConfig:
    return FrameworkConfig.load(project_root=str(tmp_path), **overrides)


def _install_grch38(tmp_path: Path, *, version: str | None = None) -> Path:
    d = tmp_path / "reference" / "grch38"
    d.mkdir(parents=True)
    (d / "GRCh38.primary_assembly.genome.fa").write_text(">chr1\nACGT\n")
    if version:
        (d / "VERSION").write_text(version)
    return d


def _install_clinvar(tmp_path: Path, *, version: str | None = None) -> Path:
    d = tmp_path / "reference" / "clinvar"
    d.mkdir(parents=True)
    (d / "clinvar.vcf.gz").write_bytes(b"\x1f\x8b" + b"0" * 100)
    if version:
        (d / "VERSION").write_text(version)
    return d


# ---------------------------------------------------------------------------
# list_resources()
# ---------------------------------------------------------------------------

def test_list_resources_returns_all_declared_names(tmp_path: Path):
    rm = ReferenceManager(config=_cfg(tmp_path))
    names = rm.list_resources()
    assert "grch38" in names
    assert "clinvar" in names
    assert "alphafold_cache" in names
    assert len(names) == len(set(names))  # no duplicates


# ---------------------------------------------------------------------------
# verify() — every health state, never raises
# ---------------------------------------------------------------------------

def test_verify_reports_missing_for_untouched_resource(tmp_path: Path):
    rm = ReferenceManager(config=_cfg(tmp_path))
    reports = {r.name: r for r in rm.verify()}
    assert reports["grch38"].status == ResourceStatus.MISSING
    assert reports["grch38"].disk_usage_gb == 0.0


def test_verify_reports_empty_for_created_but_empty_dir(tmp_path: Path):
    (tmp_path / "reference" / "clinvar").mkdir(parents=True)
    rm = ReferenceManager(config=_cfg(tmp_path))
    report = next(r for r in rm.verify() if r.name == "clinvar")
    assert report.status == ResourceStatus.EMPTY


def test_verify_reports_installed_for_complete_resource(tmp_path: Path):
    _install_grch38(tmp_path, version="p14")
    rm = ReferenceManager(config=_cfg(tmp_path))
    report = next(r for r in rm.verify() if r.name == "grch38")
    assert report.status == ResourceStatus.INSTALLED
    assert report.installed_version == "p14"
    assert report.disk_usage_gb > 0
    assert report.last_updated is not None


def test_verify_reports_corrupted_when_marker_missing(tmp_path: Path):
    d = tmp_path / "reference" / "ensembl"
    d.mkdir(parents=True)
    (d / "some_other_file.txt").write_text("incomplete download")
    rm = ReferenceManager(config=_cfg(tmp_path))
    report = next(r for r in rm.verify() if r.name == "ensembl")
    assert report.status == ResourceStatus.CORRUPTED
    assert "Homo_sapiens.GRCh38.gtf.gz" in report.detail


def test_verify_reports_version_mismatch(tmp_path: Path):
    _install_clinvar(tmp_path, version="2023-12")
    cfg = _cfg(tmp_path, versions={"clinvar_release": "2024-1"})
    rm = ReferenceManager(config=cfg)
    report = next(r for r in rm.verify() if r.name == "clinvar")
    assert report.status == ResourceStatus.VERSION_MISMATCH
    assert report.installed_version == "2023-12"
    assert report.expected_version == "2024-1"


def test_verify_no_mismatch_when_versions_match(tmp_path: Path):
    _install_clinvar(tmp_path, version="2024-1")
    cfg = _cfg(tmp_path, versions={"clinvar_release": "2024-1"})
    rm = ReferenceManager(config=cfg)
    report = next(r for r in rm.verify() if r.name == "clinvar")
    assert report.status == ResourceStatus.INSTALLED


def test_verify_no_mismatch_when_no_version_pinned_yet(tmp_path: Path):
    # versions.clinvar_release defaults to None — an installed resource
    # with no pinned expectation must never be flagged as a mismatch.
    _install_clinvar(tmp_path, version="2024-1")
    rm = ReferenceManager(config=_cfg(tmp_path))
    report = next(r for r in rm.verify() if r.name == "clinvar")
    assert report.status == ResourceStatus.INSTALLED


def test_verify_resource_with_no_markers_installed_when_nonempty(tmp_path: Path):
    # alphafold_cache declares no marker_paths — any non-empty directory
    # should count as installed.
    d = tmp_path / "reference" / "alphafold_cache"
    d.mkdir(parents=True)
    (d / "AF-P00533-F1-model_v4.pdb").write_text("structure")
    rm = ReferenceManager(config=_cfg(tmp_path))
    report = next(r for r in rm.verify() if r.name == "alphafold_cache")
    assert report.status == ResourceStatus.INSTALLED


def test_verify_never_raises_with_nothing_installed(tmp_path: Path):
    rm = ReferenceManager(config=_cfg(tmp_path))
    reports = rm.verify()  # must not raise
    assert all(r.status == ResourceStatus.MISSING for r in reports)
    assert len(reports) == len(rm.list_resources())


def test_corrupted_unreadable_marker_file_detected(tmp_path: Path):
    # A marker "file" that is actually a directory should be treated as
    # unreadable/missing rather than silently accepted.
    d = tmp_path / "reference" / "ensembl"
    d.mkdir(parents=True)
    (d / "Homo_sapiens.GRCh38.gtf.gz").mkdir()  # wrong type on purpose
    (d / "Homo_sapiens.GRCh38.gtf.gz" / "placeholder").write_text("x")
    rm = ReferenceManager(config=_cfg(tmp_path))
    report = next(r for r in rm.verify() if r.name == "ensembl")
    assert report.status == ResourceStatus.CORRUPTED


# ---------------------------------------------------------------------------
# get() — raises for unusable resources, succeeds for usable ones
# ---------------------------------------------------------------------------

def test_get_returns_handle_for_installed_resource(tmp_path: Path):
    _install_grch38(tmp_path, version="p14")
    rm = ReferenceManager(config=_cfg(tmp_path))
    handle = rm.get("grch38")
    assert handle.name == "grch38"
    assert handle.version == "p14"
    assert handle.genome_build == "GRCh38"
    assert handle.path.exists()


def test_get_succeeds_for_version_mismatch_but_intact_resource(tmp_path: Path):
    _install_clinvar(tmp_path, version="2023-12")
    cfg = _cfg(tmp_path, versions={"clinvar_release": "2024-1"})
    rm = ReferenceManager(config=cfg)
    handle = rm.get("clinvar")  # must not raise
    assert handle.version == "2023-12"
    assert handle.report.status == ResourceStatus.VERSION_MISMATCH


def test_get_raises_for_missing_resource(tmp_path: Path):
    rm = ReferenceManager(config=_cfg(tmp_path))
    with pytest.raises(ResourceCorruptedError):
        rm.get("dbnsfp")


def test_get_raises_for_empty_resource(tmp_path: Path):
    (tmp_path / "reference" / "clinvar").mkdir(parents=True)
    rm = ReferenceManager(config=_cfg(tmp_path))
    with pytest.raises(ResourceCorruptedError):
        rm.get("clinvar")


def test_get_raises_for_corrupted_resource(tmp_path: Path):
    d = tmp_path / "reference" / "ensembl"
    d.mkdir(parents=True)
    (d / "junk.txt").write_text("partial")
    rm = ReferenceManager(config=_cfg(tmp_path))
    with pytest.raises(ResourceCorruptedError):
        rm.get("ensembl")


def test_get_raises_unknown_resource_error_for_undeclared_name(tmp_path: Path):
    rm = ReferenceManager(config=_cfg(tmp_path))
    with pytest.raises(UnknownResourceError):
        rm.get("not_a_real_resource")


def test_get_error_context_includes_resource_name(tmp_path: Path):
    rm = ReferenceManager(config=_cfg(tmp_path))
    with pytest.raises(ResourceCorruptedError) as exc_info:
        rm.get("dbnsfp")
    assert exc_info.value.context["resource"] == "dbnsfp"
    assert exc_info.value.context["status"] == "missing"


# ---------------------------------------------------------------------------
# disk_usage() — budget separation and totals
# ---------------------------------------------------------------------------

def test_disk_usage_separates_reference_and_optional_budgets(tmp_path: Path):
    _install_grch38(tmp_path)
    af_dir = tmp_path / "reference" / "alphafold_cache"
    af_dir.mkdir(parents=True)
    (af_dir / "struct.pdb").write_text("x" * 1000)

    rm = ReferenceManager(config=_cfg(tmp_path))
    usage = rm.disk_usage()

    assert usage.reference_gb > 0
    assert usage.optional_gb > 0
    assert usage.total_gb == pytest.approx(usage.reference_gb + usage.optional_gb)
    assert "grch38" in usage.per_resource_gb
    assert "alphafold_cache" in usage.per_resource_gb


def test_disk_usage_zero_when_nothing_installed(tmp_path: Path):
    rm = ReferenceManager(config=_cfg(tmp_path))
    usage = rm.disk_usage()
    assert usage.reference_gb == 0.0
    assert usage.optional_gb == 0.0
    assert usage.total_gb == 0.0
    assert usage.free_disk_gb > 0  # real filesystem, should always be positive


def test_disk_usage_respects_configured_budget(tmp_path: Path):
    cfg = _cfg(tmp_path, project_storage_budget_gb=50)
    rm = ReferenceManager(config=cfg)
    usage = rm.disk_usage()
    assert usage.project_storage_budget_gb == 50
    assert usage.budget_remaining_gb == 50  # nothing installed yet


# ---------------------------------------------------------------------------
# summary() — human-readable report
# ---------------------------------------------------------------------------

def test_summary_marks_installed_resources_with_checkmark(tmp_path: Path):
    _install_grch38(tmp_path, version="p14")
    rm = ReferenceManager(config=_cfg(tmp_path))
    text = rm.summary()
    assert "✓ GRCh38" in text
    assert "Installed" in text


def test_summary_marks_missing_resources_with_warning(tmp_path: Path):
    rm = ReferenceManager(config=_cfg(tmp_path))
    text = rm.summary()
    assert "⚠ dbNSFP" in text
    assert "Missing" in text


def test_summary_includes_storage_totals(tmp_path: Path):
    _install_grch38(tmp_path)
    rm = ReferenceManager(config=_cfg(tmp_path))
    text = rm.summary()
    assert "Total reference storage" in text
    assert "Optional (Tier 3) storage" in text
    assert "Project storage budget" in text
    assert "Available disk" in text


def test_summary_uses_proper_resource_display_names(tmp_path: Path):
    rm = ReferenceManager(config=_cfg(tmp_path))
    text = rm.summary()
    # Naive title-casing would render these as "Dbnsfp", "Alphafold Cache" —
    # confirm the proper-cased labels are used instead.
    assert "dbNSFP" in text
    assert "AlphaFold Cache" in text
    assert "ClinVar" in text


def test_summary_never_raises_with_mixed_states(tmp_path: Path):
    _install_grch38(tmp_path, version="p14")
    (tmp_path / "reference" / "clinvar").mkdir(parents=True)
    d = tmp_path / "reference" / "ensembl"
    d.mkdir(parents=True)
    (d / "junk.txt").write_text("partial")
    rm = ReferenceManager(config=_cfg(tmp_path))
    text = rm.summary()  # must not raise
    assert isinstance(text, str)
    assert len(text) > 0


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

def test_get_reference_manager_returns_same_instance():
    from shared.reference import (
        get_reference_manager,
        reset_reference_manager_for_testing,
    )
    reset_reference_manager_for_testing()
    a = get_reference_manager()
    b = get_reference_manager()
    assert a is b
    reset_reference_manager_for_testing()
