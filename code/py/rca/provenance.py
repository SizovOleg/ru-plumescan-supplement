"""
Centralized provenance computation для Run lifecycle.

DNA §2.1 запрет 12 compliance: каждый Run produces immutable Provenance object
that flows через STARTED log → submission → SUCCEEDED log → asset metadata.

Key invariant: same config dict ALWAYS produces same Provenance object.
Hash drift impossible if Provenance computed once и passed by reference.

Per Algorithm §2.4.1 + RNA §9.1 (canonical provenance pattern, P-01.0c).

Usage::

    from rca.provenance import compute_provenance, write_provenance_log

    config = {
        "gas": "CH4",
        "target_year": 2025,
        # ... все параметры Configuration ...
    }
    prov = compute_provenance(
        config=config,
        config_id="default",
        period="2019_2025",
    )
    # prov is frozen Provenance dataclass

    # Pre-submission STARTED log
    write_provenance_log(prov, status="STARTED", gas="CH4",
                         period="2019_2025", asset_id="...")

    # Post-completion SUCCEEDED log
    write_provenance_log(prov, status="SUCCEEDED", gas="CH4",
                         period="2019_2025", asset_id="...",
                         extra={"n_tasks": 12})

    # Asset properties via Earth Engine API
    ee.data.setAssetProperties(asset_id, prov.to_asset_properties())
"""

from __future__ import annotations

import hashlib
import json
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> datetime:
    """Timezone-aware UTC now (_utc_now() deprecated в Python 3.12+)."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Repository paths
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Repo root anchored to file location, не cwd-dependent."""
    return Path(__file__).resolve().parents[3]


def _logs_path() -> Path:
    return _repo_root() / "logs" / "runs.jsonl"


# ---------------------------------------------------------------------------
# Canonical serialization (single point of truth)
# ---------------------------------------------------------------------------


def canonical_serialize(config: dict[str, Any]) -> str:
    """
    Deterministic JSON serialization для config dict.

    Invariants:
        * sort_keys=True — dict ordering doesn't affect hash
        * separators=(',', ':') — eliminates whitespace variations
        * default=str — non-JSON-native objects (e.g. datetime) coerced consistently

    THIS IS THE ONLY ALLOWED SERIALIZATION для params_hash computation.
    Any other serialization will produce different hashes.
    """
    return json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)


def compute_params_hash(config: dict[str, Any]) -> str:
    """SHA-256 of canonical_serialize(config). Deterministic."""
    return hashlib.sha256(canonical_serialize(config).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Immutable Provenance dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Provenance:
    """
    Immutable provenance bundle для one Run.

    Computed once via compute_provenance(...) at process start.
    Pass by reference к all logging + asset metadata operations.

    frozen=True prevents accidental mutation downstream — same Provenance
    object reference flows through entire Run lifecycle.

    Per DNA §2.1 запрет 12 — каждый Run snapshot config полностью.
    """

    config_id: str  # human-readable preset name (e.g., "default")
    params_hash: str  # SHA-256 hex of canonical_serialize(config)
    run_id: str  # f"{config_id}_{period}_{params_hash[:8]}"
    config_serialized: str  # canonical JSON for full audit trail
    algorithm_version: str
    rna_version: str
    build_date: str  # ISO date

    def to_asset_properties(self) -> dict[str, Any]:
        """
        Format Provenance fields для setAssetProperties API.

        Excludes config_serialized (too large для asset properties).
        Full config preserved в logs/runs.jsonl.
        """
        return {
            "config_id": self.config_id,
            "params_hash": self.params_hash,
            "run_id": self.run_id,
            "algorithm_version": self.algorithm_version,
            "rna_version": self.rna_version,
            "build_date": self.build_date,
        }

    def to_log_entry(self, lifecycle_event: str, **extra: Any) -> dict[str, Any]:
        """
        Format Provenance для logs/runs.jsonl entry.

        Args:
            lifecycle_event: "STARTED" | "SUCCEEDED" | "FAILED"
            extra: any additional event-specific fields (gas, period, asset_id,
                started_at, ended_at, n_tasks, ...)

        Returns: dict suitable для json.dumps в jsonl line.
        """
        entry = {
            "event": lifecycle_event,
            "status": lifecycle_event,
            "run_id": self.run_id,
            "params_hash": self.params_hash,
            "config_id": self.config_id,
            "config_serialized": self.config_serialized,
            "algorithm_version": self.algorithm_version,
            "rna_version": self.rna_version,
            "build_date": self.build_date,
            "log_timestamp": _utc_now().isoformat(),
        }
        entry.update(extra)
        return entry


# ---------------------------------------------------------------------------
# Provenance computation
# ---------------------------------------------------------------------------


def compute_provenance(
    config: dict[str, Any],
    config_id: str | None = None,
    period: str | None = None,
    algorithm_version: str = "2.3",
    rna_version: str = "1.2",
) -> Provenance:
    """
    Compute immutable Provenance object.

    Call ONCE at process start. Pass returned object к all subsequent
    operations (logging, submission, asset metadata).

    Args:
        config: full config dict (e.g. from DEFAULT_PRESET)
        config_id: human-readable preset name. If None, uses
            ``config.get("config_preset")`` or ``config.get("config_id")`` or
            "default".
        period: temporal scope identifier (e.g. "2019_2025"). If None, derived
            from config keys (history_year_min/max или target_year).
        algorithm_version: version string (default 2.3 per Algorithm.md v2.3)
        rna_version: version string (default 1.2 per RNA.md v1.2)

    Returns:
        Frozen Provenance dataclass.
    """
    if config_id is None:
        config_id = config.get("config_preset") or config.get("config_id") or "default"

    if period is None:
        if "history_year_min" in config and "history_year_max" in config:
            period = f"{config['history_year_min']}_{config['history_year_max']}"
        elif "target_year" in config:
            year = config["target_year"]
            period = f"2019_{year - 1 if isinstance(year, int) else year}"
        else:
            period = "unknown_period"

    serialized = canonical_serialize(config)
    params_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    run_id = f"{config_id}_{period}_{params_hash[:8]}"

    return Provenance(
        config_id=config_id,
        params_hash=params_hash,
        run_id=run_id,
        config_serialized=serialized,
        algorithm_version=algorithm_version,
        rna_version=rna_version,
        build_date=_utc_now().date().isoformat(),
    )


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def write_provenance_log(
    provenance: Provenance,
    status: str,
    gas: str | None = None,
    period: str | None = None,
    asset_id: str | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """
    Append run lifecycle log entry в `logs/runs.jsonl` from Provenance.

    Per RNA §9 logging spec. JSONL — append-only, одна строка per event.

    Args:
        provenance: immutable Provenance object — flows through entire run
        status: "STARTED" | "SUCCEEDED" | "FAILED"
        gas, period, asset_id: lifecycle context
        started_at, ended_at: timestamps (ISO format)
        extra: any additional event-specific fields

    Returns: path to logs/runs.jsonl.
    """
    log_path = _logs_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    base_extra: dict[str, Any] = {
        "gas": gas,
        "period": period,
        "asset_id": asset_id,
        "started_at": started_at or _utc_now().isoformat(),
        "ended_at": ended_at,
    }
    if extra:
        base_extra.update(extra)

    entry = provenance.to_log_entry(status, **base_extra)

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    return log_path


# ---------------------------------------------------------------------------
# Backwards-compatibility shim для legacy dict-returning API
# ---------------------------------------------------------------------------


def write_run_log(
    run_id: str,
    config_id: str,
    params_hash: str,
    gas: str | None = None,
    period: str | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
    asset_id: str | None = None,
    status: str = "STARTED",
    extra: dict[str, Any] | None = None,
) -> Path:
    """
    Legacy positional API. Prefer ``write_provenance_log(prov, status, ...)``
    going forward, который uses immutable Provenance object.

    Per TD-0024 lessons: this signature allows hash drift между caller contexts.
    New code MUST use Provenance dataclass.
    """
    warnings.warn(
        "write_run_log() positional API is deprecated; use write_provenance_log(prov, "
        "status, ...) с Provenance dataclass to prevent hash drift (TD-0024).",
        DeprecationWarning,
        stacklevel=2,
    )
    log_path = _logs_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "run_id": run_id,
        "config_id": config_id,
        "params_hash": params_hash,
        "gas": gas,
        "period": period,
        "started_at": started_at or _utc_now().isoformat(),
        "ended_at": ended_at,
        "asset_id": asset_id,
        "status": status,
        "log_timestamp": _utc_now().isoformat(),
    }
    if extra:
        entry.update(extra)

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    return log_path


def read_run_log(run_id: str | None = None) -> list[dict[str, Any]]:
    """
    Read `logs/runs.jsonl`. Optionally filter by run_id.

    Returns: list of log entries. Empty list если файл не exists.
    """
    log_path = _logs_path()
    if not log_path.exists():
        return []
    entries = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if run_id is None or e.get("run_id") == run_id:
                entries.append(e)
    return entries
