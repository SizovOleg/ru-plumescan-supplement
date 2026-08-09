"""
Common Plume Schema — унифицированная структура полей для всех каталогов
(наш + reference). Соответствует Algorithm.md §2.1.

Дизайн-решения:

1. **Flat structure, не nested.**
   GEE FeatureCollection properties — плоский dict; pandas DataFrame работает
   с плоскими колонками; round-trip dict ↔ PlumeEvent ↔ GeoJSON Feature
   должен быть прозрачным. Группировка полей выражена комментариями и
   docstring, не вложенностью моделей.

2. **Pydantic v2 (`BaseModel`).**
   Используется `field_validator` и `model_validator` для проверки
   диапазонов и cross-field constraints. `model_config = ConfigDict(...)`
   с `populate_by_name=True` чтобы поле `class_` в Python отображалось
   как `class` во входных/выходных dict (`class` — зарезервированное
   слово Python).

3. **Geometry как dict.**
   Геометрия хранится как GeoJSON-совместимый dict (или None для
   point-only references). Pydantic не валидирует структуру — это
   делает GEE при импорте FeatureCollection.

4. **Configuration provenance — required для `source_catalog="ours"`.**
   DNA §2.1 запрещает Run без полного config snapshot. Валидируется
   через `model_validator(mode='after')`.

5. **Cross-source agreement и ML-readiness — все nullable в v1.**
   Заполняются Comparison Engine (cross-source) и v2 ML pipeline
   (label slots) позже, см. DNA §4.2.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --------------------------------------------------------------------------- #
# Константы Schema                                                            #
# --------------------------------------------------------------------------- #

SCHEMA_VERSION: str = "1.1"
"""Версия Common Plume Schema.

v1.0 → v1.1 (2026-04-29): добавлены 5 dual-baseline-related полей per
Algorithm v2.3 §2.1 + DNA v2.2 §4.2 ML-readiness slots:
  * `delta_vs_regional_climatology` — anomaly от regional baseline
  * `delta_vs_reference_baseline` — anomaly от reference baseline (primary
    в dual baseline architecture)
  * `matched_inside_reference_zone` — bool, automatic false-positive flag
    для events detected внутри protected zone (industrial activity там
    запрещена законом)
  * `baseline_consistency_flag` — true когда reference и regional baselines
    agree within consistency_tolerance_ppb=30
  * `nearest_reference_zone` — zone_id ближайшего reference zone (для
    diagnostic — какой Reference Clean Zone provides baseline для pixel)

Изменение schema — breaking change per DNA §2.3.
"""

GAS_TYPES: tuple[str, ...] = ("CH4", "NO2", "SO2")

CONFIDENCE_LEVELS: tuple[str, ...] = ("low", "medium", "high", "very_high")

# Классы событий per DNA §1.3
EVENT_CLASSES: tuple[str, ...] = (
    "CH4_only",
    "NO2_only",
    "SO2_only",
    "CH4_NO2",
    "NO2_SO2",
    "CH4_SO2",
    "CH4_NO2_SO2",
    "diffuse_CH4",
    "wind_ambiguous",
)

MAGNITUDE_UNITS: tuple[str, ...] = ("ppb", "µmol/m²", "umol/m2", "t/h", "kg/h", "mol/m²")
"""Допустимые единицы magnitude_proxy. ASCII-варианты `umol/m2` поддержаны
для совместимости с системами, не любящими unicode (CSV экспорт)."""

DETECTION_METHODS: tuple[str, ...] = (
    "regional_threshold",
    "beirle_divergence",
    "fioletov_rotation",
    "external_reference",
)
"""`external_reference` для events импортированных из reference catalogs."""

SOURCE_CATALOGS: tuple[str, ...] = (
    "ours",
    "schuit2023",
    "imeo_mars",
    "cams_hotspot",
    "lauvaux2022",
    "carbon_mapper",
    "cherepanova2023",
    "fioletov_so2",
    "beirle2021_no2",
)

SOURCE_TYPES: tuple[str, ...] = (
    "coal_mine",
    "oil_gas",
    "power_plant",
    "metallurgy",
    "urban",
    "wetland",
    "other",
)


# --------------------------------------------------------------------------- #
# qa_flags vocabulary (v1.1, P-02.0a Шаг 3)                                   #
#                                                                             #
# Per RFC v2 Decision 6 + TD-0030: qa_flags is a comma-separated string       #
# of tokens из enumerated VALID_QA_FLAGS set. Encoding rather than explicit   #
# schema fields keeps schema v1.1 stable; формализация в schema v1.2 после    #
# year usage observation (TD-0030).                                            #
# --------------------------------------------------------------------------- #

VALID_QA_FLAGS: frozenset[str] = frozenset(
    {
        # Repeatability (RFC v2 Decision 6)
        "repeatable_event",  # ≥2 detections within 30d (60d winter)
        "single_detection_candidate",  # 1 detection only, не winter
        "single_detection_winter_bias",  # 1 detection в winter (sparse sampling)
        "winter_sparse_sampling",  # coverage_fraction < 0.3 в repeatability window
        # Transboundary (TD-0017 Phase 2A light)
        "transboundary_easterly_transport_suspected",  # 24h ERA5 trajectory shows easterly
        # Zone-boundary (TD-0021)
        "near_zone_boundary",  # centroid within 100 km of 57.5°N or 62°N
        "consistency_tolerance_inflated",  # tolerance increased due к boundary
        # Wind (RFC v2 Decision 4)
        "wind_speed_below_threshold",  # < 2 m/s — alignment skipped, wind_consistent=null
        # Manual override (Algorithm §6)
        "manual_attribution_override",  # event_overrides.json applied
        # Validation
        "synthetic_injection_test",  # synthetic event для validation
        "regression_test_event",  # known event для regression
    }
)


def validate_qa_flags(flags_str: str | None) -> bool:
    """
    Validate qa_flags string — comma-separated tokens из VALID_QA_FLAGS.

    Empty / None → valid (no flags).
    All tokens must be в VALID_QA_FLAGS set.
    Whitespace around tokens stripped.

    Args:
        flags_str: e.g. "repeatable_event,near_zone_boundary" или None.

    Returns: True if all tokens valid OR empty/None; False otherwise.
    """
    if not flags_str:  # None or empty string
        return True
    tokens = [t.strip() for t in flags_str.split(",") if t.strip()]
    return all(token in VALID_QA_FLAGS for token in tokens)


# --------------------------------------------------------------------------- #
# Модель PlumeEvent                                                           #
# --------------------------------------------------------------------------- #


class PlumeEvent(BaseModel):
    """
    Единичное событие (наш detection ИЛИ reference catalog entry) в Common
    Plume Schema. См. Algorithm.md §2.1 для исчерпывающего описания полей.

    Группы полей (выражены комментариями ниже, не вложенными моделями):

    - Идентификация: `event_id`, `source_catalog`, `source_event_id`,
      `schema_version`, `ingestion_date`.
    - Базовая атрибутика: `gas`, `date_utc`, `time_utc`, `orbit`.
    - Геометрия: `lon`, `lat`, `geometry`, `area_km2`, `n_pixels`.
    - Detection metrics: `max_z`, `mean_z`, `max_delta`, `mean_delta`,
      `detection_method`.
    - Wind context: `wind_u`, `wind_v`, `wind_speed`, `wind_dir_deg`,
      `plume_axis_deg`, `wind_alignment_score`, `wind_source`.
    - Source attribution: `nearest_source_id`, `nearest_source_distance_km`,
      `nearest_source_type`.
    - Magnitude proxy: `magnitude_proxy`, `magnitude_proxy_unit`.
    - Quantification (experimental): `ime_kg`, `q_kg_h_experimental`,
      `q_uncertainty_factor`, `quantification_method`,
      `quantification_disclaimer`.
    - Classification: `class_` (alias `class`), `confidence`,
      `confidence_score`, `qa_flags`.
    - Cross-source agreement: `matched_*`, `*_event_id`, `agreement_score`,
      `last_comparison_date`.
    - Configuration provenance: `algorithm_version`, `config_id`,
      `params_hash`, `run_id`, `run_date`. Required for `source_catalog="ours"`.
    - ML-readiness slots: `expert_label`, `label_source`, `label_date`,
      `label_confidence`, `feature_vector`. Nullable in v1.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        extra="forbid",
    )

    # ---- Identification ----------------------------------------------------
    event_id: str = Field(
        ...,
        description='Уникальный ID, формат "<source>_<gas>_<YYYYMMDD>_<lat6>_<lon6>".',
        min_length=1,
    )
    source_catalog: str = Field(..., description="Источник: ours / schuit2023 / imeo_mars / ...")
    source_event_id: str = Field(..., description="Original ID в reference catalog или ours_id.")
    schema_version: str = Field(default=SCHEMA_VERSION, description='Версия Common Schema, "1.0".')
    ingestion_date: date = Field(..., description="Дата ingestion в нашу систему (UTC).")

    # ---- Базовая атрибутика ------------------------------------------------
    gas: str = Field(..., description="CH4 | NO2 | SO2.")
    date_utc: date = Field(..., description="Дата TROPOMI overpass (UTC).")
    time_utc: time | None = Field(None, description="Время overpass; None для multi-day aggregate.")
    orbit: int | None = Field(None, description="TROPOMI orbit; None для reference catalog.")

    # ---- Геометрия ---------------------------------------------------------
    lon: float = Field(..., ge=-180.0, le=180.0, description="Centroid longitude WGS84.")
    lat: float = Field(..., ge=-90.0, le=90.0, description="Centroid latitude WGS84.")
    geometry: dict[str, Any] | None = Field(
        None,
        description="GeoJSON polygon dict; None для point-only reference.",
    )
    area_km2: float | None = Field(None, ge=0.0, description="Object area; None для point-only.")
    n_pixels: int | None = Field(None, ge=0, description="Число валидных пикселей.")

    # ---- Detection metrics (наш source) -----------------------------------
    max_z: float | None = Field(None, description="Max Z-score над объектом (ours only).")
    mean_z: float | None = Field(None, description="Mean Z-score.")
    max_delta: float | None = Field(None, description="Max Δ над фоном, в исходных единицах газа.")
    mean_delta: float | None = Field(None, description="Mean Δ.")
    detection_method: str | None = Field(
        None,
        description="regional_threshold | beirle_divergence | fioletov_rotation | external_reference.",
    )

    # ---- Wind context (ERA5 hourly) ---------------------------------------
    wind_u: float | None = Field(None, description="m/s.")
    wind_v: float | None = Field(None, description="m/s.")
    wind_speed: float | None = Field(None, ge=0.0, description="sqrt(u² + v²), m/s.")
    wind_dir_deg: float | None = Field(
        None, ge=0.0, le=360.0, description="Направление ветра, °N (атмосферная конвенция)."
    )
    plume_axis_deg: float | None = Field(
        None, ge=0.0, le=360.0, description="Ось плюма (centroid → max_z); None если объект < 3 px."
    )
    wind_alignment_score: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="|cos(plume_axis - wind_dir)|; None если plume_axis None.",
    )
    wind_source: str | None = Field(
        None, description='Default "ERA5_HOURLY" — declared limitation.'
    )

    # ---- Source attribution -----------------------------------------------
    nearest_source_id: str | None = Field(None, description="ID ближайшего industrial source.")
    nearest_source_distance_km: float | None = Field(None, ge=0.0)
    nearest_source_type: str | None = Field(
        None,
        description="coal_mine | oil_gas | power_plant | metallurgy | urban | wetland | other.",
    )

    # ---- Magnitude proxy --------------------------------------------------
    magnitude_proxy: float | None = Field(None, description="Числовое значение magnitude.")
    magnitude_proxy_unit: str | None = Field(None, description="ppb | µmol/m² | t/h | ...")

    # ---- Quantification (experimental, см. Algorithm §6) ------------------
    ime_kg: float | None = Field(None, ge=0.0, description="IME mass; None для NO2/SO2.")
    q_kg_h_experimental: float | None = Field(None, description="Q estimate с disclaimer.")
    q_uncertainty_factor: float | None = Field(
        None, ge=1.0, description="Multiplicative uncertainty, e.g. 1.5 = ±50%."
    )
    quantification_method: str | None = Field(
        None,
        description="schuit2023_ime_10m | schuit2023_ime_pbl | fioletov_full_fit | fioletov_simplified.",
    )
    quantification_disclaimer: str | None = Field(
        None, description="Текст для UI display рядом с Q value."
    )

    # ---- Classification ---------------------------------------------------
    class_: str | None = Field(
        None,
        alias="class",
        description="Класс события — см. EVENT_CLASSES (DNA §1.3).",
    )
    confidence: str | None = Field(None, description="low | medium | high | very_high.")
    confidence_score: float | None = Field(
        None, ge=0.0, le=1.0, description="Numerical confidence перед discretization."
    )
    qa_flags: str | None = Field(
        None,
        description=(
            "Comma-separated flags from VALID_QA_FLAGS vocabulary (e.g. "
            "'repeatable_event,near_zone_boundary'). См. validate_qa_flags()."
        ),
    )

    # ---- Dual baseline anomaly fields (NEW в v1.1, Algorithm v2.3 §2.1) --
    delta_vs_regional_climatology: float | None = Field(
        None,
        description="Anomaly vs regional climatology baseline (industrial buffer "
        "exclusion). Algorithm §3.4.3 secondary baseline.",
    )
    delta_vs_reference_baseline: float | None = Field(
        None,
        description="Anomaly vs reference baseline (positive-space, anchored "
        "в zapovedniks). Algorithm §3.4.3 primary baseline.",
    )
    baseline_consistency_flag: bool | None = Field(
        None,
        description="True если |reference - regional| < consistency_tolerance_ppb "
        "(default 30). False сигнализирует о возможной contamination в regional.",
    )
    matched_inside_reference_zone: bool | None = Field(
        None,
        description="True если pixel внутри boundary одного из active Reference "
        "Clean Zones. Automatic false-positive flag (industrial activity внутри "
        "protected zones запрещена федеральным законом).",
    )
    nearest_reference_zone: str | None = Field(
        None,
        description="zone_id ближайшего reference zone (diagnostic — какая zone "
        "provides baseline через latitude stratification, Algorithm §11.3 Step 4).",
    )

    # ---- Cross-source agreement (Comparison Engine fills these) ----------
    matched_schuit2023: bool | None = None
    schuit_event_id: str | None = None
    matched_imeo_mars: bool | None = None
    imeo_event_id: str | None = None
    matched_cams: bool | None = None
    cams_event_id: str | None = None
    agreement_score: int | None = Field(
        None, ge=0, description="Sum(matched_*); 0..N reference catalogs."
    )
    last_comparison_date: date | None = None

    # ---- Configuration provenance (required для ours) ---------------------
    algorithm_version: str | None = Field(None, description='"2.2" — текущая версия Algorithm.')
    config_id: str | None = Field(
        None,
        description="default | schuit_eq | imeo_eq | sensitive | conservative | custom_<sha8>.",
    )
    params_hash: str | None = Field(None, description="SHA-256 от сериализованного Configuration.")
    run_id: str | None = Field(None, description='"<config_id>_<YYYYMMDD>_<sha8>".')
    run_date: date | None = None

    # ---- ML-readiness slots (NULL в v1, заполняются позже) ----------------
    expert_label: str | None = Field(
        None,
        description="confirmed_plume | artifact | wetland | wind_ambiguous | ...",
    )
    label_source: str | None = None
    label_date: date | None = None
    label_confidence: int | None = Field(None, ge=1, le=5)
    feature_vector: str | None = Field(None, description="JSON-encoded для будущего ML.")

    # ----------------------------------------------------------------------- #
    # Validators                                                              #
    # ----------------------------------------------------------------------- #

    @field_validator("gas")
    @classmethod
    def _validate_gas(cls, value: str) -> str:
        """Газ должен быть одним из CH4 / NO2 / SO2."""
        if value not in GAS_TYPES:
            raise ValueError(f"gas must be one of {GAS_TYPES}, got {value!r}")
        return value

    @field_validator("source_catalog")
    @classmethod
    def _validate_source_catalog(cls, value: str) -> str:
        if value not in SOURCE_CATALOGS:
            raise ValueError(f"source_catalog must be one of {SOURCE_CATALOGS}, got {value!r}")
        return value

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(
                f"schema_version mismatch: expected {SCHEMA_VERSION!r}, got {value!r}. "
                "Schema migration required."
            )
        return value

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: str | None) -> str | None:
        if value is not None and value not in CONFIDENCE_LEVELS:
            raise ValueError(f"confidence must be one of {CONFIDENCE_LEVELS}, got {value!r}")
        return value

    @field_validator("class_")
    @classmethod
    def _validate_class(cls, value: str | None) -> str | None:
        if value is not None and value not in EVENT_CLASSES:
            raise ValueError(f"class must be one of {EVENT_CLASSES}, got {value!r}")
        return value

    @field_validator("magnitude_proxy_unit")
    @classmethod
    def _validate_magnitude_unit(cls, value: str | None) -> str | None:
        if value is not None and value not in MAGNITUDE_UNITS:
            raise ValueError(
                f"magnitude_proxy_unit must be one of {MAGNITUDE_UNITS}, got {value!r}"
            )
        return value

    @field_validator("detection_method")
    @classmethod
    def _validate_detection_method(cls, value: str | None) -> str | None:
        if value is not None and value not in DETECTION_METHODS:
            raise ValueError(f"detection_method must be one of {DETECTION_METHODS}, got {value!r}")
        return value

    @field_validator("nearest_source_type")
    @classmethod
    def _validate_source_type(cls, value: str | None) -> str | None:
        if value is not None and value not in SOURCE_TYPES:
            raise ValueError(f"nearest_source_type must be one of {SOURCE_TYPES}, got {value!r}")
        return value

    @field_validator("qa_flags")
    @classmethod
    def _validate_qa_flags_tokens(cls, value: str | None) -> str | None:
        """All tokens должны быть в VALID_QA_FLAGS vocabulary (P-02.0a Шаг 3)."""
        if not validate_qa_flags(value):
            tokens = [t.strip() for t in (value or "").split(",") if t.strip()]
            invalid = [t for t in tokens if t not in VALID_QA_FLAGS]
            raise ValueError(
                f"qa_flags contains invalid tokens {invalid}; "
                f"valid tokens are {sorted(VALID_QA_FLAGS)}"
            )
        return value

    @model_validator(mode="after")
    def _validate_provenance_for_ours(self) -> PlumeEvent:
        """
        DNA §2.1: «Не выдавать Run без полного config snapshot».
        Для events с `source_catalog="ours"` все configuration provenance
        поля обязательны.
        """
        if self.source_catalog == "ours":
            required = {
                "algorithm_version": self.algorithm_version,
                "config_id": self.config_id,
                "params_hash": self.params_hash,
                "run_id": self.run_id,
                "run_date": self.run_date,
                "detection_method": self.detection_method,
            }
            missing = [name for name, val in required.items() if val is None]
            if missing:
                raise ValueError(
                    f"source_catalog='ours' requires config snapshot fields: missing {missing}. "
                    "См. DNA §2.1, Algorithm §2.1."
                )
        return self

    @model_validator(mode="after")
    def _validate_agreement_score(self) -> PlumeEvent:
        """
        Если matched_* поля установлены, agreement_score должен быть согласован
        (sum of matched booleans). Допустимо None если comparison не запускался.
        """
        if self.agreement_score is None:
            return self

        explicitly_matched = [
            self.matched_schuit2023,
            self.matched_imeo_mars,
            self.matched_cams,
        ]
        observed_sum = sum(1 for m in explicitly_matched if m is True)
        # Если хотя бы одно matched_* выставлено явно (True/False), проверяем sum.
        any_set = any(m is not None for m in explicitly_matched)
        if any_set and self.agreement_score != observed_sum:
            raise ValueError(
                f"agreement_score={self.agreement_score} inconsistent with "
                f"matched_* booleans (sum={observed_sum})"
            )
        return self


# --------------------------------------------------------------------------- #
# Helper functions                                                            #
# --------------------------------------------------------------------------- #


def from_dict(data: dict[str, Any]) -> PlumeEvent:
    """
    Validation entry point. Принимает dict (например, из CSV row или
    JSON), возвращает валидированный `PlumeEvent`. Поднимает
    `pydantic.ValidationError` при невалидных данных.

    `class` (зарезервированное слово Python) маппится на `class_`
    автоматически через `populate_by_name=True`.
    """
    return PlumeEvent.model_validate(data)


def to_geojson_feature(event: PlumeEvent) -> dict[str, Any]:
    """
    Конвертирует `PlumeEvent` в GeoJSON Feature dict. Геометрия берётся
    из `event.geometry`; если она None — используется Point из
    (lon, lat). Properties — все остальные поля (по `by_alias=True`,
    т.е. `class_` сериализуется как `class`).
    """
    properties = event.model_dump(mode="json", by_alias=True, exclude={"geometry"})
    geometry = (
        event.geometry
        if event.geometry is not None
        else {
            "type": "Point",
            "coordinates": [event.lon, event.lat],
        }
    )
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": properties,
    }


def validate_batch(
    events: list[dict[str, Any]],
) -> tuple[list[PlumeEvent], list[tuple[int, str]]]:
    """
    Валидирует список dict-ов. Возвращает (valid_events, invalid_with_errors)
    где invalid_with_errors — список tuples (index, error_message).

    Используется RCA Ingester для bulk validation reference catalogs:
    invalid records логируются, не прерывают ingest.
    """
    valid: list[PlumeEvent] = []
    invalid: list[tuple[int, str]] = []
    for idx, data in enumerate(events):
        try:
            valid.append(from_dict(data))
        except Exception as exc:  # pydantic.ValidationError или прочие
            invalid.append((idx, str(exc)))
    return valid, invalid
