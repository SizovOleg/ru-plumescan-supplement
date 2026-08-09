"""
Abstract base class для Reference Catalog Ingesters.

Каждый Ingester (Schuit2023, ImeoMars, CamsHotspot, ...) реализует:
  * `fetch()` — получить raw данные из источника (CSV / API / Zenodo).
  * `validate()` — verify against `DECLARED_STATS` (DNA §2.2: «Reference catalog
    содержание верифицируется при ingestion»).
  * `to_common_schema()` — конвертация в Common Plume Schema DataFrame.

Конкретные реализации — в `rca/ingesters/`. См. RNA.md §5.1, §5.2 (Schuit),
§5.3 (IMEO MARS), §5.4 (CAMS).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    import pandas as pd


class ValidationError(Exception):
    """
    Поднимается, когда reference catalog ingestion даёт расхождение
    с DECLARED_STATS > 5% (CLAUDE.md §5.5, §7).

    При >10% — эскалация человеку (CLAUDE.md §7).
    """


class BaseIngester(ABC):
    """
    Abstract base для всех Reference Catalog Ingesters.

    Override в наследниках:
      * `SOURCE_NAME`: ключ источника, должен совпадать с одним из
        `rca.common_schema.SOURCE_CATALOGS`.
      * `DECLARED_STATS`: dict с заявленной издателем статистикой
        (n_events, time_range, license, doi, ...) — используется в
        `validate()` для sanity check.

    Pipeline `ingest(asset_id)`:
      1. `fetch()` → raw DataFrame.
      2. `validate(raw)` → dict с verification metrics (или raises
         ValidationError при расхождении > 5%).
      3. `to_common_schema(raw)` → DataFrame с колонками Common Schema.
      4. `upload_to_gee(common, asset_id)` → создаёт GEE Asset
         (FeatureCollection).

    Возвращает `asset_id` строкой.
    """

    SOURCE_NAME: ClassVar[str] = ""
    DECLARED_STATS: ClassVar[dict] = {}

    @abstractmethod
    def fetch(self) -> pd.DataFrame:
        """
        Скачать raw данные источника. Реализация специфична для каждого
        Ingester: HTTP GET для Zenodo/CAMS, REST API для IMEO MARS, и т.д.
        """

    @abstractmethod
    def validate(self, raw: pd.DataFrame) -> dict:
        """
        Проверить raw против `DECLARED_STATS`. Минимум: `n_events`
        в пределах ±5% от заявленного. Возвращает dict с метриками
        (n_actual, deviation, ...).

        Raises:
            ValidationError: при расхождении > 5%.
        """

    @abstractmethod
    def to_common_schema(self, raw: pd.DataFrame) -> pd.DataFrame:
        """
        Конвертировать raw DataFrame в Common Plume Schema. Каждая
        строка результата должна быть валидна через
        `rca.common_schema.from_dict(row.to_dict())`.
        """

    def ingest(self, asset_id: str) -> str:
        """
        Полный pipeline: fetch → validate → convert → upload.
        Возвращает GEE Asset ID опубликованного FeatureCollection.
        """
        raw = self.fetch()
        validation_result = self.validate(raw)
        # Логирование validation_result — здесь noop, но логичное место для
        # подключения logger в production (см. RNA.md §9).
        _ = validation_result
        common = self.to_common_schema(raw)
        return self.upload_to_gee(common, asset_id)

    def upload_to_gee(self, common: pd.DataFrame, asset_id: str) -> str:
        """
        Загрузить Common Schema DataFrame как GEE FeatureCollection.

        Реализация в `rca.upload_to_gee.dataframe_to_gee_asset` —
        создаётся в DevPrompt P-05.x когда понадобится первый ingester.
        Здесь — placeholder, поднимающий `NotImplementedError`, чтобы
        тест P-00.0 не падал из-за отсутствия `upload_to_gee.py`.
        """
        try:
            from rca.upload_to_gee import dataframe_to_gee_asset
        except ImportError as exc:  # pragma: no cover — будет реализовано в P-05.x
            raise NotImplementedError(
                "rca.upload_to_gee.dataframe_to_gee_asset ещё не реализован. "
                "См. DevPrompt P-05.x."
            ) from exc
        return dataframe_to_gee_asset(common, asset_id, source=self.SOURCE_NAME)
