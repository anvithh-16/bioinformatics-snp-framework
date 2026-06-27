from pathlib import Path

from shared.reference.models import (
    DiskUsageReport,
    ResourceReport,
    ResourceStatus,
)


def test_installed_status_is_usable():
    assert ResourceStatus.INSTALLED.is_usable is True


def test_version_mismatch_is_usable():
    # Intact-but-stale data is still safe for a module to read.
    assert ResourceStatus.VERSION_MISMATCH.is_usable is True


def test_missing_empty_corrupted_are_not_usable():
    assert ResourceStatus.MISSING.is_usable is False
    assert ResourceStatus.EMPTY.is_usable is False
    assert ResourceStatus.CORRUPTED.is_usable is False


def test_resource_report_is_ok_mirrors_status():
    ok_report = ResourceReport(
        name="grch38", status=ResourceStatus.INSTALLED, path=Path("/x"),
        budget="reference", installed_version="p14", expected_version=None,
        disk_usage_gb=1.0, last_updated=None, detail="OK",
    )
    bad_report = ResourceReport(
        name="dbnsfp", status=ResourceStatus.MISSING, path=Path("/y"),
        budget="reference", installed_version=None, expected_version=None,
        disk_usage_gb=0.0, last_updated=None, detail="missing",
    )
    assert ok_report.is_ok is True
    assert bad_report.is_ok is False


def test_disk_usage_report_budget_remaining():
    usage = DiskUsageReport(
        reference_gb=50.0,
        optional_gb=10.0,
        total_gb=60.0,
        project_storage_budget_gb=200.0,
        free_disk_gb=500.0,
        per_resource_gb={"grch38": 50.0, "alphafold_cache": 10.0},
    )
    assert usage.budget_remaining_gb == 140.0


def test_disk_usage_report_over_budget_goes_negative():
    # The model itself doesn't clamp at zero — over-budget should be
    # visibly negative so a developer notices, not silently floored.
    usage = DiskUsageReport(
        reference_gb=190.0,
        optional_gb=20.0,
        total_gb=210.0,
        project_storage_budget_gb=200.0,
        free_disk_gb=5.0,
        per_resource_gb={},
    )
    assert usage.budget_remaining_gb == -10.0
