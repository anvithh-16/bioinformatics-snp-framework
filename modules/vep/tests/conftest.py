import json
from pathlib import Path

import pytest

from shared.config import reset_config_for_testing
from shared.reference import reset_reference_manager_for_testing

from modules.vep.annotator import reset_memory_cache_for_testing

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _isolated_framework_state(tmp_path, monkeypatch):
    """Every test gets an isolated project root (so cache files never
    touch the real project) and a clean config/reference-manager/memory
    cache singleton, mirroring the pattern used in shared/tests/.
    """
    reset_config_for_testing()
    reset_reference_manager_for_testing()
    reset_memory_cache_for_testing()
    monkeypatch.setenv("FRAMEWORK_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "FRAMEWORK_CONFIG_PATH", str(Path(__file__).resolve().parents[3] / "config.yaml")
    )
    yield
    reset_config_for_testing()
    reset_reference_manager_for_testing()
    reset_memory_cache_for_testing()


def load_fixture(name: str):
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)