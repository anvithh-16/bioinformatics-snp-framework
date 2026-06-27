"""
shared.config
===============

Single source of truth for paths, API endpoints, timeouts, retry counts,
rate limits, and pinned tool/database versions. No module should ever
hardcode a path or URL — everything is read from here.

Configuration precedence (highest wins):
    1. Explicit kwargs passed to FrameworkConfig.load()
    2. Environment variables (FRAMEWORK_*)
    3. config.yaml in the project root (or path given via FRAMEWORK_CONFIG_PATH)
    4. Built-in defaults below

Future modules use it like:

    from shared.config import get_config
    cfg = get_config()
    vep_url = cfg.service_url("ensembl_vep")
    timeout = cfg.timeout("ensembl_vep")
    ref_dir = cfg.reference_dir / "ensembl"
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from shared.exceptions import ConfigurationError

_ENV_PREFIX = "FRAMEWORK_"

# ---------------------------------------------------------------------------
# Built-in defaults. These exist so the framework is usable out of the box
# in a fresh clone before any config.yaml is written. Every value here is
# overridable.
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, Any] = {
    "project_root": ".",
    "reference_dir": "reference",
    "cache_dir": "cache",
    "logs_dir": "logs",
    "data_dir": "data",

    "genome_build": "GRCh38",

    # Per-service settings. Keys here are the canonical service names every
    # module should reference (not hardcoded URLs scattered across modules).
    "services": {
        "ensembl_vep": {
            "base_url": "https://rest.ensembl.org",
            "timeout_seconds": 15,
            "max_retries": 4,
            "rate_limit_per_second": 15,  # Ensembl's documented public limit
        },
        "gnomad": {
            "base_url": "https://gnomad.broadinstitute.org/api",
            "timeout_seconds": 20,
            "max_retries": 4,
            "rate_limit_per_second": 5,
        },
        "string_db": {
            "base_url": "https://string-db.org/api",
            "timeout_seconds": 20,
            "max_retries": 3,
            "rate_limit_per_second": 5,
        },
        "gwas_catalog": {
            "base_url": "https://www.ebi.ac.uk/gwas/rest/api",
            "timeout_seconds": 20,
            "max_retries": 3,
            "rate_limit_per_second": 5,
        },
        "alphafold_db": {
            "base_url": "https://alphafold.ebi.ac.uk/api",
            "timeout_seconds": 30,
            "max_retries": 3,
            "rate_limit_per_second": 3,
        },
    },

    # Pinned versions — every module's output should record which version
    # of its underlying resource produced the annotation, for reproducibility.
    "versions": {
        "genome_build": "GRCh38",
        "ensembl_release": None,    # to be pinned before Module 1 ships
        "clinvar_release": None,
        "gnomad_version": None,
        "dbnsfp_version": None,
        "alphamissense_version": None,
        "vep_version": None,
        "spliceai_version": None,
    },

    "alphafold_cache_max_gb": 20,
    "project_storage_budget_gb": 200,

    # ------------------------------------------------------------------
    # Reference resources (Tier-0.5 — shared.reference)
    # ------------------------------------------------------------------
    # Declarative description of every shared biological resource that
    # shared.reference.ReferenceManager inspects. The manager NEVER
    # downloads these — it only verifies what's already on disk.
    #
    # subdir       : directory under reference_dir for this resource
    # marker_paths : files/dirs (relative to subdir) whose presence means
    #                "installed"; an existing-but-empty subdir with none
    #                of these present is reported as "empty", not "missing"
    # version_key  : key into the `versions` block above that pins the
    #                expected version for this resource (None if the
    #                resource is unversioned, e.g. a raw genome FASTA
    #                tracked only by genome_build)
    # budget       : "reference" (counts against reference-resource
    #                storage) or "optional" (e.g. AlphaFold cache, MutPred
    #                BLAST DBs — tracked separately so Tier 3 module
    #                resources never compete with core reference data for
    #                the same budget line)
    "reference_resources": {
        "grch38": {
            "subdir": "grch38",
            "marker_paths": ["GRCh38.primary_assembly.genome.fa"],
            "version_key": None,
            "budget": "reference",
        },
        "clinvar": {
            "subdir": "clinvar",
            "marker_paths": ["clinvar.vcf.gz"],
            "version_key": "clinvar_release",
            "budget": "reference",
        },
        "ensembl": {
            "subdir": "ensembl",
            "marker_paths": ["Homo_sapiens.GRCh38.gtf.gz"],
            "version_key": "ensembl_release",
            "budget": "reference",
        },
        "dbnsfp": {
            "subdir": "dbnsfp",
            "marker_paths": ["dbNSFP.txt.gz"],
            "version_key": "dbnsfp_version",
            "budget": "reference",
        },
        "uniprot": {
            "subdir": "uniprot",
            "marker_paths": ["uniprot_sprot_human.dat.gz"],
            "version_key": None,
            "budget": "reference",
        },
        "gnomad": {
            "subdir": "gnomad",
            "marker_paths": ["gnomad.genomes.vcf.bgz"],
            "version_key": "gnomad_version",
            "budget": "reference",
        },
        "spliceai": {
            "subdir": "spliceai",
            "marker_paths": ["spliceai_scores.vcf.gz"],
            "version_key": "spliceai_version",
            "budget": "reference",
        },
        "alphafold_cache": {
            "subdir": "alphafold_cache",
            "marker_paths": [],
            "version_key": None,
            "budget": "optional",
        },
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@dataclass
class ServiceConfig:
    name: str
    base_url: str
    timeout_seconds: float
    max_retries: int
    rate_limit_per_second: float


@dataclass
class ReferenceResourceConfig:
    """Resolved config for one shared.reference resource.

    Returned by FrameworkConfig.reference_resource(); shared.reference
    uses this to know where to look on disk and what "installed" means
    for a given resource, without any path/version ever being
    hardcoded in shared.reference itself.
    """
    name: str
    path: Path
    marker_paths: list[str]
    version_key: Optional[str]
    budget: str  # "reference" or "optional"


@dataclass
class FrameworkConfig:
    """Resolved, immutable-in-practice configuration object.

    Construct via FrameworkConfig.load(), not directly.
    """

    _raw: dict[str, Any] = field(repr=False)

    # ---- paths -----------------------------------------------------------

    @property
    def project_root(self) -> Path:
        return Path(self._raw["project_root"]).expanduser().resolve()

    @property
    def reference_dir(self) -> Path:
        return self._resolved_dir("reference_dir")

    @property
    def cache_dir(self) -> Path:
        return self._resolved_dir("cache_dir")

    @property
    def logs_dir(self) -> Path:
        return self._resolved_dir("logs_dir")

    @property
    def data_dir(self) -> Path:
        return self._resolved_dir("data_dir")

    def _resolved_dir(self, key: str) -> Path:
        raw = Path(self._raw[key])
        return raw if raw.is_absolute() else self.project_root / raw

    # ---- genome build ------------------------------------------------------

    @property
    def genome_build(self) -> str:
        return self._raw["genome_build"]

    # ---- versions ----------------------------------------------------------

    def version(self, key: str) -> Optional[str]:
        return self._raw["versions"].get(key)

    # ---- services ------------------------------------------------------

    def service(self, name: str) -> ServiceConfig:
        services = self._raw.get("services", {})
        if name not in services:
            raise ConfigurationError(
                f"No configuration found for service '{name}'. "
                f"Known services: {sorted(services.keys())}",
                context={"service": name},
            )
        s = services[name]
        try:
            return ServiceConfig(
                name=name,
                base_url=s["base_url"],
                timeout_seconds=float(s["timeout_seconds"]),
                max_retries=int(s["max_retries"]),
                rate_limit_per_second=float(s["rate_limit_per_second"]),
            )
        except KeyError as exc:
            raise ConfigurationError(
                f"Service '{name}' is missing required field {exc}",
                context={"service": name},
            ) from exc

    def service_url(self, name: str) -> str:
        return self.service(name).base_url

    def timeout(self, name: str) -> float:
        return self.service(name).timeout_seconds

    # ---- storage budget -----------------------------------------------------

    @property
    def alphafold_cache_max_gb(self) -> float:
        return float(self._raw["alphafold_cache_max_gb"])

    @property
    def project_storage_budget_gb(self) -> float:
        return float(self._raw["project_storage_budget_gb"])

    # ---- reference resources (Tier-0.5 — shared.reference) ------------------

    def reference_resource_names(self) -> list[str]:
        """All resource names declared in config, in declaration order."""
        return list(self._raw.get("reference_resources", {}).keys())

    def reference_resource(self, name: str) -> "ReferenceResourceConfig":
        """Resolved config for a single declared reference resource.

        Raises ConfigurationError if `name` isn't declared in
        `reference_resources` — this is intentionally the same failure
        mode as `service()` for an unknown service name, so callers get a
        consistent error type regardless of which config lookup failed.
        """
        resources = self._raw.get("reference_resources", {})
        if name not in resources:
            raise ConfigurationError(
                f"No reference resource configured named '{name}'. "
                f"Known resources: {sorted(resources.keys())}",
                context={"resource": name},
            )
        r = resources[name]
        try:
            return ReferenceResourceConfig(
                name=name,
                path=self.reference_dir / r["subdir"],
                marker_paths=list(r.get("marker_paths", [])),
                version_key=r.get("version_key"),
                budget=r.get("budget", "reference"),
            )
        except KeyError as exc:
            raise ConfigurationError(
                f"Reference resource '{name}' is missing required field {exc}",
                context={"resource": name},
            ) from exc

    # ---- loading -----------------------------------------------------------

    @classmethod
    def load(
        cls,
        config_path: Optional[Path] = None,
        **overrides: Any,
    ) -> "FrameworkConfig":
        merged = dict(_DEFAULTS)

        path = (
                config_path
                or os.environ.get("FRAMEWORK_CONFIG_PATH")
                or Path("config.yaml")
        )
        if path:
            path = Path(path)
            if not path.exists():
                raise ConfigurationError(
                    f"Config file not found: {path}", context={"path": str(path)}
                )
            try:
                with open(path) as f:
                    file_config = yaml.safe_load(f) or {}
            except yaml.YAMLError as exc:
                raise ConfigurationError(
                    f"Failed to parse config file {path}: {exc}"
                ) from exc
            merged = _deep_merge(merged, file_config)

        env_overrides = cls._env_overrides()
        merged = _deep_merge(merged, env_overrides)
        merged = _deep_merge(merged, overrides)

        return cls(_raw=merged)

    @staticmethod
    def _env_overrides() -> dict[str, Any]:
        """Simple top-level env var overrides, e.g.
        FRAMEWORK_REFERENCE_DIR=/data/reference
        FRAMEWORK_PROJECT_ROOT=/home/user/project
        Nested (service-level) overrides are intentionally left to
        config.yaml for clarity rather than supporting deep env var paths.
        """
        overrides: dict[str, Any] = {}
        for key, value in os.environ.items():
            if key.startswith(_ENV_PREFIX):
                config_key = key[len(_ENV_PREFIX):].lower()
                if config_key in _DEFAULTS and not isinstance(_DEFAULTS[config_key], dict):
                    overrides[config_key] = value
        return overrides


_GLOBAL_CONFIG: Optional[FrameworkConfig] = None


def get_config() -> FrameworkConfig:
    """Return the process-wide config singleton, loading it on first use."""
    global _GLOBAL_CONFIG
    if _GLOBAL_CONFIG is None:
        _GLOBAL_CONFIG = FrameworkConfig.load()
    return _GLOBAL_CONFIG


def reset_config_for_testing() -> None:
    """Test-only helper to clear the singleton between test cases."""
    global _GLOBAL_CONFIG
    _GLOBAL_CONFIG = None
